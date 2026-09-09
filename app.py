# import base_ctrl library
from base_ctrl import BaseController
import threading
import yaml, os

# raspberry pi version check.
def is_raspberry_pi5():
    with open('/proc/cpuinfo', 'r') as file:
        for line in file:
            if 'Model' in line:
                if 'Raspberry Pi 5' in line:
                    return True
                else:
                    return False

if is_raspberry_pi5():
    base = BaseController('/dev/ttyAMA0', 115200)
else:
    base = BaseController('/dev/serial0', 115200)

threading.Thread(target=lambda: base.breath_light(15), daemon=True).start()

# config file.
curpath = os.path.realpath(__file__)
thisPath = os.path.dirname(curpath)
with open(thisPath + '/config.yaml', 'r') as yaml_file:
    f = yaml.safe_load(yaml_file)

base.base_oled(0, f["base_config"]["robot_name"])
base.base_oled(1, f"sbc_version: {f['base_config']['sbc_version']}")
base.base_oled(2, f"{f['base_config']['main_type']}{f['base_config']['module_type']}")
base.base_oled(3, "Starting...")


# Import necessary modules
from flask import Flask, render_template, Response, request, jsonify, redirect, url_for, send_from_directory, send_file
from flask_socketio import SocketIO, emit
from werkzeug.utils import secure_filename
from aiortc import RTCPeerConnection, RTCSessionDescription
import json
import uuid
import asyncio
import time
import logging
import math
import numpy as np
import cv_ctrl
import audio_ctrl
import os_info

# ─────────────────────────────────────────────────────────────────────────────
# LIDAR Obstacle Avoidance
# ─────────────────────────────────────────────────────────────────────────────
# Danger-zone thresholds (millimetres)
LIDAR_STOP_MM   = 250   # hard stop + reverse
LIDAR_TURN_MM   = 450   # steer away
LIDAR_SLOW_MM   = 700   # reduce speed

# Angular sector widths (degrees)
FRONT_HALF_DEG  = 45    # 90° forward cone
REAR_HALF_DEG   = 45    # 90° rear cone

# Motor speeds  (−1.0 … +1.0)
CRUISE_SPD      = 0.35
SLOW_SPD        = 0.20
REVERSE_SPD     = -0.25
MAX_TURN_BIAS   = 0.45

# Timing
REVERSE_SEC     = 0.6
TURN_SEC        = 0.9
MANUAL_PAUSE_SEC = 3.0  # seconds after last joystick input before avoider resumes
LOOP_HZ         = 10


def _sector_min(angles_rad, distances_mm, center_deg, half_deg, min_mm=50):
    """
    Minimum valid distance (mm) inside an angular sector. inf = no reading.
    The LD19 lidar stores angles with +180 deg baked in (parse_lidar_frame
    adds 180°).  We subtract π before comparing so 0 deg = forward.
    """
    lo = math.radians(center_deg - half_deg)
    hi = math.radians(center_deg + half_deg)
    best = float('inf')
    for a, d in zip(angles_rad, distances_mm):
        a = a - math.pi                        # correct +180° hardware offset
        a = math.atan2(math.sin(a), math.cos(a))  # normalise to [-π, π]
        if lo <= a <= hi and d >= min_mm and d < best:
            best = d
    return best


def _turn_bias(angles_rad, distances_mm, half_deg=FRONT_HALF_DEG,
               danger_mm=LIDAR_TURN_MM, min_mm=50):
    """
    Weighted turn direction in [-1, +1].
    +1 = turn LEFT (away from right-side obstacle).
    -1 = turn RIGHT (away from left-side obstacle).
    Applies the same -π correction as _sector_min.
    """
    left_w = right_w = 0.0
    lo = math.radians(-half_deg)
    hi = math.radians(half_deg)
    for a, d in zip(angles_rad, distances_mm):
        a = a - math.pi                        # correct +180° hardware offset
        a = math.atan2(math.sin(a), math.cos(a))
        if not (lo <= a <= hi):
            continue
        if d < min_mm or d > danger_mm:
            continue
        w = (danger_mm - d) / danger_mm
        if a < 0:
            right_w += w   # obstacle on right → push left
        else:
            left_w  += w   # obstacle on left  → push right
    total = left_w + right_w
    if total < 1e-6:
        return 0.0
    return float(np.clip((right_w - left_w) / total, -1.0, 1.0))


class LidarAvoider:
    """
    Background thread that reads LIDAR data from base.rl and issues
    differential-drive commands to avoid obstacles.

    States: IDLE → CRUISE → SLOW → EVADE → REVERSE
    """
    IDLE    = 'IDLE'
    CRUISE  = 'CRUISE'
    SLOW    = 'SLOW'
    EVADE   = 'EVADE'
    REVERSE = 'REVERSE'

    def __init__(self, base_ctrl):
        self._base      = base_ctrl
        self.state      = self.IDLE
        self._active    = False
        self._stop_evt  = threading.Event()
        self._thread    = None
        self._last_L    = 0.0
        self._last_R    = 0.0
        self._cooldown  = 0.0

    # ── public ───────────────────────────────────────────────────────────────

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_evt.clear()
        self._active = True
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="lidar-avoider")
        self._thread.start()
        logging.info("[LidarAvoider] started")

    def stop(self):
        self._stop_evt.set()
        self._send(0.0, 0.0)

    def pause(self):
        """Yield control to manual driver."""
        self._active = False
        self.state   = self.IDLE

    def resume(self):
        """Re-enable automatic avoidance."""
        self._active = True

    # ── internal loop ────────────────────────────────────────────────────────

    def _loop(self):
        interval = 1.0 / LOOP_HZ
        while not self._stop_evt.is_set():
            t0 = time.time()
            if self._active:
                try:
                    angles    = list(self._base.rl.lidar_angles_show)
                    distances = list(self._base.rl.lidar_distances_show)
                    if angles:
                        self._decide(angles, distances)
                    else:
                        self.state = self.IDLE
                except Exception as e:
                    logging.warning("[LidarAvoider] loop error: %s", e)
            else:
                self.state = self.IDLE
            time.sleep(max(0.0, interval - (time.time() - t0)))

    def _decide(self, angles, distances):
        now = time.time()

        front      = _sector_min(angles, distances,   0, FRONT_HALF_DEG)
        front_left = _sector_min(angles, distances,  30, 25)
        front_right= _sector_min(angles, distances, -30, 25)
        rear       = _sector_min(angles, distances, 180, REAR_HALF_DEG)

        # ── cooldown after a reverse/turn manoeuvre ───────────────────────
        if now < self._cooldown:
            return

        # ── DANGER STOP: reverse then spin ───────────────────────────────
        if front < LIDAR_STOP_MM:
            self.state = self.REVERSE
            bias = _turn_bias(angles, distances)
            if abs(bias) < 0.15:
                bias = 1.0 if front_left > front_right else -1.0
            self._reverse_and_turn(bias, rear)
            return

        # ── DANGER TURN: steer smoothly away ─────────────────────────────
        if front < LIDAR_TURN_MM:
            self.state = self.EVADE
            bias = _turn_bias(angles, distances)
            if abs(bias) < 0.1:
                bias = 1.0 if front_left > front_right else -1.0

            # Speed scales with remaining clearance (closer = slower)
            spd_f = np.clip(
                (front - LIDAR_STOP_MM) / (LIDAR_TURN_MM - LIDAR_STOP_MM),
                0.0, 1.0)
            fwd   = float(SLOW_SPD * spd_f)
            turn  = float(MAX_TURN_BIAS * abs(bias))

            if bias > 0:   # turn left
                L, R = fwd - turn, fwd + turn
            else:          # turn right
                L, R = fwd + turn, fwd - turn

            self._send(
                float(np.clip(L, -1.0, 1.0)),
                float(np.clip(R, -1.0, 1.0)))
            return

        # ── DANGER SLOW: reduce speed with gentle bias ────────────────────
        if front < LIDAR_SLOW_MM:
            self.state = self.SLOW
            spd_f = np.clip(
                (front - LIDAR_TURN_MM) / (LIDAR_SLOW_MM - LIDAR_TURN_MM),
                0.0, 1.0)
            fwd   = float(SLOW_SPD + (CRUISE_SPD - SLOW_SPD) * spd_f)
            bias  = _turn_bias(angles, distances)
            turn  = float(MAX_TURN_BIAS * 0.4 * abs(bias))

            if bias > 0:
                L, R = fwd - turn, fwd + turn
            else:
                L, R = fwd + turn, fwd - turn

            self._send(
                float(np.clip(L, 0.0, 1.0)),
                float(np.clip(R, 0.0, 1.0)))
            return

        # ── Clear path: cruise ────────────────────────────────────────────
        self.state = self.CRUISE
        self._send(CRUISE_SPD, CRUISE_SPD)

    def _reverse_and_turn(self, bias, rear):
        """Block the avoider loop: back up then spin away."""
        # Phase 1: reverse (skip if rear is blocked)
        rev = REVERSE_SPD if rear > LIDAR_STOP_MM else 0.0
        if rev != 0.0:
            self._send(rev, rev)
            time.sleep(REVERSE_SEC)

        # Phase 2: spin in place
        if bias > 0:   # turn left: right fwd, left back
            self._send( SLOW_SPD, -SLOW_SPD)
        else:          # turn right
            self._send(-SLOW_SPD,  SLOW_SPD)
        time.sleep(TURN_SEC)

        self._send(0.0, 0.0)
        self._cooldown = time.time() + 0.3

    def _send(self, L, R):
        """Send differential-drive command, skipping duplicates."""
        L = round(L, 3)
        R = round(R, 3)
        if L == self._last_L and R == self._last_R:
            return
        self._last_L = L
        self._last_R = R
        self._base.base_json_ctrl({"T": 1, "L": L, "R": R})


# ─────────────────────────────────────────────────────────────────────────────
# App setup
# ─────────────────────────────────────────────────────────────────────────────

# Get system info
UPLOAD_FOLDER = thisPath + '/sounds/others'
si = os_info.SystemInfo()

# Create Flask app
app = Flask(__name__)
socketio = SocketIO(app)

# Make server prints land in ugv.log immediately no matter how the process is
# launched (the cron autorun does not use python -u).  Without this, 'print'
# diagnostics such as the [drive] clamp line sit in a block buffer and shell
# greps for them come up empty during live debugging.
try:
    import os as _os
    if _os.environ.get('PYTHONUNBUFFERED') != '1':
        sys.stdout.reconfigure(line_buffering=True)
        sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

# RTCPeerConnection tracking
active_pcs = {}
MAX_CONNECTIONS = 1
pcs = set()

# Hard cap for WebRTC offer setup; past this the server returns a clear 503
# so the browser falls back to the MJPEG stream instead of waiting.
OFFER_TIMEOUT_SEC = 3.0

# Camera functions
cvf = cv_ctrl.OpencvFuncs(thisPath, base)

# LIDAR avoider (starts later in __main__ if use_lidar is true)
avoider = LidarAvoider(base)

# Motor clamp for externally submitted drive commands (T:1 / T:13).
MAX_DRIVE_SPEED = float(f['args_config']['max_speed'])

# Timestamp of last manual motion command (for watchdog)
_last_manual_cmd_time = 0.0

# ─────────────────────────────────────────────────────────────────────────────
# Command dispatch tables
# ─────────────────────────────────────────────────────────────────────────────

cmd_actions = {
    f['code']['zoom_x1']: lambda: cvf.scale_ctrl(1),
    f['code']['zoom_x2']: lambda: cvf.scale_ctrl(2),
    f['code']['zoom_x4']: lambda: cvf.scale_ctrl(4),

    f['code']['pic_cap']: cvf.picture_capture,
    f['code']['vid_sta']: lambda: cvf.video_record(True),
    f['code']['vid_end']: lambda: cvf.video_record(False),

    f['code']['cv_none']: lambda: cvf.set_cv_mode(f['code']['cv_none']),
    f['code']['cv_moti']: lambda: cvf.set_cv_mode(f['code']['cv_moti']),
    f['code']['cv_face']: lambda: cvf.set_cv_mode(f['code']['cv_face']),
    f['code']['cv_objs']: lambda: cvf.set_cv_mode(f['code']['cv_objs']),
    f['code']['cv_clor']: lambda: cvf.set_cv_mode(f['code']['cv_clor']),
    f['code']['mp_hand']: lambda: cvf.set_cv_mode(f['code']['mp_hand']),
    f['code']['cv_auto']: lambda: cvf.set_cv_mode(f['code']['cv_auto']),
    f['code']['mp_face']: lambda: cvf.set_cv_mode(f['code']['mp_face']),
    f['code']['mp_pose']: lambda: cvf.set_cv_mode(f['code']['mp_pose']),

    f['code']['re_none']: lambda: cvf.set_detection_reaction(f['code']['re_none']),
    f['code']['re_capt']: lambda: cvf.set_detection_reaction(f['code']['re_capt']),
    f['code']['re_reco']: lambda: cvf.set_detection_reaction(f['code']['re_reco']),

    f['code']['mc_lock']: lambda: cvf.set_movtion_lock(True),
    f['code']['mc_unlo']: lambda: cvf.set_movtion_lock(False),

    f['code']['led_off']: lambda: cvf.head_light_ctrl(0),
    f['code']['led_aut']: lambda: cvf.head_light_ctrl(1),
    f['code']['led_ton']: lambda: cvf.head_light_ctrl(2),

    f['code']['release']: lambda: base.bus_servo_torque_lock(255, 0),
    f['code']['s_panid']: lambda: base.bus_servo_id_set(255, 2),
    f['code']['s_tilid']: lambda: base.bus_servo_id_set(255, 1),
    f['code']['set_mid']: lambda: base.bus_servo_mid_set(255),

    f['code']['base_of']: lambda: base.lights_ctrl(0, base.head_light_status),
    f['code']['base_on']: lambda: base.lights_ctrl(255, base.head_light_status),
    f['code']['head_ct']: lambda: cvf.head_light_ctrl(3),
    f['code']['base_ct']: base.base_lights_ctrl
}

cmd_feedback_actions = [
    f['code']['cv_none'], f['code']['cv_moti'],
    f['code']['cv_face'], f['code']['cv_objs'],
    f['code']['cv_clor'], f['code']['mp_hand'],
    f['code']['cv_auto'], f['code']['mp_face'],
    f['code']['mp_pose'], f['code']['re_none'],
    f['code']['re_capt'], f['code']['re_reco'],
    f['code']['mc_lock'], f['code']['mc_unlo'],
    f['code']['led_off'], f['code']['led_aut'],
    f['code']['led_ton'], f['code']['base_of'],
    f['code']['base_on'], f['code']['head_ct'],
    f['code']['base_ct']
]

# ─────────────────────────────────────────────────────────────────────────────
# Video streaming
# ─────────────────────────────────────────────────────────────────────────────

def process_cv_info(cmd):
    if cmd[f['fb']['detect_type']] != f['code']['cv_none']:
        print(cmd[f['fb']['detect_type']])

# ── Camera frame buffer ───────────────────────────────────────────────────────
# A single background thread captures frames continuously and stores the latest
# one.  Every /video_feed client reads from this shared buffer rather than
# calling frame_process() directly.  Benefits:
#   • Camera warm-up happens at boot, not on first browser connect.
#   • Multiple tabs share one capture call instead of stacking them.
#   • The feed returns a placeholder immediately while the camera initialises.

_frame_lock   = threading.Lock()
_latest_frame = None        # bytes – the most recent JPEG
_camera_ready = False       # set True on first successful real frame

# Stop auto-retrying the camera after this many consecutive failures.
# Each failed Picamera2 attempt leaks libcamera file descriptors; without
# this cap the process hits 'Too many open files' within about an hour.
MAX_CAMERA_PROBE_FAILURES = 30
_camera_retry_evt = threading.Event()
_camera_select_idx = None   # requested camera index from /select_camera (Command Center)
_camera_active_idx = None   # index of the USB camera currently in use


def _make_placeholder_frame(text="Camera warming up\xe2\x80\xa6"):
    """Generate a static JPEG shown before the camera is ready."""
    import cv2 as _cv2
    import numpy as _np
    img = _np.zeros((480, 640, 3), dtype=_np.uint8)
    img[:] = (20, 20, 24)
    _cv2.putText(img, text,
                 (140, 230), _cv2.FONT_HERSHEY_SIMPLEX, 0.75, (79, 245, 192), 2)
    _cv2.putText(img, "Please wait...",
                 (215, 270), _cv2.FONT_HERSHEY_SIMPLEX, 0.5, (110, 110, 130), 1)
    _cv2.putText(img, "UGV Robot",
                 (245, 310), _cv2.FONT_HERSHEY_SIMPLEX, 0.45, (60, 60, 70), 1)
    _, buf = _cv2.imencode('.jpg', img, [int(_cv2.IMWRITE_JPEG_QUALITY), 60])
    return buf.tobytes()


_placeholder = _make_placeholder_frame()


def _probe_usb_camera(preferred=None):
    """
    Reliably detect a USB/V4L camera by probing /dev/video* directly with
    cv2.VideoCapture, rather than relying on lsusb string matching (which
    misses many webcams that enumerate as 'Video', 'Imaging', 'USB2.0', etc).

    When `preferred` is given, that /dev/videoN is probed first (used by
    /select_camera). Returns (True, capture_object) or (False, None).
    """
    global _camera_active_idx
    import glob as _glob
    import cv2 as _cv2

    # Try indices 0-3 covering /dev/video0 .. /dev/video3,
    # with the preferred index first when a switch was requested.
    indices = list(range(4))
    if preferred is not None and preferred in indices:
        indices.remove(preferred)
        indices.insert(0, preferred)
    for idx in indices:
        try:
            cap = _cv2.VideoCapture(idx, _cv2.CAP_V4L2)
            if cap is not None and cap.isOpened():
                # Do a test read to confirm real frames come out
                ok, frame = cap.read()
                if ok and frame is not None:
                    cap.set(_cv2.CAP_PROP_FRAME_WIDTH,
                            f['video']['default_res_w'])
                    cap.set(_cv2.CAP_PROP_FRAME_HEIGHT,
                            f['video']['default_res_h'])
                    # Try to raise frame rate
                    cap.set(_cv2.CAP_PROP_FPS, 30)
                    # Shrink internal buffer so frames are always fresh
                    cap.set(_cv2.CAP_PROP_BUFFERSIZE, 1)
                    print(f"[video] USB camera found at /dev/video{idx}")
                    _camera_active_idx = idx
                    return True, cap
            if cap:
                cap.release()
        except Exception as e:
            print(f"[video] probe /dev/video{idx}: {e}")
    return False, None


def _camera_capture_loop():
    """
    Runs forever in a daemon thread.

    Strategy:
    1. Reuse the camera object cv_ctrl already opened at init (CSI) if present.
    2. Attempt USB camera first (probes /dev/video0..3 with a real read test).
    3. Fall back to CSI (Picamera2) if no USB camera found.
    4. If both fail, keep retrying every 3 s for MAX_CAMERA_PROBE_FAILURES
       attempts, then STOP retrying (each failed Picamera2 attempt leaks
       libcamera file descriptors and eventually exhausts the process limit
       -> 'Too many open files' -> every Flask route 500s).  A camera plugged
       in later can be picked up via POST /retry_camera.
    5. On read failure, release and re-probe instead of looping on errors.
    """
    global _latest_frame, _camera_ready, _camera_select_idx, _camera_active_idx
    import cv2 as _cv2
    import numpy as _np

    RETRY_DELAY = 3.0   # seconds between full re-probe cycles on failure

    camera   = None     # cv2.VideoCapture / Picamera2 / None
    use_csi  = False    # True when using Picamera2
    probe_failures = 0

    def _make_error_frame(msg):
        """Generate a JPEG with an error message overlaid."""
        img = _np.zeros((480, 640, 3), dtype=_np.uint8)
        img[:] = (20, 20, 24)
        _cv2.putText(img, msg, (60, 230),
                     _cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 80, 80), 2)
        _cv2.putText(img, "Check camera connection",
                     (130, 270), _cv2.FONT_HERSHEY_SIMPLEX, 0.45, (130, 130, 140), 1)
        _, buf = _cv2.imencode('.jpg', img,
                               [int(_cv2.IMWRITE_JPEG_QUALITY), 60])
        return buf.tobytes()

    while True:
        # ── 0. Stop auto-retrying after too many failures (FD-leak guard) ──
        if probe_failures >= MAX_CAMERA_PROBE_FAILURES:
            with _frame_lock:
                if not _camera_ready:
                    _latest_frame = _make_error_frame("No camera detected")
            # Wake up when a retry is requested
            if _camera_retry_evt.wait(timeout=5.0):
                _camera_retry_evt.clear()
                probe_failures = 0
                print("[video] /retry_camera requested - re-probing")
            continue

        # ── 1. Reuse the camera object cv_ctrl opened at init ─────────
        camera      = None
        use_csi     = False
        reused_csi  = False
        # cv_ctrl opens /dev/video0 AT IMPORT and keeps it forever — the #1
        # reason our own probe then reports 'Device or resource busy'.
        # Reuse it whenever it actually delivers frames.
        if getattr(cvf, 'usb_camera_connected', False) and getattr(cvf, 'camera', None) is not None:
            try:
                test = cvf.camera.read()
                if test is not None and test[0] and test[1] is not None:
                    camera  = cvf.camera
                    use_csi = False
                    reused_csi = True
                    import os as _os, re as _re, glob as _glob2
                    _camera_active_idx = None
                    for _fd in _glob2.glob('/proc/self/fd/*'):
                        try:
                            _t = _os.readlink(_fd)
                            _m = _re.fullmatch(r'/dev/video(\d+)', _t)
                            if _m:
                                _camera_active_idx = int(_m.group(1))
                                break
                        except OSError:
                            continue
                    print(f"[video] Using USB camera already opened by cv_ctrl (video{_camera_active_idx})")
            except Exception:
                reused_csi = False
        if camera is None and getattr(cvf, 'picam2', None) is not None and not getattr(cvf, 'usb_camera_connected', False):
            try:
                test = cvf.picam2.capture_array()
                if test is not None:
                    camera     = cvf.picam2
                    use_csi    = True
                    reused_csi = True
                    print("[video] Using CSI camera (reusing cv_ctrl instance)")
            except Exception:
                reused_csi = False
                # The old instance is dead - release its descriptors and drop it.
                try:
                    cvf.picam2.close()
                except Exception:
                    pass
                cvf.picam2 = None

        # ── 2. Probe for USB camera (preferred index first when switching) ──
        if camera is None:
            usb_found, camera = _probe_usb_camera(preferred=_camera_select_idx)
            _camera_select_idx = None          # switch request handled for this pass
            if usb_found:
                use_csi = False
                print("[video] Using USB camera")

        # ── 3. Fall back to a fresh CSI (Picamera2) instance ─────────
        if camera is None:
            try:
                from picamera2 import Picamera2 as _Picam2
                picam = _Picam2()
                picam.configure(picam.create_video_configuration(
                    main={"format": "XRGB8888",
                          "size": (f['video']['default_res_w'],
                                   f['video']['default_res_h'])}))
                picam.start()
                use_csi = True
                camera  = picam
                print("[video] Using CSI camera (Picamera2)")
            except Exception as e:
                print(f"[video] No camera found (USB and CSI both failed): {e}")
                # Clean up the half-initialised Picamera2 object so its
                # libcamera file descriptors are released.  Without this
                # every failed attempt leaks FDs until the process dies.
                try:
                    picam._preview = None   # __del__/close() expects this attr
                    picam.stop()
                except Exception:
                    pass
                try:
                    picam.close()
                except Exception:
                    pass
                with _frame_lock:
                    if not _camera_ready:
                        _latest_frame = _make_error_frame("No camera detected")
                probe_failures += 1
                time.sleep(RETRY_DELAY)
                continue   # back to top of while loop, re-probe

        # ── 4. Capture loop ───────────────────────────────────────────
        # Inject the found camera object into cvf so frame_process()
        # can apply CV overlays, OSD, info deque, etc. regardless of type.
        if use_csi:
            if not reused_csi:
                cvf.picam2 = camera
            cvf.usb_camera_connected = False
        else:
            cvf.camera               = camera
            cvf.usb_camera_connected = True

        probe_failures = 0
        consecutive_errors = 0
        while True:
            try:
                # Camera switch requested (Command Center): release and re-probe.
                if _camera_select_idx is not None:
                    print(f"[video] switching to /dev/video{_camera_select_idx}")
                    try:
                        (camera.stop() if use_csi else camera.release())
                    except Exception:
                        pass
                    _camera_active_idx = None
                    camera = None
                    break
                # Route everything through cvf.frame_process() so CV modes,
                # OSD, info overlays, FPS counter, etc. all work normally.
                frame = cvf.frame_process()

                if frame:
                    with _frame_lock:
                        _latest_frame = frame
                    if not _camera_ready:
                        _camera_ready = True
                        print("[video] Camera ready – live stream started")
                    consecutive_errors = 0

            except Exception as e:
                consecutive_errors += 1
                if consecutive_errors <= 5:
                    print(f"[video] capture error #{consecutive_errors}: {e}")

                if consecutive_errors >= 10:
                    # Too many errors – re-probe
                    print("[video] Too many errors – re-probing camera")
                    try:
                        if use_csi:
                            camera.stop()
                        else:
                            camera.release()
                    except Exception:
                        pass
                    camera = None
                    with _frame_lock:
                        _latest_frame = _make_error_frame("Camera reconnecting...")
                    time.sleep(RETRY_DELAY)
                    break   # break inner loop → outer loop re-probes
                else:
                    time.sleep(0.1)


def generate_frames():
    """
    MJPEG generator served to every browser client.
    Sends the placeholder immediately then switches to live frames the instant
    the capture thread produces them.  Caps live output at 30 fps.
    """
    LIVE_RATE       = 1.0 / 30   # max frame rate sent to browser
    WARMUP_RATE     = 0.25       # placeholder refresh rate while waiting

    last_sent = 0.0

    while True:
        now = time.time()

        with _frame_lock:
            frame = _latest_frame

        if frame is None:
            # Still warming up – drip-feed placeholder
            if now - last_sent >= WARMUP_RATE:
                try:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n'
                           + _placeholder + b'\r\n')
                    last_sent = now
                except GeneratorExit:
                    return
                except Exception:
                    return
            else:
                time.sleep(0.05)
            continue

        # Live frame available – enforce rate limit
        gap = LIVE_RATE - (now - last_sent)
        if gap > 0:
            time.sleep(gap)
            continue

        try:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            last_sent = time.time()
        except GeneratorExit:
            return
        except Exception as e:
            print(f"[generate_frames] client disconnected: {e}")
            return

# ─────────────────────────────────────────────────────────────────────────────
# Flask routes
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    audio_ctrl.play_random_audio("connected", False)
    return render_template('index.html')

@app.route('/config')
def get_config():
    with open(thisPath + '/config.yaml', 'r') as file:
        yaml_content = file.read()
    return yaml_content

@app.route('/<path:filename>')
def serve_static(filename):
    return send_from_directory('templates', filename)

@app.route('/get_photo_names')
def get_photo_names():
    img_exts = ('.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp')
    base_dir = thisPath + '/templates/pictures'
    photo_files = sorted(
        (fn for fn in os.listdir(base_dir)
         if os.path.isfile(os.path.join(base_dir, fn))
         and fn.lower().endswith(img_exts)),
        key=lambda x: os.path.getmtime(os.path.join(base_dir, x)),
        reverse=True)
    return jsonify(photo_files)

@app.route('/delete_photo', methods=['POST'])
def delete_photo():
    filename = request.form.get('filename')
    try:
        os.remove(os.path.join(thisPath + '/templates/pictures', filename))
        return jsonify(success=True)
    except Exception as e:
        print(e)
        return jsonify(success=False)

@app.route('/videos/<path:filename>')
def videos(filename):
    return send_from_directory(thisPath + '/templates/videos', filename)

@app.route('/get_video_names')
def get_video_names():
    video_files = sorted(
        [fn for fn in os.listdir(thisPath + '/templates/videos/')
         if fn.endswith('.mp4')],
        key=lambda fn: os.path.getctime(
            os.path.join(thisPath + '/templates/videos/', fn)),
        reverse=True)
    return jsonify(video_files)

@app.route('/delete_video', methods=['POST'])
def delete_video():
    filename = request.form.get('filename')
    try:
        os.remove(os.path.join(thisPath + '/templates/videos', filename))
        return jsonify(success=True)
    except Exception as e:
        print(e)
        return jsonify(success=False)

@app.route('/activate_lucy', methods=['POST'])
def activate_lucy():
    try:
        cvf.initiate_interaction()
        return jsonify({'status': 'success', 'message': 'Lucy is activated and listening.'})
    except Exception as e:
        print(f"Error activating Lucy: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to activate Lucy'})

@app.route('/toggle_gesture', methods=['POST'])
def toggle_gesture():
    enable = request.form.get('enable', 'false').lower() == 'true'
    try:
        cvf.toggle_gesture_control(enable)
        status = "enabled" if enable else "disabled"
        return jsonify({'status': 'success', 'message': f'Gesture control {status}'})
    except Exception as e:
        print(f"Error toggling gesture control: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to toggle gesture control'})

@app.route('/execute_command', methods=['POST'])
def execute_command():
    # Accept both form-encoded ($.post default) and JSON bodies.
    if request.is_json:
        command = (request.get_json(silent=True) or {}).get('command')
    else:
        command = request.form.get('command')
    if not command:
        return jsonify({'status': 'error', 'message': 'Missing command'}), 400
    try:
        cvf.execute_command(command)
        return jsonify({'status': 'success', 'message': f'Executed command: {command}'})
    except Exception as e:
        print(f"Error executing command {command}: {e}")
        return jsonify({'status': 'error', 'message': f'Failed to execute command: {command}'})

@app.route('/toggle_lights', methods=['POST'])
def toggle_lights():
    base.base_lights_ctrl()
    if base.base_light_status > 0:
        audio_ctrl.play_speech("Lights activated")
        return jsonify({'status': 'success', 'message': 'Lights activated'})
    else:
        audio_ctrl.play_speech("Lights deactivated")
        return jsonify({'status': 'success', 'message': 'Lights deactivated'})

@app.route('/toggle_listen', methods=['POST'])
def toggle_listen():
    cvf.toggle_listening()
    if cvf.listening_active:
        audio_ctrl.play_speech("Listening mode activated")
        return jsonify({'status': 'success', 'message': 'Listening mode activated'})
    else:
        audio_ctrl.play_speech("Listening mode deactivated")
        return jsonify({'status': 'success', 'message': 'Listening mode deactivated'})

@app.route('/force_reboot', methods=['POST'])
def force_reboot():
    try:
        os.system("sudo reboot --force")
        return jsonify({'status': 'success', 'message': 'System is rebooting...'})
    except Exception as e:
        print(f"Error triggering force reboot: {e}")
        return jsonify({'status': 'error', 'message': 'Failed to trigger reboot'})

# ── LIDAR avoidance control endpoints ────────────────────────────────────────

@app.route('/lidar_avoidance', methods=['POST'])
def toggle_lidar_avoidance():
    """Enable or disable LIDAR obstacle avoidance from the UI."""
    enable = request.form.get('enable', 'true').lower() == 'true'
    if enable:
        avoider.resume()
        msg = 'LIDAR avoidance enabled'
    else:
        avoider.pause()
        msg = 'LIDAR avoidance disabled'
    return jsonify({'status': 'success', 'message': msg,
                    'avoidance_active': avoider._active,
                    'avoidance_state':  avoider.state})

@app.route('/lidar_status', methods=['GET'])
def lidar_status():
    """Return current LIDAR avoidance state for UI polling."""
    hw_connected = (base.rl.lidar_ser is not None)
    enabled      = bool(f['base_config']['use_lidar'])
    # "Port open" is not "sensor streaming" - a powered-off D500 still holds
    # the port open.  Report the age of the last full revolution instead.
    scan_age = (time.time() - getattr(base.rl, 'lidar_scan_time', 0.0)) if base.rl.lidar_scan_time > 0 else None
    streaming = scan_age is not None and scan_age < 3.0
    # Wire health: raw bytes/s arriving on the port vs valid frames parsed.
    # Bytes with no frames => the cable is on the wrong pin (PWM) or corrupt.
    return jsonify({
        'avoidance_active': avoider._active,
        'avoidance_state':  avoider.state,
        'use_lidar':        enabled,
        'hw_connected':     hw_connected,
        'streaming':        streaming,
        'scan_age_s':       scan_age if scan_age is not None else -1,
        'rx_bps':           round(getattr(base.rl, 'rx_bps', 0.0), 1),
        'frames_per_s':     round(getattr(base.rl, 'frames_per_s', 0.0), 1),
        # Tell the UI why things aren't working
        'status_msg': (
            'Active'               if enabled and hw_connected and avoider._active else
            'Paused (manual ctrl)' if enabled and hw_connected and not avoider._active else
            'LIDAR not connected'  if enabled and not hw_connected else
            'Disabled in config'
        )
    })

@app.route('/lidar_points', methods=['GET'])
def lidar_points():
    """
    Return the latest full LIDAR scan as JSON for the browser radar.
    Angles are in radians (0 = forward after +180 deg hardware offset),
    distances in mm.  Returns empty lists when LIDAR is not connected.
    """
    try:
        now = time.time()
        # Prefer the dense 1-degree occupancy picture (last 3 s, built from
        # every valid packet across revolutions); fall back to the last raw
        # scan when the bins are empty.
        bins = getattr(base.rl, 'lidar_bins', None)
        angles, distances = [], []
        if bins:
            for deg in range(360):
                d, ts = bins[deg]
                if d > 0 and (now - ts) < 3.0:
                    angles.append(deg * 3.14159265358979 / 180.0)
                    distances.append(d)
        if not angles:
            angles = list(base.rl.lidar_angles_show)
            distances = list(base.rl.lidar_distances_show)
        hw_ok = (base.rl.lidar_ser is not None)
        streaming = getattr(base.rl, 'lidar_scan_time', 0.0) > 0 and \
            (now - base.rl.lidar_scan_time) < 3.0
        return jsonify({
            'angles': angles,
            'distances': distances,
            'hw_connected': hw_ok,
            'streaming': streaming,
            'use_lidar': bool(f['base_config']['use_lidar'])
        })
    except Exception as e:
        return jsonify({'angles': [], 'distances': [],
                        'hw_connected': False, 'error': str(e)})

@app.route('/restart_server', methods=['POST'])
def restart_server():
    """
    Gracefully restart only the app.py process (not the whole Pi).
    Requires the process to be managed by systemd or a wrapper that
    restarts on exit.  We send SIGTERM to ourselves after responding.
    """
    import signal
    def _do_restart():
        time.sleep(0.5)   # give Flask time to flush the response
        os.kill(os.getpid(), signal.SIGTERM)
    threading.Thread(target=_do_restart, daemon=True).start()
    return jsonify({'status': 'success', 'message': 'Server process restarting…'})

# ─────────────────────────────────────────────────────────────────────────────
# WebRTC
# ─────────────────────────────────────────────────────────────────────────────

def manage_connections(pc_id, pc):
    if len(active_pcs) >= MAX_CONNECTIONS:
        oldest_pc_id = next(iter(active_pcs))
        old_pc = active_pcs.pop(oldest_pc_id)
        try:
            old_pc.close()
        except Exception:
            pass
    active_pcs[pc_id] = pc

async def offer_async():
    # NOTE: Flask's get_json is synchronous (the awaited variant is a Quart-ism
    # that the original aiortc sample carried over and that broke every offer).
    params = request.get_json(force=True, silent=True)
    if not params or not params.get("sdp"):
        return jsonify({"status": "error",
                        "message": "Missing SDP in offer"}), 400
    offer  = RTCSessionDescription(sdp=params["sdp"], type=params.get("type", "offer"))
    pc     = RTCPeerConnection()
    pc_id  = ("PeerConnection(%s)" % uuid.uuid4())[:8]
    manage_connections(pc_id, pc)
    try:
        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        return jsonify({"sdp": pc.localDescription.sdp,
                        "type": pc.localDescription.type})
    except Exception as e:
        # Fail fast with a clear non-200 so the browser falls back to MJPEG.
        logging.warning("[webrtc] offer failed: %s", e)
        try:
            active_pcs.pop(pc_id, None)
            await pc.close()
        except Exception:
            pass
        return jsonify({"status": "error",
                        "message": "WebRTC setup failed: %s" % e}), 503

def offer():
    # Drive the coroutine on a loop we actually run, with a hard timeout.
    # The previous version scheduled onto a loop that was never started
    # (run_coroutine_threadsafe without run_forever), so the request hung
    # forever on any offer.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(
            asyncio.wait_for(offer_async(), timeout=OFFER_TIMEOUT_SEC))
    except asyncio.TimeoutError:
        logging.warning("[webrtc] offer timed out after %.1fs", OFFER_TIMEOUT_SEC)
        return jsonify({"status": "error",
                        "message": "WebRTC setup timed out; use MJPEG stream"}), 503
    except Exception as e:
        return jsonify({"status": "error",
                        "message": "WebRTC error: %s" % e}), 500
    finally:
        loop.close()

@app.route('/offer', methods=['POST'])
def offer_route():
    return offer()

@app.route('/video_feed')
def video_feed():
    resp = Response(
        generate_frames(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )
    # Prevent any proxy or browser from caching the stream
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma']        = 'no-cache'
    resp.headers['Expires']       = '0'
    resp.headers['X-Accel-Buffering'] = 'no'   # disable nginx buffering if present
    return resp


@app.route('/camera_status')
def camera_status():
    """Lightweight endpoint polled by the browser to know when the camera is live."""
    return jsonify({'ready': _camera_ready})

@app.route('/retry_camera', methods=['POST'])
def retry_camera():
    """
    Re-trigger camera detection (e.g. after plugging a camera in).
    The capture thread stopped auto-retrying after MAX_CAMERA_PROBE_FAILURES
    failures to avoid leaking file descriptors; this endpoint resets it.
    """
    _camera_retry_evt.set()
    return jsonify({'status': 'success',
                    'message': 'Camera detection restarted - check /camera_status'})


@app.route('/camera_list')
def camera_list():
    """List V4L2 video devices with human-readable names (for the Command Center)."""
    import glob as _glob
    import os as _os
    import re as _re
    import subprocess as _sp

    # Which /dev/videoN does THIS process actually hold open? (cv_ctrl opens the
    # camera at import, bypassing _probe_usb_camera, so derive it from our fds.)
    active_idx = _camera_active_idx
    if active_idx is None:
        for fd in _glob.glob('/proc/self/fd/*'):
            try:
                target = _os.readlink(fd)
                m = _re.fullmatch(r'/dev/video(\d+)', target)
                if m:
                    active_idx = int(m.group(1))
                    break
            except OSError:
                continue

    cams = []
    seen = set()
    for dev in sorted(_glob.glob('/dev/video*'),
                      key=lambda p: int(_re.findall(r'\d+', p)[0] or 0)):
        idx = int(_re.findall(r'\d+', dev)[0])
        if idx in seen or idx > 9:
            continue
        seen.add(idx)
        name = dev
        try:
            out = _sp.run(['v4l2-ctl', '-d', dev, '--info'],
                          capture_output=True, text=True, timeout=2)
            m = _re.search(r'Card type\s*:\s*(.+)', out.stdout)
            if m:
                name = m.group(1).strip()
        except Exception:
            pass
        cams.append({'index': idx, 'name': name,
                     'in_use': idx == active_idx})
    return jsonify({'cameras': cams, 'active': active_idx})


@app.route('/select_camera', methods=['POST'])
def select_camera():
    """Switch the live stream to a different /dev/videoN (Command Center)."""
    global _camera_select_idx
    try:
        idx = int(request.form.get('index', -1))
    except (TypeError, ValueError):
        return jsonify({'status': 'error', 'message': 'bad index'}), 400
    if idx < 0 or idx > 9:
        return jsonify({'status': 'error', 'message': 'index out of range'}), 400
    _camera_select_idx = idx
    _camera_retry_evt.set()      # wake the guard mode if probing had given up
    return jsonify({'status': 'success',
                    'message': f'Switching to /dev/video{idx}'})


@app.route('/video_feed2')
def video_feed2():
    """Second MJPEG stream (same frames) so two viewers can attach at once."""
    resp = Response(
        generate_frames(),
        mimetype='multipart/x-mixed-replace; boundary=frame'
    )
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['X-Accel-Buffering'] = 'no'
    return resp

@app.route('/send_command', methods=['POST'])
def handle_command():
    command = request.form['command']
    print("Received command:", command)
    cvf.info_update("CMD:" + command, (0, 255, 255), 0.36)
    try:
        cmdline_ctrl(command)
    except Exception as e:
        print(f"[app.handle_command] error: {e}")
    return jsonify({"status": "success", "message": "Command received"})

@app.route('/getAudioFiles', methods=['GET'])
def get_audio_files():
    files = [fn for fn in os.listdir(UPLOAD_FOLDER)
             if os.path.isfile(os.path.join(UPLOAD_FOLDER, fn))
             and (fn.endswith('.mp3') or fn.endswith('.wav'))]
    return jsonify(files)

@app.route('/uploadAudio', methods=['POST'])
def upload_audio():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'})
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'})
    filename = secure_filename(file.filename)
    file.save(os.path.join(UPLOAD_FOLDER, filename))
    return jsonify({'success': 'File uploaded successfully'})

@app.route('/playAudio', methods=['POST'])
def play_audio():
    audio_file = request.form['audio_file']
    audio_ctrl.play_audio_thread(thisPath + '/sounds/others/' + audio_file)
    return jsonify({'success': 'Audio is playing'})

@app.route('/stop_audio', methods=['POST'])
def audio_stop():
    audio_ctrl.stop()
    return jsonify({'success': 'Audio stop'})

@app.route('/settings/<path:filename>')
def serve_static_settings(filename):
    return send_from_directory('templates', filename)

# ─────────────────────────────────────────────────────────────────────────────
# WebSocket handlers
# ─────────────────────────────────────────────────────────────────────────────

@socketio.on('json', namespace='/json')
def handle_socket_json(data):
    """
    Forward JSON commands to the base controller.
    Motion commands (T==1 or T==13 with non-zero speed) pause the LIDAR
    avoider so the user has full manual control.  The watchdog thread
    re-enables the avoider after MANUAL_PAUSE_SEC of inactivity.
    Motor magnitudes are clamped server-side to max_speed so no client
    can command over-speed.
    """
    global _last_manual_cmd_time
    try:
        t_code = data.get('T', -1) if isinstance(data, dict) else -1
        if t_code in (1, 13):
            keyL, keyR = ('L', 'R') if ('L' in data or 'R' in data) else ('X', 'Z')
            # Drop the unused alternate key pair so a mixed-key command
            # (e.g. L:0 R:0 X:9 Z:9) cannot smuggle unclamped speeds through.
            for alt in (('X', 'Z') if keyL == 'L' else ('L', 'R')):
                data.pop(alt, None)
            try:
                L = float(data.get(keyL, 0))
                R = float(data.get(keyR, 0))
            except (TypeError, ValueError):
                L = R = 0.0
            if math.isnan(L): L = 0.0
            if math.isnan(R): R = 0.0
            Lc = max(-MAX_DRIVE_SPEED, min(MAX_DRIVE_SPEED, L))
            Rc = max(-MAX_DRIVE_SPEED, min(MAX_DRIVE_SPEED, R))
            if (Lc, Rc) != (round(L, 3), round(R, 3)):
                print(f"[drive] clamped over-speed command: "
                      f"{keyL}={L} {keyR}={R} -> {round(Lc, 3)} {round(Rc, 3)}")
            data[keyL] = round(Lc, 3)
            data[keyR] = round(Rc, 3)
            print(f"[drive] recv {keyL}={data[keyL]} {keyR}={data[keyR]}")
            if Lc != 0 or Rc != 0:
                # User is actively driving – hand control over
                avoider.pause()
                _last_manual_cmd_time = time.time()
        base.base_json_ctrl(data)
    except Exception as e:
        print("Error handling JSON data:", e)


def update_data_websocket_single():
    try:
        socket_data = {
            f['fb']['picture_size']: si.pictures_size,
            f['fb']['video_size']:   si.videos_size,
            f['fb']['cpu_load']:     si.cpu_load,
            f['fb']['cpu_temp']:     si.cpu_temp,
            f['fb']['ram_usage']:    si.ram,
            f['fb']['wifi_rssi']:    si.wifi_rssi,
            f['fb']['led_mode']:     cvf.cv_light_mode,
            f['fb']['detect_type']:  cvf.cv_mode,
            f['fb']['detect_react']: cvf.detection_reaction_mode,
            f['fb']['pan_angle']:    cvf.pan_angle,
            f['fb']['tilt_angle']:   cvf.tilt_angle,
            f['fb']['base_voltage']: base.base_data['v'],
            f['fb']['video_fps']:    cvf.video_fps,
            f['fb']['cv_movtion_mode']: cvf.cv_movtion_lock,
            f['fb']['base_light']:   base.base_light_status
        }
        socketio.emit('update', socket_data, namespace='/ctrl')
    except Exception as e:
        print("An [app.update_data_websocket_single] error occurred:", e)


def update_data_loop():
    base.base_oled(2, "F/J:5000/8888")
    start_time = time.time()
    time.sleep(1)
    while True:
        update_data_websocket_single()
        eth0 = si.eth0_ip
        wlan = si.wlan_ip
        base.base_oled(0, f"E:{eth0}" if eth0 else "E: No Ethernet")
        base.base_oled(1, f"W:{wlan}" if wlan else f"W: NO {si.net_interface}")
        elapsed = time.time() - start_time
        h  = int(elapsed // 3600)
        m  = int((elapsed % 3600) // 60)
        s  = int(elapsed % 60)
        base.base_oled(3, f"{si.wifi_mode} {h:02d}:{m:02d}:{s:02d} {si.wifi_rssi}dBm")
        time.sleep(5)


def base_data_loop():
    """
    Main sensor polling loop – reads base feedback and optional extra sensors.
    LIDAR is handled in its own thread (lidar_recv_loop) so a slow/blocking
    serial read never starves the base feedback loop.
    """
    sensor_interval  = 1.0
    sensor_read_time = time.time()
    while True:
        try:
            cvf.update_base_data(base.feedback_data())
        except Exception as e:
            print(f"[base_data_loop] feedback error: {e}")

        if base.extra_sensor:
            if time.time() - sensor_read_time > sensor_interval:
                try:
                    base.rl.read_sensor_data()
                except Exception as e:
                    print(f"[base_data_loop] sensor error: {e}")
                sensor_read_time = time.time()

        time.sleep(0.025)


def lidar_recv_loop():
    """
    Dedicated thread for LIDAR serial reads.
    Runs only when use_lidar: true in config.yaml.
    Keeps lidar_angles_show / lidar_distances_show populated with fresh data.
    Falls back gracefully when the serial port is absent or disconnects.
    """
    import glob as _glob
    print("[lidar] LIDAR receive thread started")
    # Watchdogs: (a) wire alive but no valid frames for a while -> the sensor
    # MCU is likely stuck (CP210x DTR-reset boards) - pulse it once; (b) wire
    # totally silent on a port that may have re-enumerated (ttyUSB0->ttyUSB1)
    # -> reopen so we re-glob and follow the device to its new node.
    last_kick = 0.0
    last_reopen = 0.0
    while True:
        if base.rl.lidar_ser is None:
            # Reconnect through the same port-picker as startup, so we never
            # latch onto the silent base board while the USB adapter exists.
            try:
                base.rl.open_lidar_serial()
                if base.rl.lidar_ser is None:
                    time.sleep(3)
                    continue
            except Exception as e:
                print(f"[lidar] Reconnect failed: {e}")
                time.sleep(3)
                continue
        try:
            base.rl.lidar_data_recv()   # pumps ~100 ms of stream, self-resyncs
        except Exception as e:
            print(f"[lidar] recv error: {e}")
            base.rl.lidar_ser = None    # trigger reconnect
            time.sleep(1)
            continue
        now = time.time()
        # (b) silent wire for >10 s on a still-open port: reopen (re-globs,
        # follows a device that re-enumerated to a new /dev/ttyUSBn).
        if base.rl.rx_bps < 10 and now - last_reopen > 10:
            print("[lidar] wire silent 10s - reopening port")
            last_reopen = now
            base.rl.open_lidar_serial()
        # (a) alive-but-garbage: kick the sensor's MCU via DTR pulse.
        elif base.rl.rx_bps > 500 and base.rl.frames_per_s < 1 and now - last_kick > 20:
            print("[lidar] wire alive but 0 frames - kicking sensor")
            last_kick = now
            base.rl.kick_lidar()
        time.sleep(0.01)                # yield; recv() already throttles by data


def manual_control_watchdog():
    """
    Re-enables LIDAR avoidance MANUAL_PAUSE_SEC after the user last moved
    the joystick, so the robot automatically returns to obstacle avoidance
    mode when left idle.  (Guarded by _last_manual_cmd_time > 0 so the robot
    never starts driving by itself right after boot.)
    """
    while True:
        time.sleep(0.5)
        if not avoider._active and f['base_config']['use_lidar']:
            if _last_manual_cmd_time > 0 and \
               time.time() - _last_manual_cmd_time > MANUAL_PAUSE_SEC:
                avoider.resume()
                logging.info("[app] Avoidance re-enabled by watchdog")


@socketio.on('message', namespace='/ctrl')
def handle_socket_cmd(message):
    try:
        # Accept both a JSON string (browser socket.io.js emits) and a
        # native dict (raw socket.io clients) — a dict crashed this handler.
        json_data = json.loads(message) if isinstance(message, (str, bytes, bytearray)) else message
    except (json.JSONDecodeError, TypeError):
        print("Error decoding JSON.[app.handle_socket_cmd]")
        return
    cmd_a = float(json_data.get("A", 0))
    if cmd_a in cmd_actions:
        cmd_actions[cmd_a]()
    if cmd_a in cmd_feedback_actions:
        threading.Thread(target=update_data_websocket_single,
                         daemon=True).start()

# ─────────────────────────────────────────────────────────────────────────────
# Version / product helpers
# ─────────────────────────────────────────────────────────────────────────────

def set_version(input_main, input_module):
    base.base_json_ctrl({"T": 900, "main": input_main, "module": input_module})
    names = {1: "RaspRover", 2: "UGV Rover", 3: "UGV Beast"}
    mods  = {0: "No Module", 1: "ARM", 2: "PT"}
    if input_main  in names: cvf.info_update(names[input_main],  (0,255,255), 0.36)
    if input_module in mods:  cvf.info_update(mods[input_module], (0,255,255), 0.36)

# ─────────────────────────────────────────────────────────────────────────────
# Command-line interpreter (send_command endpoint + cmd_on_boot)
# ─────────────────────────────────────────────────────────────────────────────

def cmdline_ctrl(args_string):
    if not args_string:
        return
    args = args_string.split()

    if args[0] == 'base':
        if args[1] in ('-c', '--cmd'):
            base.base_json_ctrl(json.loads(args[2]))
        elif args[1] in ('-r', '--recv'):
            cvf.show_recv_info(args[2] == 'on')

    elif args[0] == 'audio':
        if args[1] in ('-s', '--say'):
            audio_ctrl.play_speech_thread(' '.join(args[2:]))
        elif args[1] in ('-v', '--volume'):
            audio_ctrl.set_audio_volume(args[2])
        elif args[1] in ('-p', '--play_file'):
            audio_ctrl.play_file(args[2])

    elif args[0] == 'send':
        if args[1] in ('-a', '--add'):
            mac = "FF:FF:FF:FF:FF:FF" if args[2] in ('-b', '--broadcast') else args[2]
            base.base_json_ctrl({"T": 303, "mac": mac})
        elif args[1] in ('-rm', '--remove'):
            mac = "FF:FF:FF:FF:FF:FF" if args[2] in ('-b', '--broadcast') else args[2]
            base.base_json_ctrl({"T": 304, "mac": mac})
        elif args[1] in ('-b', '--broadcast'):
            base.base_json_ctrl({"T":306,"mac":"FF:FF:FF:FF:FF:FF","dev":0,"b":0,"s":0,"e":0,"h":0,"cmd":3,"megs":' '.join(args[2:])})
        elif args[1] in ('-g', '--group'):
            base.base_json_ctrl({"T":305,"dev":0,"b":0,"s":0,"e":0,"h":0,"cmd":3,"megs":' '.join(args[2:])})
        else:
            base.base_json_ctrl({"T":306,"mac":args[1],"dev":0,"b":0,"s":0,"e":0,"h":0,"cmd":3,"megs":' '.join(args[2:])})

    elif args[0] == 'cv':
        if args[1] in ('-r', '--range'):
            try:
                lower_nums = [int(n) for n in args[2].strip("[]").split(",")]
                upper_nums = [int(n) for n in args[3].strip("[]").split(",")]
                if all(0 <= n <= 255 for n in lower_nums + upper_nums):
                    cvf.change_target_color(lower_nums, upper_nums)
            except Exception:
                return
        elif args[1] in ('-s', '--select'):
            cvf.selet_target_color(args[2])

    elif args[0] in ('video', 'v'):
        if args[1] in ('-q', '--quality'):
            try:
                cvf.set_video_quality(int(args[2]))
            except Exception:
                return

    elif args[0] == 'line':
        if args[1] in ('-r', '--range'):
            try:
                lower_nums = [int(n) for n in args[2].strip("[]").split(",")]
                upper_nums = [int(n) for n in args[3].strip("[]").split(",")]
                if all(0 <= n <= 255 for n in lower_nums + upper_nums):
                    cvf.change_line_color(lower_nums, upper_nums)
            except Exception:
                return
        elif args[1] in ('-s', '--set'):
            if len(args) != 9:
                return
            try:
                cvf.set_line_track_args(*[float(a) for a in args[2:9]])
            except Exception:
                return

    elif args[0] == 'track':
        cvf.set_pt_track_args(args[1], args[2])

    elif args[0] == 'timelapse':
        if args[1] in ('-s', '--start'):
            if len(args) != 6:
                return
            try:
                cvf.timelapse(float(args[2]), float(args[3]),
                              float(args[4]), int(args[5]))
            except Exception:
                return
        elif args[1] in ('-e', '--end', '--stop'):
            cvf.mission_stop()

    elif args[0] == 'p':
        set_version(int(args[1][0]), int(args[1][1]))

    elif args[0] == 's':
        main_type   = int(args[1][0])
        module_type = int(args[1][1])
        speed_map = {1: (0.65, 0.3, "RaspRover"),
                     2: (0.5,  0.2, "UGV Rover"),
                     3: (0.5,  0.2, "UGV Beast")}
        if main_type in speed_map:
            ms, ss, name = speed_map[main_type]
            f['base_config']['robot_name']    = name
            f['args_config']['max_speed']     = ms
            f['args_config']['slow_speed']    = ss
        f['base_config']['main_type']   = main_type
        f['base_config']['module_type'] = module_type
        with open(thisPath + '/config.yaml', "w") as yaml_file:
            yaml.dump(f, yaml_file)
        set_version(main_type, module_type)

    elif args[0] == 'avoidance':
        # Command-line toggle:  avoidance on | avoidance off
        if len(args) > 1:
            if args[1] == 'on':
                avoider.resume()
                cvf.info_update("Avoidance ON", (0,255,0), 0.36)
            elif args[1] == 'off':
                avoider.pause()
                cvf.info_update("Avoidance OFF", (0,128,255), 0.36)

    elif args[0] == 'test':
        cvf.update_base_data({"T":1003,"mac":1111,"megs":"helllo aaaaaaaa"})


# ─────────────────────────────────────────────────────────────────────────────
# Boot command sequence
# ─────────────────────────────────────────────────────────────────────────────

def cmd_on_boot():
    cmd_list = [
        'base -c {"T":142,"cmd":50}',
        'base -c {"T":131,"cmd":1}',
        'base -c {"T":143,"cmd":0}',
        'base -c {{"T":4,"cmd":{}}}'.format(f['base_config']['module_type']),
        'base -c {"T":300,"mode":0,"mac":"EF:EF:EF:EF:EF:EF"}',
        'send -a -b'
    ]
    print('base -c {{"T":4,"cmd":{}}}'.format(f['base_config']['module_type']))
    for cmd in cmd_list:
        cmdline_ctrl(cmd)
        cvf.info_update(cmd, (0, 255, 255), 0.36)
    set_version(f['base_config']['main_type'], f['base_config']['module_type'])


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Raise the file-descriptor limit early - the camera/libcamera stack and
    # the web clients can otherwise exhaust the default 1024 soft limit.
    try:
        import resource as _resource
        _soft, _hard = _resource.getrlimit(_resource.RLIMIT_NOFILE)
        _resource.setrlimit(_resource.RLIMIT_NOFILE, (min(8192, _hard), _hard))
    except Exception:
        pass

    # Boot lights on briefly
    base.lights_ctrl(255, 255)

    audio_ctrl.play_random_audio("robot_started", False)
    si.update_folder(thisPath)

    # Point gimbal/arm forward
    if f['base_config']['module_type'] == 1:
        base.base_json_ctrl({
            "T": f['cmd_config']['cmd_arm_ctrl_ui'],
            "E": f['args_config']['arm_default_e'],
            "Z": f['args_config']['arm_default_z'],
            "R": f['args_config']['arm_default_r']
        })
    else:
        base.gimbal_ctrl(0, 0, 200, 10)

    # System info thread
    si.start()
    si.resume()

    # UI data broadcast thread
    threading.Thread(target=update_data_loop, daemon=True,
                     name="data-loop").start()

    # Base sensor polling thread (feedback_data only – no LIDAR blocking)
    threading.Thread(target=base_data_loop, daemon=True,
                     name="base-data-loop").start()

    # Dedicated LIDAR serial thread (only when enabled in config.yaml)
    if f['base_config']['use_lidar']:
        threading.Thread(target=lidar_recv_loop, daemon=True,
                         name="lidar-recv").start()
        # Start avoidance decision thread, but keep it PAUSED until the user
        # enables it from the UI (or drives manually) - never self-drive at boot.
        avoider.start()
        avoider.pause()
        threading.Thread(target=manual_control_watchdog, daemon=True,
                         name="avoidance-watchdog").start()
        print("[app] LIDAR data stream started (avoidance paused - enable in UI)")
        base.base_oled(3, "LIDAR radar ready")
    else:
        print("[app] LIDAR disabled (use_lidar: false in config.yaml)")

    base.lights_ctrl(0, 0)
    cmd_on_boot()

    # Start the shared camera capture thread so the first frame is ready
    # before any browser connects – eliminates the cold-start delay.
    threading.Thread(target=_camera_capture_loop, daemon=True,
                     name="camera-capture").start()
    print("[video] Camera capture thread started – warming up…")

    socketio.run(app, host='0.0.0.0', port=5000, allow_unsafe_werkzeug=True)
