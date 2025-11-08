#!/usr/bin/env python3

"""
    bridge.py  - MQTT -> validation -> UDP bridge for simulated drone control.
    
    Features:
    - Load YAML/JSON config
    - Subscribe to MQTT topic
    - Validate safety & sequence constraints
    - Forward valid commands via UDP with timestamp
    - Metrics + periodic status line
    - Robust logging (INFO/DBG) and optional blackbox JSON file logging with rotation
    - Auto-reconnect, graceful shutdown
"""
from __future__ import annotations
import argparse
import json
import logging
import signal
import socket
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional
from utils import now_ms, is_number, haversine_meters, setup_logging, _rc_value

import warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

# third-party deps
try:
    import yaml
    import paho.mqtt.client as mqtt
except Exception as e:
    print("ERROR: One of the third-party deps is not installed.", file=sys.stderr)
    raise

# --------------------------- Config ---------------------------
@dataclass
class Geofence:
    center_lat: float
    center_lon: float
    radius_m: float
    max_altitude_m: float
    min_altitude_m: float


"""
    MQTT connection details + command topic to subscribe to.
"""
@dataclass
class MqttCfg:
    broker: str = "localhost"
    port: int = 1888
    topic: str = "mission/drone/1/command"


@dataclass
class UdpCfg:
    host: str = "127.0.0.1"
    port: int = 5001


@dataclass
class LogCfg:
    level: str = "INFO"
    blackbox: bool = False
    file: Optional[str] = None


@dataclass
class Config:
    mqtt: MqttCfg
    udp: UdpCfg
    geofence: Geofence
    logging: LogCfg


def load_config(path: str) -> Config:
    with open(path, "r", encoding="utf-8") as f:
        if path.endswith(".json"):
            raw = json.load(f)
        else:
            raw = yaml.safe_load(f)
    mqttc = MqttCfg(**raw.get("mqtt", {}))
    udpc = UdpCfg(**raw.get("udp", {}))
    logc = LogCfg(**raw.get("logging", {}))
    gf = raw.get("geofence", {})
    required = ["center_lat", "center_lon", "radius_m", "max_altitude_m", "min_altitude_m"]
    for k in required:
        if k not in gf:
            raise ValueError(f"Missing geofence.{k} in config")
    geofence = Geofence(**gf)
    return Config(mqtt=mqttc, udp=udpc, geofence=geofence, logging=logc)



# --------------------------- Validator & State ---------------------------
"""
    Simple command sequence state machine: disarmed -> arm -> takeoff -> (goto)* -> land -> disarm
    Using Mealy machine ideology outputs depend on both the current state and the current input
    For now input is only a command from the user, potentially it should be the correlation of data from
    nearby instances(drones), current state value and input from SkyBrush.
"""
class SequenceState:
    def __init__(self) -> None:
        self.armed = False
        self.in_flight = False
        self.last_cmd: Optional[str] = None

    def validate_sequence(self, cmd: str) -> Optional[str]:
        if cmd == "arm":
            if self.armed:
                return "already armed"
            return None
        if cmd == "takeoff":
            if not self.armed:
                return "must arm first"
            if self.in_flight:
                return "already in flight"
            return None
        if cmd == "goto":
            if not self.in_flight:
                return "must takeoff before goto"
            return None
        if cmd == "land":
            if not self.in_flight:
                return "not in flight"
            return None
        if cmd == "disarm":
            if self.in_flight:
                return "must land before disarm"
            if not self.armed:
                return "not armed"
            return None
        return None

    def apply(self, cmd: str) -> None:
        if cmd == "arm":
            self.armed = True
        elif cmd == "takeoff":
            self.in_flight = True
        elif cmd == "land":
            self.in_flight = False
        elif cmd == "disarm":
            self.armed = False
        self.last_cmd = cmd


class Validator:
    def __init__(self, geofence: Geofence, seq_state: SequenceState, logger: logging.Logger) -> None:
        self.gf = geofence
        self.seq = seq_state
        self.log = logger
    """
        Returns (ok, reason, normalized_payload)
        normalized_payload: {"cmd": str, "params": {...}}
    """
    def validate(self, payload: Dict[str, Any]) -> (bool, Optional[str], Dict[str, Any]):
        if not isinstance(payload, dict):
            return False, "payload not a JSON object", {}

        cmd = payload.get("cmd")
        if cmd not in {"arm", "takeoff", "goto", "land", "disarm"}:
            return False, f"unknown cmd '{cmd}'", {}

        seq_err = self.seq.validate_sequence(cmd)
        if seq_err:
            return False, f"sequence violation: {seq_err}", {}

        params: Dict[str, Any] = {}
        # Data validation per command
        if cmd == "takeoff":
            alt = payload.get("alt")
            if not is_number(alt):
                return False, "takeoff.alt must be a number", {}
            if alt < self.gf.min_altitude_m or alt > self.gf.max_altitude_m:
                return False, f"takeoff.alt {alt}m outside [{self.gf.min_altitude_m}, {self.gf.max_altitude_m}]m", {}
            params = {"alt": float(alt)}

        elif cmd == "goto":
            for k in ("lat", "lon", "alt"):
                if k not in payload:
                    return False, f"goto missing field '{k}'", {}
                if not is_number(payload[k]):
                    return False, f"goto.{k} must be a number", {}
            lat = float(payload["lat"])
            lon = float(payload["lon"])
            alt = float(payload["alt"])
            if alt < self.gf.min_altitude_m or alt > self.gf.max_altitude_m:
                return False, f"goto.alt {alt}m outside [{self.gf.min_altitude_m}, {self.gf.max_altitude_m}]m", {}
            dist = haversine_meters(self.gf.center_lat, self.gf.center_lon, lat, lon)
            if dist > self.gf.radius_m:
                return False, f"goto target {dist:.1f}m outside geofence radius {self.gf.radius_m}m", {}
            params = {"lat": lat, "lon": lon, "alt": alt}

        return True, None, {"cmd": cmd, "params": params}



# --------------------------- Bridge ---------------------------
"""
    Main service orchestrator:
    MQTT subscribe -> validate -> UDP forward + metrics.
"""
class Bridge:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.log = logging.getLogger("bridge")
        self.seq_state = SequenceState()
        self.validator = Validator(cfg.geofence, self.seq_state, self.log)

        # metrics
        self.metrics = {
            "recv": 0,
            "valid": 0,
            "invalid": 0,
            "sent": 0,
            "errors": 0,
            "reconnects": 0,
        }
        self._shutdown = threading.Event()

        self.udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.udp_addr = (self.cfg.udp.host, self.cfg.udp.port)

        self.mqtt = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"illuminate-bridge-{int(time.time())}")
        # Auto reconnect backoff
        self.mqtt.reconnect_delay_set(min_delay=1, max_delay=30)
        self.mqtt.on_connect = self.on_connect
        self.mqtt.on_disconnect = self.on_disconnect
        self.mqtt.on_message = self.on_message

    def on_connect(self, client, userdata, flags, reason_code, properties=None):
        if _rc_value(reason_code) == 0:
            self.log.info("Connected to MQTT %s:%s", self.cfg.mqtt.broker, self.cfg.mqtt.port)
            client.subscribe(self.cfg.mqtt.topic)
            self.log.info("Subscribed to topic: %s", self.cfg.mqtt.topic)
        else:
            self.log.error("MQTT connect failed rc=%s", reason_code)

    def on_disconnect(self, client, userdata, reason_code, properties=None):
        if _rc_value(reason_code) != 0:
            self.metrics["reconnects"] += 1
            self.log.warning("Unexpected MQTT disconnect (rc=%s). Will auto-reconnect.", reason_code)
        else:
            self.log.info("MQTT disconnected.")

    def on_message(self, client, userdata, msg):
        self.metrics["recv"] += 1
        raw = msg.payload.decode("utf-8", errors="replace")
        self.log.debug("MQTT message on %s: %s", msg.topic, raw)
        try:
            payload = json.loads(raw)
        except Exception as e:
            self.metrics["invalid"] += 1
            self.metrics["errors"] += 1
            self.log.error("Malformed JSON: %s", e)
            return

        ok, reason, normalized = self.validator.validate(payload)
        if not ok:
            self.metrics["invalid"] += 1
            self.log.warning("Invalid command: %s - %s", payload.get("cmd"), reason)
            return

        try:
            self.seq_state.apply(normalized["cmd"])
            out = {
                "ts_ms": now_ms(),
                "cmd": normalized["cmd"],
                "params": normalized["params"],
            }
            data = json.dumps(out).encode("utf-8")
            self.udp_sock.sendto(data, self.udp_addr)
            self.metrics["valid"] += 1
            self.metrics["sent"] += 1
            self.log.info("Forwarded to drone: %s", out)
        except Exception as e:
            self.metrics["errors"] += 1
            self.log.error("UDP send failed: %s", e)

    # ---- Lifecycle ----
    def status_loop(self):
        while not self._shutdown.is_set():
            time.sleep(5)
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
            m = self.metrics
            print(f"[{ts}] Status: recv={m['recv']} valid={m['valid']} invalid={m['invalid']} sent={m['sent']} errors={m['errors']} reconnects={m['reconnects']}")
            sys.stdout.flush()

    def start(self):
        self.log.info("Starting bridge ... UDP -> %s:%s | MQTT topic=%s",
                      self.cfg.udp.host, self.cfg.udp.port, self.cfg.mqtt.topic)
        self.mqtt.connect(self.cfg.mqtt.broker, self.cfg.mqtt.port, keepalive=30)
        self.mqtt.loop_start()
        status_thr = threading.Thread(target=self.status_loop, daemon=True)
        status_thr.start()

    def stop(self):
        self._shutdown.set()
        try:
            self.mqtt.loop_stop()
            self.mqtt.disconnect()
        except Exception:
            pass
        try:
            self.udp_sock.close()
        except Exception:
            pass
        self.log.info("Bridge stopped.")

# --------------------------- Main ---------------------
def parse_args():
    p = argparse.ArgumentParser(description="MQTT -> Validation -> UDP bridge")
    p.add_argument("--config", "-c", required=True, help="Path to YAML/JSON config")
    return p.parse_args()


def main():
    args = parse_args()
    try:
        cfg = load_config(args.config)
    except Exception as e:
        print(f"Failed to load config: {e}", file=sys.stderr)
        sys.exit(2)

    setup_logging(cfg.logging.level, blackbox=cfg.logging.blackbox, logfile=cfg.logging.file)
    bridge = Bridge(cfg)

    def _sig_handler(signum, frame):
        logging.getLogger("bridge").info("Received signal %s, shutting down ...", signum)
        bridge.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)

    bridge.start()
    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        bridge.stop()


if __name__ == "__main__":
    main()
