"""spatial_memory.py — what the robot has learned about its surroundings.

Single owner of the learned map:

  * an egocentric occupancy grid (robot frame, +y forward) built from LIDAR
    rays; static hits accumulate counts and decay when stale, so a wall the
    robot saw a minute ago still steers it;
  * a camera-object memory: each detection gets a bearing (perception) and a
    range from the front LIDAR sector — a single camera has no depth of its
    own — and close objects are fused into the grid as small occupied disks so
    walls and objects share one avoidance model;
  * persistence, in surroundings.json next to the app.

There is no odometry, so the map is egocentric and revisiting a spot
re-anchors it. Angles passed in here are always already in the robot frame
(see robot_state.LidarScan).
"""

import json
import math
import os
import threading
import time

from perception import box_bearing_deg, names_match

MEM_VERSION = 2          # bumped when the lidar frame convention changed
                         # (v1 maps were rotated 180°) — an old file is ignored
                         # so the robot relearns instead of driving on a
                         # mirrored picture of the room

GRID_SIZE    = 121       # cells per side (±6 m at 10 cm)
CELL_M       = 0.10      # metres per cell
MIN_HITS     = 3         # hits before a cell counts as blocked
DECAY_SEC    = 30.0      # stale cells lose a hit after this long
OBJ_RANGE_MAX = 3.0      # metres — objects beyond this are remembered, not avoided
OBJ_GRID_R   = 0.18      # metres — fused disk radius for an object in the grid
OBJ_DEDUPE_M = 0.5       # metres — merge a sighting into a known object within this
DET_MIN_CONF = 0.30      # ignore camera boxes below this confidence


class SpatialMemory:
    """Occupancy grid (robot frame) + camera-object memory, persisted."""

    def __init__(self, path=None):
        self._hits = [[0] * GRID_SIZE for _ in range(GRID_SIZE)]
        self._last = [[0.0] * GRID_SIZE for _ in range(GRID_SIZE)]
        self.objects = []          # [{'name','bearing_deg','range_m','confidence','t'}]
        self._lock = threading.Lock()
        self.path = path
        self.load()

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

    def find_object(self, name):
        """Most recent remembered sighting of `name`, or None."""
        with self._lock:
            best = None
            for obj in self.objects:
                if names_match(obj.get('name', ''), name):
                    if best is None or obj.get('t', 0) > best.get('t', 0):
                        best = obj
            return dict(best) if best else None

    # ── learning ──────────────────────────────────────────────────────────
    def observe_lidar(self, angles, distances, range_m=6.0):
        """Feed one scan (angles already in the robot frame)."""
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
        """Fuse one sighting into the object memory + grid."""
        now = time.time()
        with self._lock:
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

    def observe_detections(self, dets, front_range_m, min_conf=DET_MIN_CONF):
        """Fuse a batch of camera detections seen from `front_range_m`."""
        for det in dets or []:
            name = det.get('name', '')
            box = det.get('box')
            confidence = float(det.get('confidence', 0.0))
            if not name or not box or confidence < min_conf:
                continue
            bearing = box_bearing_deg(box)
            self.observe_object(name, round(bearing, 1), round(front_range_m, 2),
                                confidence)

    # ── persistence ───────────────────────────────────────────────────────
    def load(self):
        if not self.path or not os.path.exists(self.path):
            return False
        try:
            with open(self.path, 'r', encoding='utf-8') as fh:
                data = json.load(fh)
            if data.get('version') != MEM_VERSION:
                print("[memory] surroundings memory predates the corrected "
                      "lidar frame — relearning from scratch")
                return False
            with self._lock:
                self._hits = data.get('grid', self._hits)
                self.objects = data.get('objects', [])
            print("[memory] loaded surroundings memory: "
                  f"{self.busy_cells} busy cells, {len(self.objects)} objects")
            return True
        except Exception as e:
            print(f"[memory] failed to load {self.path}: {e}")
            return False

    # Back-compat alias: older call sites used the private name.
    _load = load

    def save(self):
        if not self.path:
            return False
        try:
            with self._lock:
                payload = {'version': MEM_VERSION, 'grid': self._hits,
                           'objects': self.objects}
            tmp = self.path + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as fh:
                json.dump(payload, fh)
            os.replace(tmp, self.path)
            print(f"[memory] saved surroundings memory: "
                  f"{self.busy_cells} busy cells, {len(self.objects)} objects")
            return True
        except Exception as e:
            print(f"[memory] save failed: {e}")
            return False

    def clear(self):
        with self._lock:
            self._hits = [[0] * GRID_SIZE for _ in range(GRID_SIZE)]
            self._last = [[0.0] * GRID_SIZE for _ in range(GRID_SIZE)]
            self.objects = []
        print("[memory] surroundings memory cleared")
        return True
