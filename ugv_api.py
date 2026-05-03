"""
UGV REST API - Safe control layer over existing Flask app.
Registers as a Blueprint on /api/ugv/* routes.
All movement commands have mandatory auto-stop after duration.
Routine endpoints delegate to ugv_routines for high-level missions.
"""

import threading
import ugv_routines
from flask import Blueprint, jsonify, request

ugv_api = Blueprint('ugv_api', __name__)

_base = None
_cvf = None
_si = None
_f = None

MAX_DURATION = 5.0
MAX_SPEED = 0.8
DEFAULT_SPEED = 0.3

_move_timer = None
_move_lock = threading.Lock()


def init_api(base, cvf, si, config, project_path=""):
    global _base, _cvf, _si, _f
    _base = base
    _cvf = cvf
    _si = si
    _f = config
    ugv_routines.init_routines(base, cvf, si, config, project_path)


def _stop():
    if _base:
        _base.base_speed_ctrl(0, 0)


def _cancel_move_timer():
    global _move_timer
    if _move_timer and _move_timer.is_alive():
        _move_timer.cancel()


def _safe_move(left, right, duration):
    global _move_timer
    with _move_lock:
        _cancel_move_timer()
        _base.base_speed_ctrl(left, right)
        _move_timer = threading.Timer(duration, _stop)
        _move_timer.daemon = True
        _move_timer.start()


DIRECTION_MAP = {
    'forward':  lambda s: (s, s),
    'backward': lambda s: (-s, -s),
    'left':     lambda s: (-s, s),
    'right':    lambda s: (s, -s),
    'spin_left':  lambda s: (-s, s),
    'spin_right': lambda s: (s, -s),
}

CV_MODE_MAP = {
    'none':      'cv_none',
    'motion':    'cv_moti',
    'face':      'cv_face',
    'objects':   'cv_objs',
    'color':     'cv_clor',
    'autodrive': 'cv_auto',
    'hand':      'mp_hand',
    'mp_face':   'mp_face',
    'pose':      'mp_pose',
}


@ugv_api.route('/api/ugv/move', methods=['POST'])
def api_move():
    """Move robot. Body: {direction, speed (0-0.8), duration (0.1-5.0)}"""
    data = request.get_json() or {}
    direction = data.get('direction', 'forward').lower()
    speed = float(data.get('speed', DEFAULT_SPEED))
    duration = float(data.get('duration', 1.0))

    speed = max(0.0, min(MAX_SPEED, speed))
    duration = max(0.1, min(MAX_DURATION, duration))

    if direction not in DIRECTION_MAP:
        return jsonify({'status': 'error',
                        'message': f'Unknown direction: {direction}. Valid: {list(DIRECTION_MAP.keys())}'}), 400

    left, right = DIRECTION_MAP[direction](speed)
    _safe_move(left, right, duration)
    return jsonify({'status': 'ok', 'direction': direction, 'speed': speed, 'duration': duration})


@ugv_api.route('/api/ugv/stop', methods=['POST'])
def api_stop():
    """Emergency stop: cancels timer, stops motors, stops any running routine."""
    _cancel_move_timer()
    ugv_routines.emergency_stop()
    return jsonify({'status': 'ok', 'message': 'Emergency stop sent'})


@ugv_api.route('/api/ugv/lights', methods=['POST'])
def api_lights():
    """Control lights. Body: {base: 0-255, head: 0-255}"""
    data = request.get_json() or {}
    base_light = max(0, min(255, int(data.get('base', 0))))
    head_light = max(0, min(255, int(data.get('head', 0))))
    _base.lights_ctrl(base_light, head_light)
    return jsonify({'status': 'ok', 'base': base_light, 'head': head_light})


@ugv_api.route('/api/ugv/gimbal', methods=['POST'])
def api_gimbal():
    """Pan/tilt gimbal. Body: {x: -180..180, y: -30..90, speed: 1-1000}"""
    data = request.get_json() or {}
    x = max(-180.0, min(180.0, float(data.get('x', 0))))
    y = max(-30.0, min(90.0, float(data.get('y', 0))))
    speed = max(1, min(1000, int(data.get('speed', 200))))
    _base.gimbal_ctrl(x, y, speed, 10)
    _cvf.pan_angle = x
    _cvf.tilt_angle = y
    return jsonify({'status': 'ok', 'x': x, 'y': y, 'speed': speed})


@ugv_api.route('/api/ugv/gimbal/center', methods=['POST'])
def api_gimbal_center():
    """Reset gimbal to center (look forward)."""
    _base.gimbal_ctrl(0, 0, 200, 10)
    _cvf.pan_angle = 0
    _cvf.tilt_angle = 0
    return jsonify({'status': 'ok', 'message': 'Gimbal centered'})


@ugv_api.route('/api/ugv/photo', methods=['POST'])
def api_photo():
    """Capture a photo."""
    _cvf.picture_capture()
    return jsonify({'status': 'ok', 'message': 'Photo capture triggered'})


@ugv_api.route('/api/ugv/video/start', methods=['POST'])
def api_video_start():
    """Start video recording."""
    _cvf.video_record(True)
    return jsonify({'status': 'ok', 'message': 'Recording started'})


@ugv_api.route('/api/ugv/video/stop', methods=['POST'])
def api_video_stop():
    """Stop video recording."""
    _cvf.video_record(False)
    return jsonify({'status': 'ok', 'message': 'Recording stopped'})


@ugv_api.route('/api/ugv/cv/mode', methods=['POST'])
def api_cv_mode():
    """Set CV detection mode. Body: {mode: none|motion|face|objects|color|autodrive, confirm: bool}"""
    data = request.get_json() or {}
    mode = data.get('mode', 'none').lower()

    if mode == 'autodrive' and not data.get('confirm', False):
        return jsonify({'status': 'requires_confirm',
                        'message': 'autodrive requires confirm=true in body (dangerous mode)'}), 400

    if mode not in CV_MODE_MAP:
        return jsonify({'status': 'error',
                        'message': f'Unknown mode: {mode}. Valid: {list(CV_MODE_MAP.keys())}'}), 400

    _cvf.set_cv_mode(_f['code'][CV_MODE_MAP[mode]])
    return jsonify({'status': 'ok', 'mode': mode})


# ── Routine endpoints ─────────────────────────────────────────────────────────

@ugv_api.route('/api/ugv/routine/patrol', methods=['POST'])
def api_routine_patrol():
    """
    Start patrol mission.
    Body: {duration (s), speed (0.1-0.5), scan_mode, lights, record}
    """
    d = request.get_json() or {}
    ok, msg = ugv_routines.patrol(
        duration   = float(d.get('duration',   120.0)),
        speed      = float(d.get('speed',      ugv_routines.PATROL_SPEED_DEFAULT)),
        scan_mode  = d.get('scan_mode', 'motion'),
        lights     = bool(d.get('lights',  False)),
        record     = bool(d.get('record',  False)),
    )
    code = 200 if ok else 409
    return jsonify({'status': 'ok' if ok else 'error', 'message': msg}), code


@ugv_api.route('/api/ugv/routine/guard', methods=['POST'])
def api_routine_guard():
    """
    Start guard mission (robot stays still, scans periodically).
    Body: {scan_interval (s), cv_mode, record_on_detection, photo_on_detection, max_duration}
    """
    d = request.get_json() or {}
    if not d.get('confirm', False):
        return jsonify({'status': 'requires_confirm',
                        'message': 'guard mode requires confirm=true (long-running autonomous mode)'}), 400
    ok, msg = ugv_routines.guard(
        scan_interval       = float(d.get('scan_interval', 30.0)),
        cv_mode             = d.get('cv_mode', 'motion'),
        record_on_detection = bool(d.get('record_on_detection', False)),
        photo_on_detection  = bool(d.get('photo_on_detection', True)),
        max_duration        = float(d.get('max_duration', ugv_routines.GUARD_MAX_DURATION)),
    )
    code = 200 if ok else 409
    return jsonify({'status': 'ok' if ok else 'error', 'message': msg}), code


@ugv_api.route('/api/ugv/routine/watch', methods=['POST'])
def api_routine_watch():
    """
    Watch mode: immobile, CV active, optional periodic scan.
    Body: {cv_mode, scan_gimbal (bool), scan_interval (s)}
    """
    d = request.get_json() or {}
    ok, msg = ugv_routines.watch(
        cv_mode       = d.get('cv_mode', 'motion'),
        scan_gimbal   = bool(d.get('scan_gimbal', True)),
        scan_interval = float(d.get('scan_interval', 20.0)),
    )
    code = 200 if ok else 409
    return jsonify({'status': 'ok' if ok else 'error', 'message': msg}), code


@ugv_api.route('/api/ugv/routine/search', methods=['POST'])
def api_routine_search():
    """
    Full gimbal sweep searching for a target (base does not move).
    Body: {target: motion|face|objects|color|person|..., take_photo (bool)}
    """
    d = request.get_json() or {}
    ok, msg = ugv_routines.search(
        target     = d.get('target', 'motion'),
        take_photo = bool(d.get('take_photo', True)),
    )
    code = 200 if ok else 409
    return jsonify({'status': 'ok' if ok else 'error', 'message': msg}), code


@ugv_api.route('/api/ugv/routine/sentinel', methods=['POST'])
def api_routine_sentinel():
    """
    Sentinel: reactive guard with auto-recording on detection.
    Body: {cv_mode, scan_interval (s), record_on_detect, max_duration, confirm}
    """
    d = request.get_json() or {}
    if not d.get('confirm', False):
        return jsonify({'status': 'requires_confirm',
                        'message': 'sentinel requires confirm=true (autonomous reactive mode)'}), 400
    ok, msg = ugv_routines.sentinel(
        cv_mode          = d.get('cv_mode', 'motion'),
        scan_interval    = float(d.get('scan_interval', 10.0)),
        record_on_detect = bool(d.get('record_on_detect', True)),
        max_duration     = float(d.get('max_duration', ugv_routines.GUARD_MAX_DURATION)),
    )
    return jsonify({'status': 'ok' if ok else 'error', 'message': msg}), 200 if ok else 409


@ugv_api.route('/api/ugv/routine/follow', methods=['POST'])
def api_routine_follow():
    """
    Follow mode: track a person/face with gimbal + optional base rotation.
    Body: {cv_mode, max_duration (s, max 600), base_follow (bool), confirm}
    """
    d = request.get_json() or {}
    if not d.get('confirm', False):
        return jsonify({'status': 'requires_confirm',
                        'message': 'follow requires confirm=true (robot will move)'}), 400
    ok, msg = ugv_routines.follow(
        cv_mode      = d.get('cv_mode', 'mp_pose'),
        max_duration = float(d.get('max_duration', ugv_routines.FOLLOW_MAX_DUR)),
        base_follow  = bool(d.get('base_follow', True)),
    )
    return jsonify({'status': 'ok' if ok else 'error', 'message': msg}), 200 if ok else 409


@ugv_api.route('/api/ugv/routine/stop', methods=['POST'])
def api_routine_stop():
    """Request clean stop of the running routine."""
    ugv_routines.stop_routine()
    return jsonify({'status': 'ok', 'message': 'Routine stop requested'})


@ugv_api.route('/api/ugv/routine/status', methods=['GET'])
def api_routine_status():
    """Return current routine state."""
    return jsonify(ugv_routines.get_status())


# ── CV events ─────────────────────────────────────────────────────────────────

@ugv_api.route('/api/ugv/cv/events', methods=['GET'])
def api_cv_events():
    """Return last N routine and CV events. Query param: ?limit=30"""
    limit = min(int(request.args.get('limit', 30)), 200)
    return jsonify({'events': ugv_routines.get_events(limit)})


# ── ROS2 integration (optional, graceful degradation) ─────────────────────────

@ugv_api.route('/api/ugv/ros2/status', methods=['GET'])
def api_ros2_status():
    """Return ROS2 availability, running nodes and topics."""
    return jsonify(ugv_routines.ros2_status())


@ugv_api.route('/api/ugv/ros2/command', methods=['POST'])
def api_ros2_command():
    """
    Send a ROS2 command.
    Body: {cmd_type: "topic_pub"|"service_call"|"nav_goal"|"raw", ...payload}
    nav_goal body: {x, y, yaw}  — requires Nav2 running
    topic_pub body: {topic, type, data, once}
    raw body: {cmd}  — arbitrary ros2 CLI command (must confirm=true)
    """
    d = request.get_json() or {}
    cmd_type = d.get('cmd_type', '')

    if cmd_type == 'raw' and not d.get('confirm', False):
        return jsonify({'ok': False,
                        'error': 'raw ros2 commands require confirm=true'}), 400

    result = ugv_routines.ros2_command(cmd_type, d)
    code   = 200 if result.get('ok') else 500
    return jsonify(result), code


# ── System status ─────────────────────────────────────────────────────────────

@ugv_api.route('/api/ugv/status', methods=['GET'])
def api_status():
    """Return full system and robot status."""
    try:
        voltage = _base.base_data.get('v', 0) if _base.base_data else 0
    except Exception:
        voltage = 0

    return jsonify({
        'status': 'ok',
        'system': {
            'cpu_load':  _si.cpu_load,
            'cpu_temp':  _si.cpu_temp,
            'ram_usage': _si.ram,
            'wifi_rssi': _si.wifi_rssi,
            'wifi_mode': _si.wifi_mode,
            'wlan_ip':   _si.wlan_ip,
            'eth0_ip':   _si.eth0_ip,
        },
        'robot': {
            'voltage':         voltage,
            'base_light':      _base.base_light_status,
            'head_light':      _base.head_light_status,
            'cv_mode':         _cvf.cv_mode,
            'pan_angle':       _cvf.pan_angle,
            'tilt_angle':      _cvf.tilt_angle,
            'video_recording': _cvf.video_record_status_flag,
            'video_fps':       _cvf.video_fps,
        }
    })
