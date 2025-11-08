# Illuminate Drones demo project
This repo contains a small service that subscribes to MQTT drone commands, validates them
(altitude, geofence, command sequence), and forwards valid commands to a simulated drone via UDP.
It also includes a simple UDP listener to emulate a drone.

## Prerequisites
- Python 3.11 (
- MacOS 26.0.1 (Didn't have Ubuntu machine with me, but should work fine with any Unix based systems) 
- Mosquitto (MQTT broker) - If you are on Mac by any chance: brew install masquitto, on Ubunto: sudo apt install mosquitto mosquitto-clients
- Python deps: pip install -r requirements.txt

## Files & directories
- bridge.py -main service
- udp_listener.py - simulated drone UDP receiver
- config.yaml - config file
- INTEGRATION_NOTES.md - architecture & integration thoughts
- requirements.txt - dependencies list
- my_debug_logs/ - folder where I left the debug logs of my last run, with all commands combinations validations, and all possible failures verifications

## Run (you will need 4 terminal windows, please keep order of the steps, cause proper ERROR handling is not done yet) 
1) Start MQTT broker in termnial
   - mosquitto -p 1888 -v

2) Start the UDP listener (aka simulated drone) in another terminal/window
   - python udp_listener.py --port 5001

3) Run the bridge in another terminal/window
   - python bridge.py --config config.yaml

    You should see status lines every ~5s, and per-command logs.

4) Test commands in another terminal:
# Valid flow example
    - mosquitto_pub -h localhost -p 1888 -t 'mission/drone/1/command' -m '{"cmd":"arm"}'
    - mosquitto_pub -h localhost -p 1888 -t 'mission/drone/1/command' -m '{"cmd":"takeoff","alt":30.0}'
    - mosquitto_pub -h localhost -p 1888 -t 'mission/drone/1/command' -m '{"cmd":"goto","lat":40.2340,"lon":111.6590,"alt":50.0}'
    - mosquitto_pub -h localhost -p 1888 -t 'mission/drone/1/command' -m '{"cmd":"land"}'
    - mosquitto_pub -h localhost -p 1888 -t 'mission/drone/1/command' -m '{"cmd":"disarm"}'

# Validation failures
   # Too high
    - mosquitto_pub -h localhost -p 1888 -t 'mission/drone/1/command' -m '{"cmd":"goto","lat":40.2340,"lon":111.6590,"alt":150.0}'
   # Outside geofence
    - mosquitto_pub -h localhost -p 1888 -t 'mission/drone/1/command' -m '{"cmd":"goto","lat":40.9999,"lon":111.6590,"alt":50.0}'
   # Not armed yet
    - mosquitto_pub -h localhost -p 1888 -t 'mission/drone/1/command' -m '{"cmd":"takeoff","alt":30.0}'
   # Must land first
    - mosquitto_pub -h localhost -p 1888 -t 'mission/drone/1/command' -m '{"cmd":"disarm"}' 

## Just playing with specific validation errors :)
- Missing fields: {"cmd":"goto","lat":1.0}
- Non‑numeric: {"cmd":"takeoff","alt":"NaN"}
- Out of sequence: {"cmd":"goto","lat":0,"lon":0,"alt":20}

## Logging
- Per-command logs (INFO/DBG)
- Status line every ~5s:
e.g. [2024-11-04 14:32:15] Status: recv=12 valid=10 invalid=2 sent=10 errors=0 reconnects=1

## Notes & Assumptions
- The command sequence modeled is: arm -> takeoff -> goto* -> land -> disarm.
- Geofence validation uses the Haversine formula for great-circle distance in meters.
- The bridge accepts YAML or JSON config via `--config` (filename extension determines parser).

## Debugging Tips
- Use logging.level: "DBG" in config.yaml for verbose traces.
- Turn on BlackBox in config file for recording logs.
- To simulate MQTT reconnects, restart Mosquitto while the bridge is running.
- To test UDP failures, point udp.host to a non‑routable address.
