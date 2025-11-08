# utils.py
"""
Utility and helper functions ...
"""
import os
import sys
import time
import math
import json
import logging
from logging.handlers import RotatingFileHandler

# Generic helpers ---------------------------------------------------------------------

"""Return current time in milliseconds."""
def now_ms() -> int:
    return int(time.time() * 1000)

"""Return True if x is a finite float."""
def is_number(x) -> bool:
    try:
        f = float(x)
        return math.isfinite(f)
    except Exception:
        return False

"""Return distance between two lat/lon pairs in meters."""
def haversine_meters(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

# Logging helpers  -----------------------------------------------------------------------

class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": int(time.time() * 1000),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        # Include any structured extras
        for k in ("topic", "payload", "event", "metrics"):
            if hasattr(record, k):
                payload[k] = getattr(record, k)
        return json.dumps(payload, ensure_ascii=False)

def setup_logging(level: str = "INFO", blackbox: bool = False, logfile: str | None = None):
    norm = (level or "INFO").upper()
    if norm == "DBG":
        norm = "DEBUG"
    lvl = getattr(logging, norm, logging.INFO)

    for h in list(logging.root.handlers):
        logging.root.removeHandler(h)

    logging.root.setLevel(logging.DEBUG)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(lvl)
    ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S"))
    logging.root.addHandler(ch)

    # Blackbox JSON file 
    if blackbox or logfile:
        path = logfile or "logs/bridge.blackbox.log"
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fh = RotatingFileHandler(path, maxBytes=5 * 1024 * 1024, backupCount=3)
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(JsonFormatter())
        logging.root.addHandler(fh)
        logging.getLogger("bridge").info("Blackbox logging enabled -> %s", path)

### socket helpers 

"""Normalize paho-mqtt v2 ReasonCode or plain int to an int-like value."""
def _rc_value(rc):
    return getattr(rc, "value", rc)

