"""self_drive.py — the self-drive planner thread.

This module owns the thread lifecycle (start/stop/pause/resume and the
composite transitions enable/disable/pursue/warm), one planning tick, the
heading choice, and the status payload. Everything it needs has a module of
its own:

    perception.py        robot-frame conventions + pure scan helpers
    robot_state.py       live LIDAR scan + ESP32 wheel odometry
    spatial_memory.py    learned occupancy grid + object memory (surroundings.json)
    detection_source.py  live detections + throttled open-vocabulary top-up
    target_pursuit.py    what object is being chased + the pursuit rules

Where a change lands
    a new sensor reading        -> robot_state.py
    an angle/bearing convention -> perception.py (the only place either lives)
    what the robot remembers    -> spatial_memory.py
    which detections it sees    -> detection_source.py
    the target's state/rules    -> target_pursuit.py
    the heading that gets picked, the veto, the executor contract
                                -> SelfDriver._choose_heading / _tick (here)

The planner never writes wheel commands. It publishes suggested_turn (-1..1,
+ = left) and halt; app.LidarAvoider remains the executor and its emergency
states (SLOW/EVADE/REVERSE) stay authoritative, as does this module's refusal
to drive forward with something inside TOO_CLOSE_MM.

A surfaced detail: pending-halt. When the object is reached the planner sets
halt so the executor stops; that is the only way it can stop the robot, and
the avoider is free to override it (which is what safety wants).
"""

import math
import threading
import time

from detection_source import DetectionSource
from perception import arc_clearance
from robot_state import LidarScan, wheel_odometry
from spatial_memory import MEM_VERSION, SpatialMemory          # re-exported
from target_pursuit import PursuitPolicy, Target

# ── planner tunables ──────────────────────────────────────────────────────────
HEADINGS      = [0, 15, -15, 30, -30, 45, -45, 60, -60, 80, -80, 110, -110]
LOOP_HZ       = 7.0
SAVE_INTERVAL = 60.0        # seconds between auto-saves while active
TOO_CLOSE_MM  = 250         # inside this the planner refuses to drive forward
FRONT_CONE_DEG = 45         # safety cone for TOO_CLOSE_MM
OBJECT_CONE_DEG = 35       # front sector a detection is ranged with for memory
                           # (the *arrival* range follows the object's own
                           # bearing — see target_pursuit.TARGET_CONE_DEG)
VETO_HALF_WIDTH = 0.4      # rad — live arc sampled per candidate heading

# heading score weights (mirror the desktop AutoPilot, plus object avoidance)
W_LIDAR = 2.0
W_MEM   = 1.2
W_GOAL  = 0.6


class SelfDriver:
    """Planner thread: learns surroundings, picks a cruise or pursuit heading."""

    def __init__(self, base, cvf, memory=None, detections=None, policy=None):
        self._base = base
        self._cvf = cvf
        self.memory = memory if memory is not None else SpatialMemory()
        self.detections = detections if detections is not None \
            else DetectionSource(cvf)
        self.policy = policy if policy is not None else PursuitPolicy()
        self.target = Target()

        self._active = False
        self._stop_evt = threading.Event()
        self._thread = None
        self._last_save = time.time()

        self.suggested_turn = 0.0   # -1..1, + = left (avoider convention)
        self.halt = False           # executor hint: stop the wheels now
        self.last_scores = []       # [(deg, score)] for the UI
        self.last_decision = "off"

    # ── lifecycle (the only way the thread and its flags change) ──────────
    def warm(self):
        """Boot state: the thread exists but the planner stays idle."""
        self.start()
        self.pause(save=False)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_evt.clear()
        self._active = True
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="self-drive")
        self._thread.start()

    def stop(self):
        self._active = False
        self.suggested_turn = 0.0
        self.halt = False
        self.last_decision = "off"
        self._stop_evt.set()
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        self._thread = None

    def pause(self, save=True):
        self._active = False
        self.suggested_turn = 0.0
        self.halt = False
        self.last_decision = "paused"
        if save:
            self.memory.save()

    def resume(self):
        # A resume after stop() must bring the thread back: the /selfdrive
        # routes and app.py's watchdog both call this on a planner that may
        # have been stopped, and without it the planner would stay dead while
        # claiming to be active.
        if not (self._thread and self._thread.is_alive()):
            self.start()
        self._active = True
        self.halt = False
        self.last_decision = (f"looking for {self.target.name}" if self.target.name
                              else "planning")

    def enable(self):
        """Turn driving on (keeps any current target)."""
        self.resume()

    def disable(self, save=True):
        """Turn driving off and drop the chase: the composite every caller wants."""
        self.pause(save=save)
        self.target.clear()
        self.stop()

    def pursue(self, name):
        """Drive toward one named object; False if the name is blank."""
        if not self.target.set(name, memory=self.memory):
            return False
        self.enable()
        return True

    def clear_target(self):
        self.target.clear()

    # ── memory shortcuts (the map's owner is SpatialMemory) ───────────────
    def save_memory(self):
        return self.memory.save()

    def load_memory(self):
        return self.memory.load()

    def clear_memory(self):
        return self.memory.clear()

    @property
    def active(self):
        return self._active

    # ── reporting ─────────────────────────────────────────────────────────
    def status(self):
        scan = LidarScan.read(self._base)
        return {
            'active': self._active,
            'suggested_turn': round(self.suggested_turn, 3),
            'front_mm': scan.front_min_mm(FRONT_CONE_DEG),
            'halt': self.halt,
            'wheels': wheel_odometry(self._base),
            'decision': self.last_decision,
            'busy_cells': self.memory.busy_cells,
            'objects': self.memory.objects[-20:][::-1],
            'scores': self.last_scores,
            'target': self.target.status(),
        }

    # ── planning ──────────────────────────────────────────────────────────
    def _loop(self):
        interval = 1.0 / LOOP_HZ
        while not self._stop_evt.is_set():
            t0 = time.time()
            if self._active:
                try:
                    self._tick()
                except Exception as e:
                    print(f"[planner] tick error: {e}")
                if time.time() - self._last_save > SAVE_INTERVAL:
                    self.memory.save()
                    self._last_save = time.time()
            time.sleep(max(0.0, interval - (time.time() - t0)))

    def _tick(self):
        """One planning step: read, learn, then decide (safety first)."""
        scan = LidarScan.read(self._base)
        if scan.empty:
            # No scan means no cruise: the avoider goes IDLE without angles, so
            # nothing needs stopping here — just refuse to suggest a heading.
            self._hold("no lidar data", stop=False)
            return
        self.memory.observe_lidar(scan.angles, scan.distances)
        dets = self.detections.for_target(self.target.name)
        self.memory.observe_detections(dets, self._object_range_m(scan))

        front = scan.front_min_mm(FRONT_CONE_DEG)
        if front is not None and front < TOO_CLOSE_MM:
            # The avoider's emergency states own anything this close, and the
            # planner also refuses to drive forward, so a CRUISE state can
            # never push the robot into a <250 mm obstacle.
            self._hold(f"too close {front/1000:.2f}m — avoider owns it")
            return

        self.target.observe(dets, scan)
        if self.policy.arrival_hold(self.target):
            self.target.mark_arrived()
            self._hold(f"arrived at {self.target.name} "
                       f"({self.target.range_m:.2f}m) — stopped")
            return

        self._choose_heading(scan)

    def _choose_heading(self, scan):
        """Pick the heading to suggest — the one place heading policy lives."""
        target, policy = self.target, self.policy
        pursuing = target.name is not None
        bearing = target.aim_bearing          # None when not in view
        self.halt = False

        best, best_score, scores = 0.0, float('-inf'), []
        for heading in HEADINGS:
            heading_rad = math.radians(heading)
            lidar_clear = arc_clearance(scan.angles, scan.distances, heading_rad,
                                        VETO_HALF_WIDTH)
            mem_clear = self.memory.clearance(heading_rad, 1.1)
            if pursuing and lidar_clear < policy.veto_clear:
                scores.append((heading, None))   # live obstacle in the way
                continue
            goal_term = policy.goal_term(heading, bearing)
            if goal_term is None:
                goal, weight = -abs(heading) / 180.0, W_GOAL  # prefer straight
            else:
                goal, weight = goal_term
            score = W_LIDAR * lidar_clear + W_MEM * mem_clear + weight * goal
            scores.append((heading, round(score, 3)))
            if score > best_score:
                best_score, best = score, float(heading)
        self.last_scores = scores

        if best_score == float('-inf'):
            # Every heading is blocked right now — hold still and let the
            # avoider's emergency states work it out.
            self._hold("surrounded — holding position")
            return

        self.suggested_turn = float(max(-1.0, min(1.0, best / 90.0)))

        if pursuing and bearing is None:
            self.suggested_turn = target.next_scan_turn()
            self.last_decision = (f"looking for {target.name} — sweeping "
                                  f"{'left' if self.suggested_turn > 0 else 'right'} "
                                  f"cells {self.memory.busy_cells} "
                                  f"objs {len(self.memory.objects)}")
            return

        if pursuing and policy.aim_clear(scan, bearing):
            self.suggested_turn = policy.aim_turn(bearing)
            self.last_decision = (f"approaching {target.name} "
                                  f"bearing {bearing:+.0f}° "
                                  f"range {target.range_m:.2f}m "
                                  f"turn {self.suggested_turn:+.2f}")
            return

        if pursuing:
            self.last_decision = (f"approaching {target.name} "
                                  f"bearing {bearing:+.0f}° "
                                  f"range {target.range_m:.2f}m "
                                  f"heading {best:+.0f}° "
                                  f"turn {self.suggested_turn:+.2f} "
                                  f"(going around)")
            return

        self.last_decision = (f"heading {best:+.0f}° turn {self.suggested_turn:+.2f} "
                             f"cells {self.memory.busy_cells} "
                             f"objs {len(self.memory.objects)}")

    def _hold(self, decision, stop=True):
        """Stop suggesting motion (empty scan, too close, arrived, surrounded).

        `stop` asks the executor to halt the wheels; it is the only way the
        planner can stop the robot, because the avoider owns the motors.
        """
        self.suggested_turn = 0.0
        self.halt = stop
        self.last_decision = decision

    def _object_range_m(self, scan):
        """Range to attribute to a camera object: the front LIDAR sector."""
        front = scan.front_min_mm(OBJECT_CONE_DEG)
        range_m = (front / 1000.0) if front else 3.0
        return max(0.2, min(range_m, 3.0))
