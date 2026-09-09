"""
lidar_avoidance.py
------------------
LIDAR-based obstacle avoidance for a 4-wheel differential-drive robot.

How to integrate
----------------
1. Copy this file next to app.py / cv_ctrl.py on the Pi.
2. In app.py, after `base` is created add:

    import lidar_avoidance
    avoider = lidar_avoidance.LidarAvoider(base)
    avoider.start()

3. To pause avoidance while the user is manually driving, call:
    avoider.pause()   # hands control back to user
    avoider.resume()  # re-enables avoidance

4. The avoider respects base.use_lidar.  Enable it in config.yaml:
    base_config:
      use_lidar: true
"""

import threading
import time
import math
import numpy as np
import logging

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  Tuneable constants
# ─────────────────────────────────────────────

# Danger zones (mm).  Distances below these thresholds trigger reactions.
DANGER_STOP      = 250   # mm  — hard stop + reverse
DANGER_TURN      = 450   # mm  — begin turning away
DANGER_SLOW      = 700   # mm  — reduce forward speed

# Angular sectors (degrees, 0 = straight ahead after offset correction)
# The LD19 lidar is mounted so that 0° points forward on the robot.
# Adjust FRONT_HALF_WIDTH if the robot is wide relative to the sensor.
FRONT_HALF_WIDTH = 45    # degrees each side → 90° cone in front
REAR_HALF_WIDTH  = 45    # degrees each side → 90° cone behind

# Motor command T-codes (match your firmware)
CMD_MOVE = 1             # {"T":1,"L":<-1..1>,"R":<-1..1>}
CMD_OMNI = 13            # {"T":13,"X":<speed>,"Z":<turn>}  for mecanum / omni

# Speed constants (−1.0 … +1.0)
CRUISE_SPEED     = 0.35
SLOW_SPEED       = 0.20
REVERSE_SPEED    = -0.25
MAX_TURN_BIAS    = 0.45   # how aggressively to steer away

# How long to back up before re-scanning (seconds)
REVERSE_DURATION = 0.6
TURN_DURATION    = 0.9

# Loop interval
LOOP_HZ = 10             # evaluations per second


# ─────────────────────────────────────────────
#  Helper: polar scan → Cartesian danger map
# ─────────────────────────────────────────────

def sector_min_distance(angles_rad, distances_mm,
                        sector_center_deg, half_width_deg,
                        min_valid_mm=50):
    """
    Return the minimum valid distance (mm) inside a given angular sector.
    Returns float('inf') when no valid reading exists.

    Parameters
    ----------
    angles_rad      : list of floats  (radians, robot frame, 0 = forward)
    distances_mm    : list of ints
    sector_center_deg : float   centre of the sector (degrees)
    half_width_deg  : float   half-width of the sector (degrees)
    min_valid_mm    : int     distances below this are treated as noise
    """
    lo = math.radians(sector_center_deg - half_width_deg)
    hi = math.radians(sector_center_deg + half_width_deg)

    min_d = float('inf')
    for ang, d in zip(angles_rad, distances_mm):
        # normalise angle to [−π, π]
        a = math.atan2(math.sin(ang), math.cos(ang))
        if lo <= a <= hi and d >= min_valid_mm:
            if d < min_d:
                min_d = d
    return min_d


def weighted_turn_direction(angles_rad, distances_mm,
                            front_half_deg=FRONT_HALF_WIDTH,
                            danger_mm=DANGER_TURN,
                            min_valid_mm=50):
    """
    Returns a turn bias in [-1, +1].
    Positive  → turn LEFT  (counter-clockwise).
    Negative  → turn RIGHT (clockwise).

    The magnitude reflects how much the danger is off-centre:
    an obstacle dead-ahead returns a small value (random left/right bias),
    an obstacle to the right returns a strong positive (go left).
    """
    left_weight  = 0.0
    right_weight = 0.0

    lo = math.radians(-front_half_deg)
    hi = math.radians( front_half_deg)

    for ang, d in zip(angles_rad, distances_mm):
        a = math.atan2(math.sin(ang), math.cos(ang))
        if not (lo <= a <= hi):
            continue
        if d < min_valid_mm or d > danger_mm:
            continue
        # weight: closer obstacle = stronger push
        w = (danger_mm - d) / danger_mm   # 0…1
        if a < 0:          # obstacle on the right → push left
            right_weight += w
        else:              # obstacle on the left  → push right
            left_weight  += w

    total = left_weight + right_weight
    if total < 1e-6:
        return 0.0

    # bias: +1 = turn full left, -1 = turn full right
    bias = (right_weight - left_weight) / total
    return float(np.clip(bias, -1.0, 1.0))


# ─────────────────────────────────────────────
#  Main avoider class
# ─────────────────────────────────────────────

class LidarAvoider:
    """
    Background thread that reads LIDAR data from base.rl and issues
    differential-drive commands to base to avoid obstacles.

    The avoider runs a simple state machine:
        IDLE      – no LIDAR data yet / avoidance paused
        CRUISE    – clear path, drive forward at cruise speed
        SLOW      – obstacle detected ahead (DANGER_SLOW zone), reduce speed
        EVADE     – obstacle in DANGER_TURN zone, steer away smoothly
        REVERSE   – obstacle in DANGER_STOP zone, back up then turn
    """

    # State constants
    IDLE    = 'IDLE'
    CRUISE  = 'CRUISE'
    SLOW    = 'SLOW'
    EVADE   = 'EVADE'
    REVERSE = 'REVERSE'

    def __init__(self, base_controller, use_omni=False):
        """
        Parameters
        ----------
        base_controller : BaseController instance from base_ctrl.py
        use_omni        : True if the robot uses mecanum / omni wheels
                          (uses CMD_OMNI {"T":13,"X":...,"Z":...})
                          False for standard differential drive
                          (uses CMD_MOVE {"T":1,"L":...,"R":...})
        """
        self._base      = base_controller
        self._use_omni  = use_omni
        self._state     = self.IDLE
        self._active    = False          # paused / resumed
        self._thread    = None
        self._stop_evt  = threading.Event()

        # Last commanded speeds (to detect when we actually need to re-send)
        self._last_L    = 0.0
        self._last_R    = 0.0

        # Cooldown after a reverse manoeuvre (prevent oscillation)
        self._cooldown_until = 0.0

        logger.info("[LidarAvoider] Initialised (use_omni=%s)", use_omni)

    # ── public API ──────────────────────────────

    def start(self):
        """Start the background avoidance loop."""
        if self._thread and self._thread.is_alive():
            return
        self._stop_evt.clear()
        self._active = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("[LidarAvoider] Started")

    def stop(self):
        """Stop the background loop and halt the robot."""
        self._stop_evt.set()
        self._send_stop()
        logger.info("[LidarAvoider] Stopped")

    def pause(self, halt=False):
        """
        Pause avoidance (e.g. user is manually driving).
        When `halt` is set (explicit disable from the UI), also send a stop so
        the wheels don't keep the last avoider speed (the ESP32 holds the last
        commanded L/R until a new command arrives).
        """
        self._active = False
        if halt:
            self._send_stop()
        logger.info("[LidarAvoider] Paused%s", " + halted" if halt else "")

    def resume(self):
        """Re-enable automatic avoidance."""
        self._active = True
        logger.info("[LidarAvoider] Resumed")

    @property
    def state(self):
        return self._state

    # ── internal loop ───────────────────────────

    def _loop(self):
        interval = 1.0 / LOOP_HZ
        while not self._stop_evt.is_set():
            t0 = time.time()

            if not self._active:
                self._state = self.IDLE
                time.sleep(interval)
                continue

            # Grab a consistent snapshot of the latest LIDAR frame
            try:
                angles    = list(self._base.rl.lidar_angles_show)
                distances = list(self._base.rl.lidar_distances_show)
            except Exception:
                time.sleep(interval)
                continue

            if not angles:
                # No data yet – stay idle
                self._state = self.IDLE
                time.sleep(interval)
                continue

            self._process(angles, distances)

            # Maintain loop rate
            elapsed = time.time() - t0
            sleep_t = max(0.0, interval - elapsed)
            time.sleep(sleep_t)

    def _process(self, angles, distances):
        """Core decision logic called once per loop tick."""

        now = time.time()

        # ── 1. Measure key sectors ──────────────
        # Forward sector  (0° = straight ahead)
        front_dist = sector_min_distance(
            angles, distances,
            sector_center_deg=0, half_width_deg=FRONT_HALF_WIDTH)

        # Left / right sub-sectors for finer steering
        front_left_dist = sector_min_distance(
            angles, distances,
            sector_center_deg=30, half_width_deg=25)

        front_right_dist = sector_min_distance(
            angles, distances,
            sector_center_deg=-30, half_width_deg=25)

        # Rear sector (useful to prevent backing into something)
        rear_dist = sector_min_distance(
            angles, distances,
            sector_center_deg=180, half_width_deg=REAR_HALF_WIDTH)

        logger.debug(
            "[LidarAvoider] front=%.0fmm  fl=%.0f  fr=%.0f  rear=%.0f",
            front_dist, front_left_dist, front_right_dist, rear_dist)

        # ── 2. Cooldown guard (no action right after reversal) ──
        if now < self._cooldown_until:
            # Just hold the last commanded speed (probably turning)
            return

        # ── 3. State machine ────────────────────────────────────

        # --- DANGER_STOP: back up ---
        if front_dist < DANGER_STOP:
            if self._state != self.REVERSE:
                logger.info(
                    "[LidarAvoider] REVERSE – obstacle at %.0f mm", front_dist)
            self._state = self.REVERSE

            # Decide which way to turn after backing up
            turn_bias = weighted_turn_direction(angles, distances)
            if abs(turn_bias) < 0.15:
                # Obstacle dead-ahead: pick a side based on sub-sector
                turn_bias = 1.0 if front_left_dist > front_right_dist else -1.0

            self._execute_reverse_and_turn(turn_bias, rear_dist)
            return

        # --- DANGER_TURN: steer away ---
        if front_dist < DANGER_TURN:
            self._state = self.EVADE

            turn_bias = weighted_turn_direction(angles, distances)
            if abs(turn_bias) < 0.1:
                turn_bias = 1.0 if front_left_dist > front_right_dist else -1.0

            # Speed proportional to distance: closer → slower
            speed_factor = (front_dist - DANGER_STOP) / (DANGER_TURN - DANGER_STOP)
            speed_factor = float(np.clip(speed_factor, 0.0, 1.0))
            fwd_speed    = SLOW_SPEED * speed_factor
            turn_amount  = MAX_TURN_BIAS * abs(turn_bias)

            if turn_bias > 0:           # turn left
                L = fwd_speed - turn_amount
                R = fwd_speed + turn_amount
            else:                       # turn right
                L = fwd_speed + turn_amount
                R = fwd_speed - turn_amount

            L = float(np.clip(L, -1.0, 1.0))
            R = float(np.clip(R, -1.0, 1.0))

            logger.debug(
                "[LidarAvoider] EVADE  bias=%.2f  L=%.2f R=%.2f", turn_bias, L, R)
            self._send_diff(L, R)
            return

        # --- DANGER_SLOW: slow down ---
        if front_dist < DANGER_SLOW:
            self._state = self.SLOW

            speed_factor = (front_dist - DANGER_TURN) / (DANGER_SLOW - DANGER_TURN)
            speed_factor = float(np.clip(speed_factor, 0.0, 1.0))
            fwd_speed    = SLOW_SPEED + (CRUISE_SPEED - SLOW_SPEED) * speed_factor

            # Gentle steering bias even in slow zone
            turn_bias   = weighted_turn_direction(angles, distances)
            turn_amount = MAX_TURN_BIAS * 0.4 * abs(turn_bias)

            if turn_bias > 0:
                L = fwd_speed - turn_amount
                R = fwd_speed + turn_amount
            else:
                L = fwd_speed + turn_amount
                R = fwd_speed - turn_amount

            L = float(np.clip(L, 0.0, 1.0))
            R = float(np.clip(R, 0.0, 1.0))

            self._send_diff(L, R)
            return

        # --- Clear path: cruise ---
        self._state = self.CRUISE
        self._send_diff(CRUISE_SPEED, CRUISE_SPEED)

    # ── manoeuvre helpers ───────────────────────

    def _sleep_interruptible(self, seconds):
        """Sleep in short slices, aborting early when paused or stopped."""
        end = time.time() + seconds
        while time.time() < end:
            if not self._active or self._stop_evt.is_set():
                return False
            time.sleep(min(0.1, end - time.time()))
        return True

    def _execute_reverse_and_turn(self, turn_bias, rear_dist):
        """
        Back up for REVERSE_DURATION then spin for TURN_DURATION.
        Runs in-thread (blocks the avoidance loop for the duration).
        rear_dist guards against backing into a rear obstacle.
        Aborts immediately (and halts) if avoidance is paused or stopped.
        """
        # --- Phase 1: reverse ---
        rev_spd = REVERSE_SPEED
        if rear_dist < DANGER_STOP:
            # Can't back up safely either – just spin in place
            rev_spd = 0.0

        if rev_spd != 0.0:
            self._send_diff(rev_spd, rev_spd)
            if not self._sleep_interruptible(REVERSE_DURATION):
                self._send_stop()
                return

        # --- Phase 2: turn in place ---
        if turn_bias > 0:          # turn left: right wheel fwd, left wheel back
            L =  SLOW_SPEED
            R = -SLOW_SPEED
        else:                      # turn right
            L = -SLOW_SPEED
            R =  SLOW_SPEED

        self._send_diff(L, R)
        if not self._sleep_interruptible(TURN_DURATION):
            self._send_stop()
            return

        # --- Phase 3: stop and start fresh ---
        self._send_stop()
        self._cooldown_until = time.time() + 0.3   # 300 ms cooldown

    # ── motor command wrappers ──────────────────

    def _send_diff(self, L, R):
        """
        Send a differential-drive command.
        Skips the serial write when nothing has changed (reduces bus traffic).
        """
        L = round(L, 3)
        R = round(R, 3)
        if L == self._last_L and R == self._last_R:
            return
        self._last_L = L
        self._last_R = R

        if self._use_omni:
            # Omni / mecanum: convert L/R to X (fwd) and Z (turn)
            X = (L + R) / 2.0
            Z = (R - L) / 2.0
            self._base.base_json_ctrl({"T": CMD_OMNI, "X": X, "Z": Z})
        else:
            self._base.base_json_ctrl({"T": CMD_MOVE, "L": L, "R": R})

    def _send_stop(self):
        self._last_L = 0.0
        self._last_R = 0.0
        if self._use_omni:
            self._base.base_json_ctrl({"T": CMD_OMNI, "X": 0, "Z": 0})
        else:
            self._base.base_json_ctrl({"T": CMD_MOVE, "L": 0, "R": 0})


# ─────────────────────────────────────────────
#  Convenience: patch into the base_data_loop
#  already running in app.py
# ─────────────────────────────────────────────

def patch_base_data_loop(base, avoider):
    """
    Call this instead of defining base_data_loop in app.py when you want
    the avoider to react on every fresh LIDAR frame rather than on a fixed
    timer.  This is optional – the avoider's own thread works independently.

    Usage in app.py:
        import lidar_avoidance
        avoider = lidar_avoidance.LidarAvoider(base)
        avoider.start()
        # optionally:
        # lidar_avoidance.patch_base_data_loop(base, avoider)
    """
    import threading, time

    def _loop():
        while True:
            if base.use_lidar:
                base.rl.lidar_data_recv()   # blocks until one full rotation
                # avoider picks up the new data on its next tick automatically

            if base.extra_sensor:
                base.rl.read_sensor_data()

            time.sleep(0.025)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    return t
