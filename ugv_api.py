"""
UGV REST API - Safe control layer over existing Flask app.
Registers as a Blueprint on /api/ugv/* routes.
All movement commands have mandatory auto-stop after duration.
"""

import threading
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


def init_api(base, cvf, si, config):
    global _base, _cvf, _si, _f
    _base = base
    _cvf = cvf
    _si = si
    _f = config


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
    """Emergency stop. Cancels any pending timer and sends stop immediately."""
    _cancel_move_timer()
    _stop()
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
