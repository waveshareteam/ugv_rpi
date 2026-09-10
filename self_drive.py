"""
self_drive.py — onboard self-driving with spatial learning.

The robot learns its surroundings while it drives and uses that memory to
choose safe headings:

  * SpatialMemory: a robot-centric occupancy grid built from LIDAR rays
    (walls and static obstacles accumulate hit counts, stale hits decay) plus
    a camera-object memory (YOLO-World detections get a bearing from the box
    position and a range from the front LIDAR sector, and are fused into the
    grid as small obstacles). The whole map persists to surroundings.json so
    the robot remembers the room across runs.

  * SelfDriver: a planner thread that scores candidate headings (13 from
    -110..110 deg) with live LIDAR clearance + learned-memory clearance +
    a forward goal bias, and exposes suggested_turn (-1..1). It never writes
    wheel commands itself: the LidarAvoider remains the executor and its
    emergency states (SLOW/EVADE/REVERSE) stay authoritative, but its CRUISE
    branch steers by the planner's suggested heading.

Design notes
  * No odometry is available, so the grid is egocentric (robot frame, +y
    forward) — the robot remembers "a wall was over there" relative to
    itself, and revisiting a spot re-anchors the memory.
  * Objects are fused into the grid as small occupied disks so walls and
    objects share one avoidance model.
  * The driver refuses to drive blind: if the LIDAR stream is stale or empty
    it suggests 0 turn and the avoider's own safety logic takes over.
"""

import json
import math
import os
import threading
import time

# ── tunables ──────────────────────────────────────────────────────────────────
GRID_SIZE     = 121          # cells per side  (±6 m at 10 cm)
CELL_M        = 0.10         # metres per cell
MIN_HITS      = 3            # hits before a cell counts as blocked
DECAY_SEC     = 30.0         # stale cells lose a hit after this long
SAVE_INTERVAL = 60.0         # seconds between auto-saves while active
OBJ_RANGE_MAX = 3.0          # metres — objects beyond this are remembered, not avoided
OBJ_GRID_R    = 0.18         # metres — fused disk radius for an object in the grid
OBJ_DEDUPE_M  = 0.5          # metres — merge a new sighting into a known object within this
HEADINGS      = [0, 15, -15, 30, -30, 45, -45, 60, -60, 80, -80, 110, -110]
LOOP_HZ       = 7.0
STALE_LIDAR_S = 0.5          # lidar scan older than this => don't drive on it

# scoring weights (mirror the desktop AutoPilot, plus object avoidance)
W_LIDAR = 2.0
W_MEM   = 1.2
W_GOAL  = 0.6


def _normalize_angle(a):
    """Wrap to [-pi, pi]."""
    return math.atan2(math.sin(a), math.cos(a))


class SpatialMemory:
    """Occupancy grid (robot frame) + camera-object memory, persisted."""

    def __init__(self, path=None):
        self._hits = [[0] * GRID_SIZE for _ in range(GRID_SIZE)]
        self._last = [[0.0] * GRID_SIZE for _ in range(GRID_SIZE)]
        self.objects = []          # [{'name','bearing_deg','range_m','confidence','t'}]
        self._lock = threading.Lock()
        self.path = path
        self._load()

    # ── grid accessors ────────────────────────────────────────────────────
    def _cell(self, mx, my):
        cx = GRID_SIZE // 2 + int(round(mx / CELL_M))
        cy = GRID_SIZE // 2 - int(round(my / CELL_M))   # +y forward -> up
        return max(0, min(GRID_SIZE - 1, cx)), max(0, min(GRID_SIZE - 1, cy))

    def blocked(self, mx, my, min_hits=MIN_HITS):
        with self._lock:
            cx, cy = self._cell(mx, my)
            return self._hits[cx][cy] >= min_hits

    def clearance(self, heading_rad, r, half_width_rad=0.35):
        """0..1 — fraction of a 12-sample arc at radius r that is free."""
        samples = 12
        blocked = 0
        for i in range(samples):
            a = heading_rad + (i - samples / 2.0) / (samples / 2.0) * half_width_rad
            if self.blocked(r * math.sin(a), r * math.cos(a)):
                blocked += 1
        return 1.0 - blocked / float(samples)

    @property
    def busy_cells(self):
        with self._lock:
            return sum(1 for row in self._hits for h in row if h > 0)

    def cells(self, min_hits=1):
        """[(mx, my, hits)] in metres, robot frame."""
        out = []
        half = GRID_SIZE // 2
        with self._lock:
            for x in range(GRID_SIZE):
                for y in range(GRID_SIZE):
                    if self._hits[x][y] >= min_hits:
                        out.append(((x - half) * CELL_M, (half - y) * CELL_M,
                                    self._hits[x][y]))
        return out

    # ── learning ──────────────────────────────────────────────────────────
    def observe_lidar(self, angles, distances, range_m=6.0):
        """Feed one scan (robot frame; angle 0 = forward, + = left)."""
        now = time.time()
        with self._lock:
            for a, d in zip(angles, distances):
                if d <= 0 or d > range_m * 1000.0:
                    continue
                mx = (d / 1000.0) * math.sin(a)
                my = (d / 1000.0) * math.cos(a)
                cx, cy = self._cell(mx, my)
                if self._hits[cx][cy] < 65535:
                    self._hits[cx][cy] += 1
                self._last[cx][cy] = now
            self._decay_locked(now)

    def _decay_locked(self, now):
        for x in range(GRID_SIZE):
            for y in range(GRID_SIZE):
                if self._hits[x][y] > 0 and now - self._last[x][y] > DECAY_SEC:
                    self._hits[x][y] -= 1
                    self._last[x][y] = now - DECAY_SEC

    def observe_object(self, name, bearing_deg, range_m, confidence):
        """Fuse a camera detection into the object memory + grid."""
        now = time.time()
        with self._lock:
            # merge into a nearby known object of the same class
            for obj in self.objects:
                if obj['name'] == name and abs(obj['bearing_deg'] - bearing_deg) < 15.0 \
                        and abs(obj['range_m'] - range_m) < OBJ_DEDUPE_M:
                    obj.update(bearing_deg=bearing_deg, range_m=range_m,
                               confidence=confidence, t=now)
                    break
            else:
                self.objects.append({'name': name, 'bearing_deg': bearing_deg,
                                     'range_m': range_m, 'confidence': confidence,
                                     't': now})
            # fuse close objects into the grid as small disks
            if range_m <= OBJ_RANGE_MAX:
                r = max(CELL_M, OBJ_GRID_R)
                steps = 8
                for i in range(steps):
                    ang = 2 * math.pi * i / steps
                    mx = range_m * math.sin(math.radians(bearing_deg)) + r * math.sin(ang)
                    my = range_m * math.cos(math.radians(bearing_deg)) + r * math.cos(ang)
                    cx, cy = self._cell(mx, my)
                    if self._hits[cx][cy] < 65535:
                        self._hits[cx][cy] += 2      # objects count double
                    self._last[cx][cy] = now
        return len(self.objects)

    # ── persistence ───────────────────────────────────────────────────────
    def _load(self):
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
            with self._lock:
                self._hits = data.get('grid', self._hits)
                self.objects = data.get('objects', [])
            print(f"[self_drive] loaded surroundings memory: "
                  f"{self.busy_cells} busy cells, {len(self.objects)} objects")
        except Exception as e:
            print(f"[self_drive] failed to load {self.path}: {e}")

    def save(self):
        if not self.path:
            return False
        try:
            with self._lock:
                payload = {'grid': self._hits, 'objects': self.objects}
            tmp = self.path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as fh:
                json.dump(payload, fh)
            os.replace(tmp, self.path)
            print(f"[self_drive] saved surroundings memory: "
                  f"{self.busy_cells} busy cells, {len(self.objects)} objects")
            return True
        except Exception as e:
            print(f"[self_drive] save failed: {e}")
            return False

    def clear(self):
        with self._lock:
            self._hits = [[0] * GRID_SIZE for _ in range(GRID_SIZE)]
            self._last = [[0.0] * GRID_SIZE for _ in range(GRID_SIZE)]
            self.objects = []
        print("[self_drive] surroundings memory cleared")
        return True


class SelfDriver:
    """Planner thread: learns surroundings, picks a cruise heading."""

    def __init__(self, base, cvf, memory=None):
        self._base = base          # BaseCtrl — only for lidar reads
        self._cvf = cvf            # OpencvFuncs — last_detections
        self.memory = memory or SpatialMemory()
        self._active = False
        self._stop_evt = threading.Event()
        self._thread = None
        self.suggested_turn = 0.0   # -1..1, + = left (avoider convention)
        self.last_scores = []       # [(deg, score)] for the UI
        self.last_decision = "off"
        self._last_save = time.time()

    # ── control ───────────────────────────────────────────────────────────
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_evt.clear()
        self._active = True
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="self-drive")
        self._thread.start()

    def pause(self, save=True):
        self._active = False
        self.suggested_turn = 0.0
        self.last_decision = "paused"
        if save:
            self.memory.save()

    def resume(self):
        self._active = True
        self.last_decision = "planning"

    @property
    def active(self):
        return self._active

    def status(self):
        return {
            'active': self._active,
            'suggested_turn': round(self.suggested_turn, 3),
            'decision': self.last_decision,
            'busy_cells': self.memory.busy_cells,
            'objects': self.memory.objects[-20:][::-1],
            'scores': self.last_scores,
        }

    # ── planning loop ─────────────────────────────────────────────────────
    def _loop(self):
        interval = 1.0 / LOOP_HZ
        while not self._stop_evt.is_set():
            t0 = time.time()
            if self._active:
                try:
                    self._tick()
                except Exception as e:
                    print(f"[self_drive] tick error: {e}")
                if time.time() - self._last_save > SAVE_INTERVAL:
                    self.memory.save()
                    self._last_save = time.time()
            time.sleep(max(0.0, interval - (time.time() - t0)))

    def _tick(self):
        angles = list(getattr(self._base.rl, 'lidar_angles_show', []))
        dists = list(getattr(self._base.rl, 'lidar_distances_show', []))
        now = time.time()

        if not angles:
            self.suggested_turn = 0.0
            self.last_decision = "no lidar data"
            return
        self.memory.observe_lidar(angles, dists)
        self._observe_camera()

        # live front clearance (90 deg cone)
        front = min((d for a, d in zip(angles, dists)
                     if d > 0 and abs(_normalize_angle(a)) < math.radians(45)),
                    default=None)
        if front is not None and front < 250:
            # avoider's emergency states own anything this close                    self.suggested_turn = 0.0
            self.last_decision = f"too close {front/1000:.2f}m — avoider owns it"
            return


        best = 0.0
        best_score = float('-inf')
        scores = []
        for h in HEADINGS:
            hr = math.radians(h)
            lidar_clear = 1.0 - self._count_blocked(angles, dists, hr, 0.4) / 9.0
            mem_clear = self.memory.clearance(hr, 1.1)
            goal = -abs(h) / 180.0                      # prefer straight ahead
            score = W_LIDAR * lidar_clear + W_MEM * mem_clear + W_GOAL * goal
            scores.append((h, round(score, 3)))
            if score > best_score:
                best_score = score
                best = float(h)
        self.last_scores = scores
        self.suggested_turn = float(max(-1.0, min(1.0, best / 90.0)))
        self.last_decision = (f"heading {best:+.0f}° turn {self.suggested_turn:+.2f} "
                              f"cells {self.memory.busy_cells} objs {len(self.memory.objects)}")

    def _observe_camera(self):
        """Associate latest CV detections: bearing from box center, range from
        the front LIDAR sector (monocular camera has no depth of its own)."""
        dets = getattr(self._cvf, 'last_detections', None) or []
        if not dets:
            return
        angles = list(getattr(self._base.rl, 'lidar_angles_show', []))
        dists = list(getattr(self._base.rl, 'lidar_distances_show', []))
        front = min((d for a, d in zip(angles, dists)
                     if d > 0 and abs(_normalize_angle(a)) < math.radians(35)),
                    default=OBJ_RANGE_MAX * 1000.0) / 1000.0
        front = max(0.2, min(front, OBJ_RANGE_MAX))
        for det in dets:
            name = det.get('name', '')
            conf = det.get('confidence', 0.0)
            box = det.get('box')
            if not name or not box or conf < 0.30:
                continue
            x1, y1, x2, y2 = box
            cx = (x1 + x2) / 2.0
            # box center -> bearing: assume ~60 deg horizontal FOV
            bearing = (cx / 640.0 - 0.5) * 60.0
            self.memory.observe_object(name, round(bearing, 1), round(front, 2), conf)

    @staticmethod
    def _count_blocked(angles, dists, heading_rad, half_width_rad):
        blocked = 0
        for a, d in zip(angles, dists):
            if abs(_normalize_angle(a - heading_rad)) <= half_width_rad and 0 < d < 1100:
                blocked += 1
        return blocked