# UGV Robot Control Skill

Control a Waveshare UGV robot via its Flask REST API (`/api/ugv/*`).

## Setup

The Flask app must be running on the Raspberry Pi (default port 5000).
Set `UGV_HOST` env var or use `--host` with `ugv_client.py` if not on localhost.

Default: `http://<raspberry-pi-ip>:5000`

## Available API Endpoints

All endpoints require the Flask server to be running.

### Movement (always auto-stops after `duration` seconds)

```
POST /api/ugv/move
Body: {"direction": "forward"|"backward"|"left"|"right"|"spin_left"|"spin_right",
       "speed": 0.0-0.8,      # default 0.3 (slow)
       "duration": 0.1-5.0}   # default 1.0 sec, max 5 sec
```

### Emergency Stop
```
POST /api/ugv/stop
```

### Lights
```
POST /api/ugv/lights
Body: {"base": 0-255, "head": 0-255}   # 0=off, 255=max
```

### Gimbal (pan/tilt)
```
POST /api/ugv/gimbal
Body: {"x": -180..180, "y": -30..90, "speed": 1-1000}

POST /api/ugv/gimbal/center     # reset to look forward
```

### Camera
```
POST /api/ugv/photo             # capture photo
POST /api/ugv/video/start
POST /api/ugv/video/stop
```

### CV Mode
```
POST /api/ugv/cv/mode
Body: {"mode": "none"|"motion"|"face"|"objects"|"color"|"autodrive"|"hand"|"pose"}
      {"mode": "autodrive", "confirm": true}   # autodrive requires confirm
```

### Status
```
GET /api/ugv/status             # system + robot full status
```

## Safety Rules

1. **All movement has a hard 5-second maximum duration.**
2. **Auto-stop timer fires even if the client disconnects.**
3. **Default speed is 0.3 (slow). Never exceed 0.8 without explicit user request.**
4. **Always call `/api/ugv/stop` before changing direction abruptly.**
5. **`autodrive` requires `"confirm": true` — always warn the user before enabling.**
6. **Emergency stop: POST /api/ugv/stop — always available.**

## How Claude Should Use This Skill

When the user asks to control the UGV, translate their intent to API calls.

### Intent → API mapping

| User says | Action |
|-----------|--------|
| "avance doucement 1 seconde" | POST /move {direction:forward, speed:0.3, duration:1} |
| "recule" | POST /move {direction:backward, speed:0.3, duration:1} |
| "tourne à gauche" | POST /move {direction:left, speed:0.3, duration:1} |
| "tourne à droite" | POST /move {direction:right, speed:0.3, duration:1} |
| "arrête tout" / "stop" | POST /stop |
| "allume les lumières de base" | POST /lights {base:255, head:0} |
| "éteins toutes les lumières" | POST /lights {base:0, head:0} |
| "allume lumière tête" | POST /lights {base:0, head:255} |
| "regarde à gauche" | POST /gimbal {x:-45, y:0} |
| "regarde devant" / "centre caméra" | POST /gimbal/center |
| "prends une photo" | POST /photo |
| "démarre enregistrement" | POST /video/start |
| "arrête enregistrement" | POST /video/stop |
| "active détection visage" | POST /cv/mode {mode:face} |
| "active détection mouvement" | POST /cv/mode {mode:motion} |
| "désactive la CV" | POST /cv/mode {mode:none} |
| "donne-moi le statut" | GET /status |

## Executing Commands

### Option 1 — From the Raspberry Pi via SSH or local shell

```bash
# Status
python ugv_client.py status

# Move
python ugv_client.py move forward --speed 0.3 --duration 1.5
python ugv_client.py move backward --speed 0.3 --duration 1
python ugv_client.py move left --speed 0.3 --duration 0.5
python ugv_client.py stop

# Lights
python ugv_client.py lights --base 255 --head 0
python ugv_client.py lights --base 0 --head 0

# Gimbal
python ugv_client.py gimbal --x -45 --y 10
python ugv_client.py gimbal center

# Photo / Video
python ugv_client.py photo
python ugv_client.py video start
python ugv_client.py video stop

# CV Mode
python ugv_client.py cv face
python ugv_client.py cv motion
python ugv_client.py cv none
python ugv_client.py cv autodrive --confirm
```

### Option 2 — From another machine (specify host)

```bash
python ugv_client.py --host http://192.168.1.42:5000 status
python ugv_client.py --host http://192.168.1.42:5000 move forward --speed 0.3 --duration 1
```

### Option 3 — Direct curl (from any machine)

```bash
curl -X POST http://<pi-ip>:5000/api/ugv/stop
curl -X POST http://<pi-ip>:5000/api/ugv/move \
     -H "Content-Type: application/json" \
     -d '{"direction":"forward","speed":0.3,"duration":1.0}'
curl http://<pi-ip>:5000/api/ugv/status
```

## Verification Checklist Before Movement Commands

1. Check Flask is running: `curl http://<pi-ip>:5000/api/ugv/status`
2. Ensure the robot has clear space in the intended direction
3. Confirm speed ≤ 0.5 for indoor use
4. Keep duration ≤ 2 seconds for first tests

## Error Handling

- If `/api/ugv/status` returns error → Flask is not running, advise user to start it
- If move returns error → check direction spelling, speed/duration bounds
- If cv/mode autodrive returns 400 → must include `"confirm": true`
- Always suggest running `stop` if unsure of robot state
