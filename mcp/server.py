"""
UGV MCP Server — exposes robot tools to Claude.

Two transport modes (auto-detected):
  1. FastMCP SSE  — if `mcp` package installed  →  port settings.mcp.port (default 5001)
                     Claude Code: add to .claude/settings.json mcpServers
  2. REST fallback — always available via Flask   →  POST /mcp/rpc

FastMCP tools implemented:
  get_robot_status, move_robot, stop_robot, set_lights, set_gimbal,
  center_gimbal, capture_photo, start_recording, stop_recording,
  set_cv_mode, start_routine, stop_routine, get_routine_status,
  get_events, get_zerotier_status

All tools call the Flask REST API (localhost:5000) — no direct hardware access.
"""

import threading
import requests
from ugv_logger import get_logger

log = get_logger("mcp")

# ── Flask API base (MCP server runs alongside Flask) ─────────────────────────
_FLASK = "http://localhost:5000"
_TIMEOUT = 5


def _get(path: str) -> dict:
    try:
        r = requests.get(_FLASK + path, timeout=_TIMEOUT)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def _post(path: str, body: dict = None) -> dict:
    try:
        r = requests.post(_FLASK + path, json=body or {}, timeout=_TIMEOUT)
        return r.json()
    except Exception as e:
        return {"error": str(e)}


# ── Tool implementations (shared by FastMCP + REST fallback) ─────────────────

def tool_get_robot_status() -> dict:
    """Full robot status: battery, CPU, temperature, gimbal angles, CV mode, lights."""
    return _get("/api/ugv/status")


def tool_move_robot(direction: str, speed: float = 0.3, duration: float = 1.0) -> dict:
    """
    Move robot. Auto-stops after `duration` seconds.
    direction: forward | backward | left | right | spin_left | spin_right
    speed: 0.0–0.8 (default 0.3, slow and safe)
    duration: 0.1–5.0 seconds (default 1.0)
    """
    return _post("/api/ugv/move", {"direction": direction, "speed": speed, "duration": duration})


def tool_stop_robot() -> dict:
    """Emergency stop — immediately stops motors and any running routine."""
    return _post("/api/ugv/stop")


def tool_set_lights(base: int = 0, head: int = 0) -> dict:
    """
    Control robot lights.
    base: 0–255 (base ring lights)
    head: 0–255 (head/camera lights)
    0 = off, 255 = max brightness
    """
    return _post("/api/ugv/lights", {"base": base, "head": head})


def tool_set_gimbal(x: float = 0.0, y: float = 0.0, speed: int = 200) -> dict:
    """
    Pan/tilt camera gimbal.
    x: -180 to 180 (pan, negative=left positive=right)
    y: -30 to 90  (tilt, negative=down positive=up)
    speed: 1–1000 (default 200)
    """
    return _post("/api/ugv/gimbal", {"x": x, "y": y, "speed": speed})


def tool_center_gimbal() -> dict:
    """Reset gimbal to center position — looks straight ahead."""
    return _post("/api/ugv/gimbal/center")


def tool_capture_photo() -> dict:
    """Capture a photo with the current camera view."""
    return _post("/api/ugv/photo")


def tool_start_recording() -> dict:
    """Start video recording."""
    return _post("/api/ugv/video/start")


def tool_stop_recording() -> dict:
    """Stop video recording."""
    return _post("/api/ugv/video/stop")


def tool_set_cv_mode(mode: str) -> dict:
    """
    Set computer vision detection mode.
    mode: none | motion | face | objects | color | hand | mp_face | pose
    Note: autodrive requires explicit confirmation — not available via MCP for safety.
    """
    if mode == "autodrive":
        return {"error": "autodrive disabled via MCP for safety — use the web UI"}
    return _post("/api/ugv/cv/mode", {"mode": mode})


def tool_start_routine(routine: str, params: dict = None) -> dict:
    """
    Start an autonomous routine.
    routine: patrol | watch | search | sentinel | follow | guard
    params: dict of routine-specific options (optional)
      patrol  → {duration:120, speed:0.25, scan_mode:'motion', lights:false}
      watch   → {cv_mode:'motion', scan_gimbal:true, scan_interval:20}
      search  → {target:'face', take_photo:true}
      sentinel→ {cv_mode:'motion', scan_interval:10, record_on_detect:true, confirm:true}
      follow  → {cv_mode:'mp_pose', base_follow:true, confirm:true}
    """
    body = dict(params or {})
    if routine in ("sentinel", "follow", "guard"):
        body["confirm"] = True
    return _post(f"/api/ugv/routine/{routine}", body)


def tool_stop_routine() -> dict:
    """Stop the currently running autonomous routine."""
    return _post("/api/ugv/routine/stop")


def tool_get_routine_status() -> dict:
    """Get current routine state (idle/running), name, and parameters."""
    return _get("/api/ugv/routine/status")


def tool_get_events(limit: int = 20) -> dict:
    """Get last N robot events (CV detections, routine changes, errors)."""
    return _get(f"/api/ugv/cv/events?limit={limit}")


def tool_get_zerotier_status() -> dict:
    """Get ZeroTier network status — node ID, version, joined networks."""
    return _get("/zt/status")


# ── Tool registry (for REST fallback) ────────────────────────────────────────

TOOLS = {
    "get_robot_status":   (tool_get_robot_status,   {}),
    "move_robot":         (tool_move_robot,          {"direction": "forward", "speed": 0.3, "duration": 1.0}),
    "stop_robot":         (tool_stop_robot,          {}),
    "set_lights":         (tool_set_lights,          {"base": 0, "head": 0}),
    "set_gimbal":         (tool_set_gimbal,          {"x": 0.0, "y": 0.0, "speed": 200}),
    "center_gimbal":      (tool_center_gimbal,       {}),
    "capture_photo":      (tool_capture_photo,       {}),
    "start_recording":    (tool_start_recording,     {}),
    "stop_recording":     (tool_stop_recording,      {}),
    "set_cv_mode":        (tool_set_cv_mode,         {"mode": "none"}),
    "start_routine":      (tool_start_routine,       {"routine": "watch"}),
    "stop_routine":       (tool_stop_routine,        {}),
    "get_routine_status": (tool_get_routine_status,  {}),
    "get_events":         (tool_get_events,          {"limit": 20}),
    "get_zerotier_status":(tool_get_zerotier_status, {}),
}


def list_tools_schema() -> list:
    return [
        {
            "name":        name,
            "description": fn.__doc__.strip().splitlines()[0] if fn.__doc__ else name,
            "defaults":    defaults,
        }
        for name, (fn, defaults) in TOOLS.items()
    ]


def call_tool(name: str, params: dict) -> dict:
    if name not in TOOLS:
        return {"error": f"Unknown tool: {name}. Available: {list(TOOLS)}"}
    fn, _ = TOOLS[name]
    try:
        return fn(**params) if params else fn()
    except TypeError as e:
        return {"error": f"Bad params: {e}"}
    except Exception as e:
        return {"error": str(e)}


# ── FastMCP server (optional) ─────────────────────────────────────────────────

_MCP_THREAD = None
MCP_AVAILABLE = False

try:
    from mcp.server.fastmcp import FastMCP
    MCP_AVAILABLE = True
    log.info("mcp package found — FastMCP SSE server available")
except ImportError:
    log.info("mcp package not installed — using REST fallback only (POST /mcp/rpc)")


def _build_fastmcp(flask_base: str):
    """Build FastMCP instance with all tools wired up."""
    global _FLASK
    _FLASK = flask_base

    server = FastMCP("UGV Waveshare Robot")

    @server.tool()
    def get_robot_status() -> dict:
        """Full robot status: battery, CPU, temperature, gimbal angles, CV mode."""
        return tool_get_robot_status()

    @server.tool()
    def move_robot(direction: str, speed: float = 0.3, duration: float = 1.0) -> dict:
        """Move robot. direction: forward/backward/left/right. speed: 0-0.8. duration: 0.1-5s."""
        return tool_move_robot(direction, speed, duration)

    @server.tool()
    def stop_robot() -> dict:
        """Emergency stop — stops motors and any running routine immediately."""
        return tool_stop_robot()

    @server.tool()
    def set_lights(base: int = 0, head: int = 0) -> dict:
        """Control lights. base/head: 0=off, 255=max."""
        return tool_set_lights(base, head)

    @server.tool()
    def set_gimbal(x: float = 0.0, y: float = 0.0, speed: int = 200) -> dict:
        """Pan/tilt gimbal. x: -180..180 (pan), y: -30..90 (tilt)."""
        return tool_set_gimbal(x, y, speed)

    @server.tool()
    def center_gimbal() -> dict:
        """Reset gimbal to center — looks straight ahead."""
        return tool_center_gimbal()

    @server.tool()
    def capture_photo() -> dict:
        """Capture a photo."""
        return tool_capture_photo()

    @server.tool()
    def start_recording() -> dict:
        """Start video recording."""
        return tool_start_recording()

    @server.tool()
    def stop_recording() -> dict:
        """Stop video recording."""
        return tool_stop_recording()

    @server.tool()
    def set_cv_mode(mode: str) -> dict:
        """Set CV mode: none|motion|face|objects|color|hand|mp_face|pose."""
        return tool_set_cv_mode(mode)

    @server.tool()
    def start_routine(routine: str, params: dict = None) -> dict:
        """Start autonomous routine: patrol|watch|search|sentinel|follow."""
        return tool_start_routine(routine, params)

    @server.tool()
    def stop_routine() -> dict:
        """Stop the running routine."""
        return tool_stop_routine()

    @server.tool()
    def get_routine_status() -> dict:
        """Current routine state."""
        return tool_get_routine_status()

    @server.tool()
    def get_events(limit: int = 20) -> dict:
        """Get last N robot events."""
        return tool_get_events(limit)

    @server.tool()
    def get_zerotier_status() -> dict:
        """ZeroTier network status."""
        return tool_get_zerotier_status()

    return server


def start_mcp_server(port: int = 5001, flask_base: str = "http://localhost:5000"):
    """Start FastMCP SSE server in a background daemon thread."""
    global _MCP_THREAD, _FLASK
    _FLASK = flask_base

    if not MCP_AVAILABLE:
        log.info("FastMCP not available — MCP REST endpoint at /mcp/rpc")
        return None

    if _MCP_THREAD and _MCP_THREAD.is_alive():
        log.warning("MCP server already running")
        return _MCP_THREAD

    def _run():
        try:
            srv = _build_fastmcp(flask_base)
            log.info("FastMCP SSE server starting on port %d", port)
            srv.run(transport="sse", host="0.0.0.0", port=port)
        except Exception as e:
            log.error("FastMCP server error: %s", e)

    _MCP_THREAD = threading.Thread(target=_run, name="mcp-sse", daemon=True)
    _MCP_THREAD.start()
    log.info("MCP thread started (port %d) — add to Claude Code via .claude/settings.json", port)
    return _MCP_THREAD
