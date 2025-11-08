# INTEGRATION_NOTES

This document describes how the bridge would integrate with Skybrush and real drone protocols (e.g. MAVLink),
and what changes will be needed for production scale.

## 1) Skybrush Integration Strategy

Goal: Consume mission data from Skybrush and execute safely via validated commands.
Input format: 
- Skybrush can publish mission plans over MQTT.
- Extend the bridge with a *mission topic* (e.g., mission/plan/{group}) alongside the per‑drone command topic.
- Parse the mission into an internal structure: Mission { waypoints: [lat, lon, alt, t], safety: { geofence, alt limits }, metadata }.

Parsing & validation:
  - Schema validation (required fields, numeric types, bounds).
  - Temporal constraints (e.g., min/max velocity, separation between drones if applicable).
  - Geofence & altitude checks reused from the current validator.
  - Produce a stream of low-level per drone commands: arm -> takeoff -> goto* -> land with timestamps.

State tracking data structures:
  - MissionState: phase (planning/running/paused/completed) 
  - DroneState: armed, position (from telemetry), battery, failsafe.
  - Registry: drone_id -> DroneState, mission_id  -> MissionState.

Execution:
  - Scheduler converts mission waypoints into timed goto commands per drone
  - Back-pressure if telemetry indicates a drone is lagging; pause/resume per group.

## 2) Real Drone Protocol Integration

Replace UDP simulator with MAVLink (PX4/ArduPilot)

Commands mapping 
## TODO 

Bidirectional comms (telemetry):
  - Run a second channel (or task) that listens to telemetry (HEARTBEAT, GLOBAL_POSITION_INT, SYS_STATUS).
  - Update DroneState and publish summaries back to MQTT (e.g., telemetry/drone/{id}) for Skybrush/ops UI.

Connection strategy:
  - One MAVLink connection per drone (UDP/serial). Reconnect with backoff; surface health via metrics.

# TODO

## 3) Production Considerations (100+ drone show)

Scaling model:

Concurrency:
