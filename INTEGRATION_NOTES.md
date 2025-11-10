# INTEGRATION_NOTES.md

## 1. Overview
This project implements a **bridge service** between the **Skybrush control system** and the drone fleet.  
It listens for drone commands from **MQTT**, validates them against safety and mission rules, and forwards valid commands to the drone networ via **MAVLink**.
The goal is to provide a **safe, modular, and observable** middleware layer between the control software and the UAVs.

---

## 2. Integration with Skybrush
- **Skybrush** publishes mission plans and commands to MQTT topics (e.g., `mission/drone/<id>/command`).
- The bridge subscribes to these topics and performs:
  - **Validation** (geofence, altitude limits, command order)
  - **Normalization** (converting mission data into drone-level commands)
  - **Forwarding** (sending valid commands to UDP or MAVLink endpoints)
- It can later parse simplified **Skybrush `.skyc` mission files** and translate them into validated sequences of commands, making it compatible with both live and pre-planned missions.

---

## 3. Communication & Protocols
- **MQTT**: lightweight publish/subscribe system for command distribution.  
  - Chosen for its **low latency**, **reliability**, and **built-in QoS** levels.
- **MAVLink**: will replace UDP in production. It’s the **industry standard protocol** for PX4 and ArduPilot drones.  
  - Allows bidirectional communication — command + telemetry.
  - Libraries: `pymavlink` or `MAVSDK-Python`.

---

## 4. Validation & Safety
Before forwarding commands, the bridge enforces:
- **Sequence safety:** correct order of `arm → takeoff → goto → land → disarm`.
- **Geofence checks:** distance from center point using **Haversine formula**.
- **Altitude limits:** defined min/max to avoid unsafe altitude commands.
- **Payload validation:** ensures all required fields exist and are numeric.

If any validation fails, the command is logged as an error and not sent to the drone.

---

## 5. Logging, Monitoring & Observability
- Console logs (with `INFO` / `DEBUG` / `WARN` / `ERROR` levels).
- **Blackbox JSON logs** written to rotating files for audit and analysis.
- Every message (valid/invalid) increments real-time counters.
  ```
  Status: recv=12 valid=10 invalid=2 sent=10 errors=0 reconnects=1
  ```
- Future integrations:
  - **Prometheus** for metrics scraping.
  - **Grafana** dashboards for real-time drone show monitoring.
  - **Sentry** for runtime error tracking (optional).

---

## 6. Scaling to Multi-Drone Systems

### Architecture
Each drone or small group of drones runs its own **bridge instance**:
- Independent process → isolates failures.
- Each instance subscribes to its own MQTT topic (`mission/drone/<id>/command`).
- All bridges connect to a shared MQTT broker and telemetry aggregator.

### Why this model
- **Fault isolation:** one drone’s error never stops others.
- **Horizontal scalability:** adding more drones means just adding more bridge containers.
- **Low coupling:** no shared global state; coordination handled at MQTT level.

### Tools for Scaling
| Layer | Tool / Framework | Reason |
|-------|------------------|--------|
| Message broker | **Eclipse Mosquitto** or **EMQX** | Lightweight, stable, supports thousands of topics and QoS levels. |
| Containerization | **Docker** / **Docker Compose** | One container per drone bridge for isolation. |
| Orchestration | **Kubernetes** (K8s) | Automates scaling, restart policies, and health monitoring. |
| Metrics | **Prometheus** + **Grafana** | Real-time visibility, alerting, dashboards. |
| Telemetry | **MAVLink** | Direct link to PX4/ArduPilot for position, battery, and status. |

### Scaling Flow Example
1. **Skybrush** publishes 100 commands (one per drone).  
2. **MQTT broker** routes each command to its respective topic.  
3. **100 bridge instances** validate and forward simultaneously.  
4. **Telemetry collectors** gather MAVLink responses (e.g., GPS, battery).  
5. **Prometheus** scrapes bridge metrics; **Grafana** visualizes overall health.

This design allows near-linear scaling and easy failover.  
If one bridge fails, Kubernetes restarts it within seconds, and other drones remain unaffected.


## 7. Future Extensions
- **Web dashboard**: control, status view, mission uploads.
- **Telemetry aggregator**: collects drone data and republishes to MQTT.
- **Auto mission planner**: dynamic waypoint assignment via REST or MQTT.
- **Config hot-reload**: live parameter update without service restart.

---

## 8. Summary
This bridge ensures:
- Safe command validation before flight.
- Compatibility with Skybrush and MAVLink.
- Modular, scalable design suitable for large drone shows.
- Easy monitoring and fault recovery.
