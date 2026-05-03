# Connecting Claude to the UGV MCP Server

## Option 1 — Claude Code (via .mcp.json)

Create `.mcp.json` at the project root (NOT in `.claude/settings.json`):

```json
{
  "mcpServers": {
    "ugv-robot": {
      "type": "sse",
      "url": "http://<PI_IP>:5001/sse"
    }
  }
}
```

Requires `mcp` Python package on the Pi:
```bash
pip install mcp
```

## Option 2 — REST fallback (always available, no extra package)

Use `POST /mcp/rpc` on port 5000:

```bash
# List available tools
curl http://<PI_IP>:5000/mcp/tools

# Call a tool
curl -X POST http://<PI_IP>:5000/mcp/rpc \
  -H "Content-Type: application/json" \
  -d '{"tool": "get_robot_status", "params": {}}'

curl -X POST http://<PI_IP>:5000/mcp/rpc \
  -d '{"tool": "move_robot", "params": {"direction":"forward","speed":0.3,"duration":1}}'
```

## Available MCP tools

| Tool | Description |
|------|-------------|
| `get_robot_status` | Full status: battery, CPU, gimbal, CV mode |
| `move_robot` | Move with direction/speed/duration |
| `stop_robot` | Emergency stop |
| `set_lights` | base/head light 0-255 |
| `set_gimbal` | Pan/tilt x/y |
| `center_gimbal` | Look forward |
| `capture_photo` | Take photo |
| `start_recording` | Start video |
| `stop_recording` | Stop video |
| `set_cv_mode` | none/motion/face/objects/color/hand/pose |
| `start_routine` | patrol/watch/search/sentinel/follow |
| `stop_routine` | Stop current routine |
| `get_routine_status` | Routine state |
| `get_events` | Last N events |
| `get_zerotier_status` | ZT node/networks |
