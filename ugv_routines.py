"""
UGV Routine Engine - High-level mission management with safety constraints.
All routines run in daemon threads with a shared stop event.
Only one routine runs at a time. Safety is checked continuously.
"""

import threading
import time
import datetime
import subprocess
import shutil
import os

# ── State constants ──────────────────────────────────────────────────────────
IDLE    = "idle"
RUNNING = "running"
STOPPED = "stopped"

# ── Safety limits ────────────────────────────────────────────────────────────
PATROL_SPEED_DEFAULT = 0.25
PATROL_MAX_DURATION  = 600.0   # 10 min
GUARD_MAX_DURATION   = 7200.0  # 2 h
SCAN_GIMBAL_SPEED    = 80
MIN_VOLTAGE          = 10.2    # stop if battery below this
MAX_CPU_TEMP         = 82.0    # stop if Pi overheating

# Gimbal sweep patterns
SCAN_FULL   = [(-60, 0), (-30, 0), (0, 0), (30, 0), (60, 0), (0, 15), (0, -10)]
SCAN_NARROW = [(-30, 0), (0, 0), (30, 0)]
SCAN_SEARCH = [
    (-90, 0), (-60, 0), (-30, 0), (0, 0), (30, 0), (60, 0), (90, 0),
    (90, 20), (60, 20), (30, 20), (0, 20), (-30, 20), (-60, 20), (-90, 20),
    (0, -15),
]

# ── Shared state ─────────────────────────────────────────────────────────────
_base = None
_cvf  = None
_si   = None
_f    = None
_project_path = None

_routine_thread  = None
_stop_event      = threading.Event()
_routine_lock    = threading.Lock()
_current_routine = IDLE
_current_params  = {}

_events      = []
_events_lock = threading.Lock()
_MAX_EVENTS  = 200


# ── Init ─────────────────────────────────────────────────────────────────────

def init_routines(base, cvf, si, config, project_path):
    global _base, _cvf, _si, _f, _project_path
    _base = base
    _cvf  = cvf
    _si   = si
    _f    = config
    _project_path = project_path


# ── Event log ────────────────────────────────────────────────────────────────

def _log(event_type, details=None):
    entry = {
        "ts":      datetime.datetime.now().isoformat(timespec="seconds"),
        "type":    event_type,
        "details": details or {},
    }
    with _events_lock:
        _events.append(entry)
        if len(_events) > _MAX_EVENTS:
            _events.pop(0)


def get_events(limit=30):
    with _events_lock:
        return list(_events[-limit:])


# ── Status ───────────────────────────────────────────────────────────────────

def get_status():
    alive = bool(_routine_thread and _routine_thread.is_alive())
    return {
        "state":         _current_routine,
        "running":       alive,
        "stop_requested": _stop_event.is_set(),
        "params":        _current_params,
    }


# ── Safety checks ────────────────────────────────────────────────────────────

def _safety_ok():
    """Returns (ok: bool, reason: str)."""
    try:
        voltage = _base.base_data.get("v", 0) if _base.base_data else 0
        if 0 < voltage < MIN_VOLTAGE:
            return False, f"low_battery ({voltage:.1f}V)"
    except Exception:
        pass
    try:
        if _si.cpu_temp and _si.cpu_temp > MAX_CPU_TEMP:
            return False, f"overheating ({_si.cpu_temp}°C)"
    except Exception:
        pass
    if _stop_event.is_set():
        return False, "stop_requested"
    return True, "ok"


# ── Primitive helpers ────────────────────────────────────────────────────────

def _motors_stop():
    _base.base_speed_ctrl(0, 0)


def _gimbal_center():
    _base.gimbal_ctrl(0, 0, 200, 10)
    _cvf.pan_angle  = 0
    _cvf.tilt_angle = 0


def _gimbal_sweep(angles, pause=0.55):
    """Step through gimbal angles; return early if stop requested."""
    for x, y in angles:
        if _stop_event.is_set():
            break
        _base.gimbal_ctrl(x, y, SCAN_GIMBAL_SPEED, 5)
        _cvf.pan_angle  = x
        _cvf.tilt_angle = y
        time.sleep(pause)
    _gimbal_center()


def _cv_set(mode_key):
    _cvf.set_cv_mode(_f["code"][mode_key])


def _cv_none():
    _cvf.set_cv_mode(_f["code"]["cv_none"])


def _take_photo():
    _cvf.picture_capture()
    _log("photo_taken")


def _sleep_interruptible(seconds, step=0.2):
    """Sleep in small chunks so stop_event is checked frequently."""
    elapsed = 0.0
    while elapsed < seconds and not _stop_event.is_set():
        time.sleep(step)
        elapsed += step


# ── Routine launcher ─────────────────────────────────────────────────────────

def _set_state(state, params=None):
    global _current_routine, _current_params
    _current_routine = state
    _current_params  = params or {}


def start_routine(fn, params, *args):
    """
    Launch a routine background thread.
    Returns (ok, message).
    Only one routine at a time.
    """
    global _routine_thread
    with _routine_lock:
        if _routine_thread and _routine_thread.is_alive():
            return False, "A routine is already running — send POST /api/ugv/routine/stop first"
        _stop_event.clear()
        _set_state(RUNNING, params)
        _routine_thread = threading.Thread(target=fn, args=args, daemon=True)
        _routine_thread.start()
    return True, "started"


def stop_routine():
    """Request clean stop of running routine."""
    _stop_event.set()
    _motors_stop()
    _log("routine_stop_requested")


def emergency_stop():
    """Hard stop — motors, CV, gimbal, recording."""
    _stop_event.set()
    _motors_stop()
    _cv_none()
    _gimbal_center()
    try:
        _cvf.video_record(False)
    except Exception:
        pass
    _log("emergency_stop")


# ── CV mode key resolver ─────────────────────────────────────────────────────

CV_MODE_MAP = {
    "motion":   "cv_moti",
    "face":     "cv_face",
    "objects":  "cv_objs",
    "color":    "cv_clor",
    "autodrive":"cv_auto",
    "hand":     "mp_hand",
    "mp_face":  "mp_face",
    "pose":     "mp_pose",
    "none":     "cv_none",
    "person":   "mp_pose",
    "human":    "mp_pose",
}

def _resolve_cv(mode_name):
    return CV_MODE_MAP.get(mode_name.lower(), "cv_moti")


# ── PATROL ───────────────────────────────────────────────────────────────────

def patrol(duration=120.0, speed=PATROL_SPEED_DEFAULT,
           scan_mode="motion", lights=False, record=False):
    """
    Robot patrols forward in segments with camera scans between moves.
    duration  : total patrol time in seconds (max PATROL_MAX_DURATION)
    speed     : drive speed 0.1-0.5
    scan_mode : cv mode name during patrol
    lights    : turn on base+head lights
    record    : start video recording
    """
    duration = min(float(duration), PATROL_MAX_DURATION)
    speed    = max(0.1, min(0.5, float(speed)))
    params   = dict(duration=duration, speed=speed, scan_mode=scan_mode,
                    lights=lights, record=record)
    ok, msg  = start_routine(_patrol_thread, params, duration, speed,
                              scan_mode, lights, record)
    return ok, msg


def _patrol_thread(duration, speed, scan_mode, lights, record):
    _log("patrol_start", dict(duration=duration, speed=speed, scan_mode=scan_mode))
    try:
        ok, reason = _safety_ok()
        if not ok:
            _log("patrol_abort", {"reason": reason})
            return

        if lights:
            _base.lights_ctrl(255, 255)
        _cv_set(_resolve_cv(scan_mode))
        if record:
            _cvf.video_record(True)

        start    = time.time()
        segment  = 0

        while not _stop_event.is_set():
            elapsed = time.time() - start
            if elapsed >= duration:
                break

            ok, reason = _safety_ok()
            if not ok:
                _log("patrol_abort_mid", {"reason": reason, "elapsed": round(elapsed, 1)})
                break

            # ── drive segment ──
            _base.base_speed_ctrl(speed, speed)
            _sleep_interruptible(1.5)
            _motors_stop()

            if _stop_event.is_set():
                break

            _sleep_interruptible(0.4)

            # ── camera scan ──
            _gimbal_sweep(SCAN_FULL, pause=0.45)
            segment += 1
            _log("patrol_segment", {"n": segment, "elapsed": round(time.time() - start, 1)})

            _sleep_interruptible(1.2)

    except Exception as e:
        _log("patrol_error", {"error": str(e)})
    finally:
        _motors_stop()
        if record:
            _cvf.video_record(False)
        _gimbal_center()
        _cv_none()
        if lights:
            _base.lights_ctrl(0, 0)
        _set_state(IDLE)
        _log("patrol_end")


# ── GUARD ────────────────────────────────────────────────────────────────────

def guard(scan_interval=30.0, cv_mode="motion", record_on_detection=False,
          max_duration=GUARD_MAX_DURATION, photo_on_detection=True):
    """
    Robot stays immobile, head-light on auto, scans gimbal every scan_interval s.
    Detects via CV mode; logs events.
    """
    max_duration  = min(float(max_duration), GUARD_MAX_DURATION)
    scan_interval = max(5.0, float(scan_interval))
    params = dict(cv_mode=cv_mode, scan_interval=scan_interval,
                  record_on_detection=record_on_detection,
                  photo_on_detection=photo_on_detection,
                  max_duration=max_duration)
    return start_routine(_guard_thread, params, scan_interval, cv_mode,
                         record_on_detection, photo_on_detection, max_duration)


def _guard_thread(scan_interval, cv_mode, record_on_detection,
                  photo_on_detection, max_duration):
    _log("guard_start", dict(cv_mode=cv_mode, scan_interval=scan_interval))
    try:
        ok, reason = _safety_ok()
        if not ok:
            _log("guard_abort", {"reason": reason})
            return

        _motors_stop()
        _gimbal_center()
        _cvf.head_light_ctrl(1)   # auto head light
        _cv_set(_resolve_cv(cv_mode))

        start     = time.time()
        last_scan = time.time()

        while not _stop_event.is_set():
            if time.time() - start >= max_duration:
                break

            ok, reason = _safety_ok()
            if not ok:
                _log("guard_abort_mid", {"reason": reason})
                break

            # Periodic gimbal sweep
            if time.time() - last_scan >= scan_interval:
                _log("guard_scan")
                _gimbal_sweep(SCAN_FULL, pause=0.6)
                last_scan = time.time()

            _sleep_interruptible(1.0)

    except Exception as e:
        _log("guard_error", {"error": str(e)})
    finally:
        _motors_stop()
        _cv_none()
        _cvf.head_light_ctrl(0)
        _gimbal_center()
        _set_state(IDLE)
        _log("guard_end")


# ── WATCH ────────────────────────────────────────────────────────────────────

def watch(cv_mode="motion", scan_gimbal=True, scan_interval=20.0):
    """
    Robot stays still, activates CV detection, optionally sweeps gimbal.
    """
    scan_interval = max(5.0, float(scan_interval))
    params = dict(cv_mode=cv_mode, scan_gimbal=scan_gimbal,
                  scan_interval=scan_interval)
    return start_routine(_watch_thread, params, cv_mode, scan_gimbal, scan_interval)


def _watch_thread(cv_mode, scan_gimbal, scan_interval):
    _log("watch_start", dict(cv_mode=cv_mode, scan_gimbal=scan_gimbal))
    try:
        ok, reason = _safety_ok()
        if not ok:
            _log("watch_abort", {"reason": reason})
            return

        _motors_stop()
        _gimbal_center()
        _cv_set(_resolve_cv(cv_mode))

        last_scan = time.time()

        while not _stop_event.is_set():
            ok, reason = _safety_ok()
            if not ok:
                _log("watch_abort_mid", {"reason": reason})
                break

            if scan_gimbal and time.time() - last_scan >= scan_interval:
                _log("watch_scan")
                _gimbal_sweep(SCAN_NARROW, pause=0.5)
                last_scan = time.time()

            _sleep_interruptible(1.0)

    except Exception as e:
        _log("watch_error", {"error": str(e)})
    finally:
        _motors_stop()
        _cv_none()
        _gimbal_center()
        _set_state(IDLE)
        _log("watch_end")


# ── SEARCH ───────────────────────────────────────────────────────────────────

def search(target="motion", take_photo=True):
    """
    Robot does a full 3D gimbal sweep looking for a target.
    Does NOT move the base.  Returns once sweep is complete.
    """
    params = dict(target=target, take_photo=take_photo)
    return start_routine(_search_thread, params, target, take_photo)


def _search_thread(target, take_photo):
    _log("search_start", dict(target=target))
    try:
        ok, reason = _safety_ok()
        if not ok:
            _log("search_abort", {"reason": reason})
            return

        _motors_stop()
        _cv_set(_resolve_cv(target))
        _log("search_sweep_start")
        _gimbal_sweep(SCAN_SEARCH, pause=0.7)

        if take_photo and not _stop_event.is_set():
            _take_photo()

    except Exception as e:
        _log("search_error", {"error": str(e)})
    finally:
        _motors_stop()
        _cv_none()
        _gimbal_center()
        _set_state(IDLE)
        _log("search_end")


# ── ROS2 integration (optional, graceful degradation) ───────────────────────

_ROS2_AVAILABLE = None   # None = not yet checked

_ROS2_SETUP = (
    "source /opt/ros/humble/setup.bash 2>/dev/null || "
    "source /opt/ros/jazzy/setup.bash 2>/dev/null; "
    "source /home/ws/ugv_ws/install/setup.bash 2>/dev/null"
)


def _check_ros2():
    global _ROS2_AVAILABLE
    if _ROS2_AVAILABLE is not None:
        return _ROS2_AVAILABLE
    has_ros2 = bool(shutil.which("ros2"))
    if not has_ros2:
        result = subprocess.run(
            "bash -c 'source /opt/ros/humble/setup.bash 2>/dev/null && ros2 --version'",
            shell=True, capture_output=True, timeout=4
        )
        has_ros2 = result.returncode == 0
    _ROS2_AVAILABLE = has_ros2
    _log("ros2_check", {"available": has_ros2})
    return has_ros2


def ros2_status():
    available = _check_ros2()
    if not available:
        return {"available": False, "nodes": [], "topics": []}
    try:
        nodes_r = subprocess.run(
            f"bash -c '{_ROS2_SETUP} && ros2 node list 2>/dev/null'",
            shell=True, capture_output=True, text=True, timeout=6
        )
        topics_r = subprocess.run(
            f"bash -c '{_ROS2_SETUP} && ros2 topic list 2>/dev/null'",
            shell=True, capture_output=True, text=True, timeout=6
        )
        nodes  = [n for n in nodes_r.stdout.strip().splitlines() if n]
        topics = [t for t in topics_r.stdout.strip().splitlines() if t]
        return {"available": True, "nodes": nodes, "topics": topics}
    except Exception as e:
        return {"available": True, "nodes": [], "topics": [], "error": str(e)}


# ── SENTINEL ─────────────────────────────────────────────────────────────────

def sentinel(scan_interval=10.0, max_duration=GUARD_MAX_DURATION,
             record_on_detect=True, cv_mode="motion"):
    """
    Enhanced reactive guard: motion/person detection with auto-recording,
    aggressive gimbal scans, and event logging on detection.
    confirm=True required from API layer.
    """
    max_duration  = min(float(max_duration), GUARD_MAX_DURATION)
    scan_interval = max(5.0, float(scan_interval))
    params = dict(cv_mode=cv_mode, scan_interval=scan_interval,
                  record_on_detect=record_on_detect, max_duration=max_duration)
    return start_routine(_sentinel_thread, params,
                         scan_interval, record_on_detect, cv_mode, max_duration)


def _sentinel_thread(scan_interval, record_on_detect, cv_mode, max_duration):
    _log("sentinel_start", dict(cv_mode=cv_mode, scan_interval=scan_interval,
                                record_on_detect=record_on_detect))
    try:
        ok, reason = _safety_ok()
        if not ok:
            _log("sentinel_abort", {"reason": reason})
            return

        _motors_stop()
        _gimbal_center()
        _cvf.head_light_ctrl(1)                              # auto head light
        _cv_set(_resolve_cv(cv_mode))
        _cvf.set_detection_reaction(
            _f["code"]["re_reco"] if record_on_detect else _f["code"]["re_capt"]
        )
        _cvf.set_movtion_lock(False)                         # allow gimbal to follow

        start     = time.time()
        last_scan = time.time()

        while not _stop_event.is_set():
            if time.time() - start >= max_duration:
                break

            ok, reason = _safety_ok()
            if not ok:
                _log("sentinel_abort_mid", {"reason": reason})
                break

            if time.time() - last_scan >= scan_interval:
                _log("sentinel_scan")
                _gimbal_sweep(SCAN_FULL, pause=0.45)
                last_scan = time.time()

            _sleep_interruptible(0.5)

    except Exception as e:
        _log("sentinel_error", {"error": str(e)})
    finally:
        _motors_stop()
        _cvf.set_detection_reaction(_f["code"]["re_none"])
        _cvf.set_movtion_lock(True)
        _cv_none()
        _cvf.head_light_ctrl(0)
        _gimbal_center()
        _set_state(IDLE)
        _log("sentinel_end")


# ── FOLLOW ────────────────────────────────────────────────────────────────────

FOLLOW_DEAD_ZONE = 15.0    # degrees — ignored pan error
FOLLOW_SPEED     = 0.18    # base speed for rotation correction
FOLLOW_MAX_DUR   = 300.0   # default 5 min


def follow(cv_mode="mp_pose", max_duration=FOLLOW_MAX_DUR, base_follow=True):
    """
    Follow mode: enables tracking CV, unlocks gimbal tracking.
    If base_follow=True: rotates robot base to keep pan_angle near 0.
    confirm=True required from API layer.
    """
    max_duration = min(float(max_duration), 600.0)
    params = dict(cv_mode=cv_mode, max_duration=max_duration, base_follow=base_follow)
    return start_routine(_follow_thread, params, cv_mode, max_duration, base_follow)


def _follow_thread(cv_mode, max_duration, base_follow):
    _log("follow_start", dict(cv_mode=cv_mode, base_follow=base_follow))
    try:
        ok, reason = _safety_ok()
        if not ok:
            _log("follow_abort", {"reason": reason})
            return

        _motors_stop()
        _gimbal_center()
        _cv_set(_resolve_cv(cv_mode))
        _cvf.set_movtion_lock(False)   # gimbal tracks target

        start = time.time()

        while not _stop_event.is_set():
            if time.time() - start >= max_duration:
                break

            ok, reason = _safety_ok()
            if not ok:
                _log("follow_abort_mid", {"reason": reason})
                break

            if base_follow:
                pan = _cvf.pan_angle
                if pan > FOLLOW_DEAD_ZONE:
                    _base.base_speed_ctrl(FOLLOW_SPEED, -FOLLOW_SPEED)
                    time.sleep(0.12)
                    _motors_stop()
                elif pan < -FOLLOW_DEAD_ZONE:
                    _base.base_speed_ctrl(-FOLLOW_SPEED, FOLLOW_SPEED)
                    time.sleep(0.12)
                    _motors_stop()

            _sleep_interruptible(0.25)

    except Exception as e:
        _log("follow_error", {"error": str(e)})
    finally:
        _motors_stop()
        _cvf.set_movtion_lock(True)
        _cv_none()
        _gimbal_center()
        _set_state(IDLE)
        _log("follow_end")


# ── ROS2 integration (optional, graceful degradation) ───────────────────────

def ros2_command(cmd_type, payload):
    """
    Execute a ROS2 command via subprocess.
    cmd_type: "topic_pub" | "service_call" | "action_send" | "nav_goal" | "raw"
    payload:  dict with command-specific fields
    Returns: {"ok": bool, "output": str, "error": str}
    """
    if not _check_ros2():
        return {"ok": False, "error": "ROS2 not available on this system"}

    try:
        if cmd_type == "topic_pub":
            # payload: {topic, type, data, once: bool}
            once = "--once" if payload.get("once", True) else ""
            raw  = f"ros2 topic pub {once} {payload['topic']} {payload['type']} '{payload['data']}'"

        elif cmd_type == "service_call":
            # payload: {service, type, data}
            raw = f"ros2 service call {payload['service']} {payload['type']} '{payload.get('data', '{}')}'"

        elif cmd_type == "nav_goal":
            # payload: {x, y, yaw}  — uses Nav2 simple API
            x, y = payload.get("x", 0), payload.get("y", 0)
            yaw  = payload.get("yaw", 0)
            qz   = round(__import__("math").sin(yaw / 2), 4)
            qw   = round(__import__("math").cos(yaw / 2), 4)
            goal_json = (
                f'{{"pose": {{"header": {{"frame_id": "map"}}, '
                f'"pose": {{"position": {{"x": {x}, "y": {y}, "z": 0.0}}, '
                f'"orientation": {{"z": {qz}, "w": {qw}}}}}}}}}'
            )
            raw = (
                f"ros2 action send_goal /navigate_to_pose "
                f"nav2_msgs/action/NavigateToPose '{goal_json}'"
            )

        elif cmd_type == "raw":
            raw = payload.get("cmd", "")
        else:
            return {"ok": False, "error": f"Unknown cmd_type: {cmd_type}"}

        full_cmd = f"bash -c '{_ROS2_SETUP} && {raw}'"
        r = subprocess.run(full_cmd, shell=True, capture_output=True,
                           text=True, timeout=15)
        ok = r.returncode == 0
        _log("ros2_cmd", {"type": cmd_type, "ok": ok})
        return {"ok": ok, "output": r.stdout.strip(), "error": r.stderr.strip()}

    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "ROS2 command timed out (15s)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}
