"""target_pursuit.py — the object the robot is driving toward.

Two things live here, and nothing else does:

  * Target — the state of the chase: which object, whether the camera can see
    it, where it is (bearing, range), and whether the executor should stop
    (`halt`). set()/clear()/observe() are the only ways that state changes, so
    "why is it not moving" has one place to look.

  * PursuitPolicy — the rules for steering at it: when the object counts as
    arrived, whether the direction to it is clear enough to aim down, how hard
    to turn toward it, and how to sweep when it is not in view. The heading
    scoring loop that consumes these lives in self_drive.SelfDriver, which is
    therefore the one obvious place where a change to pursuit *scoring* lands
    (this module owns pursuit *rules*, self_drive owns heading choice).

Range comes from the LIDAR arc around the object's own bearing
(TARGET_CONE_DEG), not from the whole forward cone: a single camera has no
depth of its own, and the forward cone used to measure whatever was nearest
in front of the robot — so a wall beside the object ended the approach at the
wall's distance and the robot stopped short of the thing it was told to reach.
The arc still refuses to drive *through* a wall, and the avoider's own
forward-cone states own collision avoidance independently of this estimate.
"""

import math
import time

from perception import arc_clearance, box_bearing_deg, names_match, sector_min

# ── target tunables ───────────────────────────────────────────────────────────
DET_MIN_CONF = 0.30      # a sighting below this confidence is not a sighting
OBJ_RANGE_MAX = 3.0      # m — clamp: beyond this the robot only remembers it
TARGET_CONE_DEG = 10.0   # LIDAR arc around the object's bearing = its range
LOST_S       = 2.0       # no sighting for this long => the object is not in view
REMEMBER_S   = 90.0      # use a remembered bearing for this long when searching
SCAN_TURN    = 0.45      # sweep strength while searching
SCAN_FLIP_S  = 8.0       # flip the sweep direction this often (don't circle)

# ── pursuit rules ─────────────────────────────────────────────────────────────
ARRIVE_M      = 0.6      # close enough: ask the executor to stop
AIM_HALF_RAD  = 0.25     # arc sampled down the bearing to the object
VETO_CLEAR    = 0.5      # that arc must be at least this clear to aim directly
W_TARGET      = 2.4      # heading-score bias toward the object's bearing
AIM_FULL_DEG  = 45.0     # bearing that maps to a full-lock turn


class Target:
    """The object being pursued, and how the chase is going."""

    IDLE, SEEKING, APPROACHING, ARRIVED = 'idle', 'seeking', 'approaching', 'arrived'

    def __init__(self):
        self.name = None
        self.state = self.IDLE
        self.bearing_deg = None
        self.range_m = None
        self.halt = False
        self._seen_t = 0.0
        self.last_seen = None       # last sighting even if stale (search aim)
        self._scan_dir = 1.0
        self._scan_flip_t = 0.0

    # ── lifecycle ─────────────────────────────────────────────────────────
    def set(self, name, memory=None):
        """Start pursuing `name`. Returns False for a blank name."""
        name = (name or "").strip().lower()
        if not name:
            return False
        self.name = name
        self.state = self.SEEKING
        self.bearing_deg = None
        self.range_m = None
        self.halt = False
        self._seen_t = 0.0
        self.last_seen = None
        # Aim the first sweep toward where this object was last seen, which is
        # much faster than sweeping blind from straight ahead.
        remembered = memory.find_object(name) if memory is not None else None
        if remembered and (time.time() - remembered.get('t', 0)) < REMEMBER_S:
            self.last_seen = remembered
            self._scan_dir = 1.0 if remembered.get('bearing_deg', 0) >= 0 else -1.0
        self._scan_flip_t = time.time()
        print(f"[pursuit] target set: {name}")
        return True

    def clear(self):
        if self.name:
            print(f"[pursuit] target cleared: {self.name}")
        self.name = None
        self.state = self.IDLE
        self.bearing_deg = None
        self.range_m = None
        self.last_seen = None
        self.halt = False

    # ── observation ───────────────────────────────────────────────────────
    def observe(self, dets, scan, now=None):
        """Refresh bearing/range from the newest detections.

        Bearing comes from the box centre (perception.box_bearing_deg); range
        is the nearest LIDAR return within TARGET_CONE_DEG of that bearing.
        """
        if not self.name:
            return
        now = time.time() if now is None else now
        best = None
        for det in dets or []:
            box = det.get('box')
            confidence = float(det.get('confidence', 0.0))
            if not box or confidence < DET_MIN_CONF:
                continue
            if not names_match(det.get('name', ''), self.name):
                continue
            bearing = box_bearing_deg(box)
            # Prefer the sighting nearest the centre of the view, then the
            # most confident one: with two chairs on screen, drive at the one
            # it is already roughly facing.
            key = (abs(bearing), -confidence)
            if best is None or key < best[0]:
                best = (key, str(det.get('name', '')), bearing)
        if best is None:
            if self.state == self.APPROACHING and now - self._seen_t > LOST_S:
                self.state = self.SEEKING
            return
        _, name, bearing = best
        # Nothing back down the bearing (a person, a thin-legged chair) counts
        # as far away rather than near: falling back to the forward cone here
        # would resurrect the wall-measured arrival this replaced, and the
        # avoider still stops the robot at anything physically in front of it.
        got = sector_min(scan.angles, scan.distances, bearing, TARGET_CONE_DEG)
        range_m = got / 1000.0 if got != float('inf') else OBJ_RANGE_MAX
        self.bearing_deg = round(bearing, 1)
        self.range_m = round(max(0.2, min(range_m, OBJ_RANGE_MAX)), 2)
        self._seen_t = now
        self.state = self.APPROACHING
        self.last_seen = {'name': name, 'bearing_deg': self.bearing_deg,
                          'range_m': self.range_m, 't': now}

    def mark_arrived(self):
        self.state = self.ARRIVED
        self.halt = True

    @property
    def in_view(self):
        return (time.time() - self._seen_t) < LOST_S

    @property
    def aim_bearing(self):
        """Bearing to steer at, or None when the object is not in view."""
        return self.bearing_deg if self.state == self.APPROACHING else None

    def next_scan_turn(self, now=None):
        """Sweep strength while searching, flipping direction periodically."""
        now = time.time() if now is None else now
        if now - self._scan_flip_t > SCAN_FLIP_S:
            self._scan_flip_t = now
            self._scan_dir = -self._scan_dir
        return SCAN_TURN * self._scan_dir

    def status(self):
        """Public shape of the chase (None when nothing is being pursued)."""
        if not self.name:
            return None
        return {'name': self.name, 'state': self.state,
                'bearing_deg': self.bearing_deg, 'range_m': self.range_m,
                'seen': self.in_view, 'halt': self.halt}


class PursuitPolicy:
    """The rules for driving at a Target. Stateless; safe to share."""

    arrive_m = ARRIVE_M
    veto_clear = VETO_CLEAR
    aim_half_rad = AIM_HALF_RAD
    w_target = W_TARGET
    aim_full_deg = AIM_FULL_DEG

    def arrival_hold(self, target):
        """Should the wheels stay stopped because the chase is finished?

        Covers both arriving and staying arrived. Arrival is sticky: the tick
        that first reaches the object marks it arrived, and every tick after
        must keep holding too — including the ones where the object has slipped
        out of the camera view, which is what happens once the robot is on top
        of it. Re-deciding arrival from scratch each tick released halt the
        moment the object left the frame, so the robot drove off again having
        already reached its target. The range may be a nearer wall — stopping
        early is the safe direction.
        """
        if target.state == Target.ARRIVED:
            return True
        return (target.state == Target.APPROACHING
                and target.range_m is not None
                and target.range_m <= self.arrive_m)

    def aim_clear(self, scan, bearing_deg):
        """Is the arc down the bearing to the object clear enough to aim at?"""
        return arc_clearance(scan.angles, scan.distances,
                             math.radians(bearing_deg), self.aim_half_rad) \
            >= self.veto_clear

    def aim_turn(self, bearing_deg):
        """Proportional turn toward the object, full lock at +/-aim_full_deg.

        Aiming at the exact bearing matters: with a target a couple of degrees
        off centre the discrete heading set ties (cos(+15-b) == cos(-15-b)),
        and snapping to it made the wheels alternate every tick.
        """
        return max(-1.0, min(1.0, bearing_deg / self.aim_full_deg))

    def goal_term(self, heading_deg, bearing_deg):
        """(goal, weight) pull toward the object's bearing.

        None when there is no target in view, so the planner applies its own
        'prefer straight ahead' bias — the cruise weight belongs to the
        planner, not to pursuit.
        """
        if bearing_deg is None:
            return None
        return math.cos(math.radians(heading_deg - bearing_deg)), self.w_target
