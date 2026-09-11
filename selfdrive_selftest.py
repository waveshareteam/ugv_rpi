"""Regression harness for the self-drive restructure. Stdlib only.

    python selfdrive_selftest.py

It covers the parts a live run cannot pin down reproducibly:
  0. every *call site* in the refactored modules still matches the signature of
     the function it calls — the restructure moved helpers into perception.py
     and dropped their default arguments, which left app.py's SLOW branch
     calling turn_bias() with two arguments. That raised on every tick, so the
     avoider sent no wheel command in the 450-700 mm band and the exception was
     swallowed by a dead log handler. Nothing caught it until a live run. This
     check does;
  1. the refactored angle math is *numerically identical* to the code it
     replaced (old implementations inlined here verbatim from the previous
     working tree), so app.py's avoider and the planner see the same numbers;
  2. every other behavior the live robot proved, through the public API.
"""
import ast
import importlib
import inspect
import json
import math
import os
import random
import tempfile
import time

import lance
import perception
import spatial_memory
import target_pursuit
from detection_source import DetectionSource
from self_drive import SelfDriver

FAILS = []


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + ("  <- " + str(detail) if detail else ""))
    if not cond:
        FAILS.append(name)


class RL:
    def __init__(self, angles, dists):
        self.lidar_angles_show = angles
        self.lidar_distances_show = dists


class Base:
    def __init__(self, rl, base_data=None):
        self.rl = rl
        self.base_data = base_data or {}


class CV:
    def __init__(self, dets=None, world=None):
        self.last_detections = dets or []
        self._world = world or []
        self.world_calls = 0

    def detect_world(self):
        self.world_calls += 1
        return list(self._world)


def raw(deg_robot):
    """Robot-frame degrees (+ = left) -> the raw value the wire carries."""
    return math.radians(deg_robot) + math.pi


def scan(front_mm=3000, sectors=None):
    sectors = sectors or {}
    angles, dists = [], []
    for d in range(-180, 180):
        angles.append(raw(d))
        dists.append(sectors.get(d, front_mm))
    return angles, dists


def planner(scan_pair=None, dets=None, world=None, base_data=None, mem=None):
    angles, dists = scan_pair or scan()
    cv = CV(dets, world)
    return SelfDriver(Base(RL(angles, dists), base_data),
                      cv, memory=mem or spatial_memory.SpatialMemory()), cv


# ── 0. call sites of every module-level function still match its signature ───
# This is the guard for the bug class the restructure introduced: moving a
# helper and dropping its defaults silently breaks callers that relied on them.
print("--- 0. call-site arity across the refactored modules ---")

MODULES = ["perception", "robot_state", "spatial_memory", "target_pursuit",
           "detection_source", "self_drive", "base_ctrl"]
SOURCES = ["app.py", "lance.py", "cv_ctrl.py", "self_drive.py",
           "spatial_memory.py", "detection_source.py", "robot_state.py",
           "target_pursuit.py", "perception.py"]
mods = {}
for _name in MODULES:
    try:
        mods[_name] = importlib.import_module(_name)
    except Exception as _e:      # e.g. base_ctrl needs pyserial, absent off-Pi
        print("  (not importable here, call sites in it are unchecked: %s: %s)"
              % (_name, _e))

arity_problems, checked = [], 0
for src in SOURCES:
    with open(src, encoding="utf-8") as fh:
        tree = ast.parse(fh.read(), filename=src)
    binds = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in mods:
            for alias in node.names:
                binds[alias.asname or alias.name] = (node.module, alias.name)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or node.keywords:
            continue
        fn = node.func
        if isinstance(fn, ast.Name):
            key = binds.get(fn.id)
        elif isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) \
                and fn.value.id in mods:
            key = (fn.value.id, fn.attr)
        else:
            continue
        if not key:
            continue
        obj = getattr(mods[key[0]], key[1], None)
        if not callable(obj):
            continue
        try:
            params = [p for p in inspect.signature(obj).parameters.values()
                      if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
        except (TypeError, ValueError):
            continue
        required = len([p for p in params if p.default is p.empty])
        checked += 1
        if not required <= len(node.args) <= len(params):
            arity_problems.append("%s:%d %s.%s(%d args, signature wants %d..%d)"
                                  % (src, node.lineno, key[0], key[1],
                                     len(node.args), required, len(params)))
check("every call into a moved module matches its signature (%d call sites)"
      % checked, not arity_problems, "; ".join(arity_problems[:4]))

# ── 0b. the executor consults the planner's halt before it moves forward ─────
# app.py cannot be imported off the Pi (it boots Flask and opens hardware), so
# this is asserted from its syntax tree: in LidarAvoider._decide the planner's
# halt must be checked before any wheel command, because that is exactly what
# went wrong — halt was honored in CRUISE alone, so the 450-700 mm SLOW band
# kept driving the robot on after the planner had said to stop.
print("--- 0b. executor: halt precedes every forward command ---")
app_tree = ast.parse(open("app.py", encoding="utf-8").read(), filename="app.py")
avoider = next(n for n in ast.walk(app_tree)
               if isinstance(n, ast.ClassDef) and n.name == "LidarAvoider")
decide = next(n for n in avoider.body
              if isinstance(n, ast.FunctionDef) and n.name == "_decide")
halt_lines = [n.lineno for n in ast.walk(decide)
              if isinstance(n, ast.Attribute) and n.attr == "_planner_halted"]
send_lines = [n.lineno for n in ast.walk(decide)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr == "_send"]
check("_decide() checks _planner_halted() before every wheel command",
      bool(halt_lines) and bool(send_lines)
      and all(line > min(halt_lines) for line in send_lines),
      "halt@%s sends@%s" % (halt_lines, sorted(send_lines)))
check("the avoider has a HOLD state to report while halted",
      any(isinstance(n, ast.Assign)
          and getattr(n.targets[0], "id", "") == "HOLD" for n in avoider.body))

# ── 1. the refactored angle math is numerically identical ────────────────────
print("--- 1. perception == the math it replaced (randomised) ---")


def old_sector_min(angles_rad, distances_mm, center_deg, half_deg, min_mm=50):
    lo, hi = math.radians(center_deg - half_deg), math.radians(center_deg + half_deg)
    best = float('inf')
    for a, d in zip(angles_rad, distances_mm):
        a = math.atan2(math.sin(a - math.pi), math.cos(a - math.pi))
        if lo <= a <= hi and d >= min_mm and d < best:
            best = d
    return best


def old_turn_bias(angles_rad, distances_mm, half_deg, danger_mm, min_mm=50):
    left_w = right_w = 0.0
    lo, hi = math.radians(-half_deg), math.radians(half_deg)
    for a, d in zip(angles_rad, distances_mm):
        a = math.atan2(math.sin(a - math.pi), math.cos(a - math.pi))
        if not (lo <= a <= hi) or d < min_mm or d > danger_mm:
            continue
        w = (danger_mm - d) / danger_mm
        if a < 0:
            right_w += w
        else:
            left_w += w
    total = left_w + right_w
    return 0.0 if total < 1e-6 else max(-1.0, min(1.0, (right_w - left_w) / total))


random.seed(7)
same_sector = same_bias = True
for trial in range(200):
    angles, dists = scan(random.choice([500, 1500, 3000]),
                         {random.randint(-60, 60): random.randint(50, 2000)})
    if old_sector_min(angles, dists, 0, 45) != perception.sector_min(
            [perception.robot_angle(a) for a in angles], dists, 0, 45):
        same_sector = False
    robot_angles = [perception.robot_angle(a) for a in angles]
    if old_turn_bias(angles, dists, 45, 450) != perception.turn_bias(
            robot_angles, dists, 45, 450):
        same_bias = False
check("sector_min identical to the old implementation (200 random scans)", same_sector)
check("turn_bias identical to the old implementation (200 random scans)", same_bias)
check("box on the left of frame -> + bearing",
      perception.box_bearing_deg([60, 0, 140, 100]) > 0,
      perception.box_bearing_deg([60, 0, 140, 100]))
check("box on the right of frame -> - bearing",
      perception.box_bearing_deg([440, 0, 520, 100]) < 0)
check("label matching singular/plural", perception.names_match("chairs", "chair")
      and perception.names_match("chair", "chair"))

# ── 2. lifecycle: warm / enable / disable ────────────────────────────────────
print("--- 2. thread lifecycle owns its own transitions ---")
drv, _ = planner()
drv.warm()
check("warm() = thread up, planner idle, paused",
      drv._thread is not None and drv._thread.is_alive()
      and not drv.active and drv.last_decision == "paused")
drv.enable()
check("enable() -> active", drv.active)
drv.pursue("chair")
check("pursue() sets the target and enables",
      drv.active and drv.target.name == "chair")
drv.disable()
check("disable() = inactive + thread gone + target cleared",
      not drv.active and drv._thread is None and drv.target.name is None)
drv.enable()
check("enable() after disable() restarts the thread",
      drv.active and drv._thread is not None and drv._thread.is_alive())
drv.stop()

# ── 3. same status payload shape as before the restructure ───────────────────
print("--- 3. /selfdrive_status payload unchanged ---")
drv, _ = planner(base_data={'odl': -10398.7, 'odr': -9916.4, 'v': 11.48})
drv.warm()
st = drv.status()
check("keys identical",
      set(st) == {'active', 'suggested_turn', 'front_mm', 'halt', 'wheels',
                  'decision', 'busy_cells', 'objects', 'scores', 'target'},
      sorted(st))
check("wheels read from the ESP32 frame", st['wheels'] ==
      {'odl': -10398.7, 'odr': -9916.4, 'voltage': 11.48})
check("no target -> target is null", st['target'] is None)
drv.enable()
drv.pursue("chair")
t = drv.status()['target']
check("target block keys identical",
      set(t) == {'name', 'state', 'bearing_deg', 'range_m', 'seen', 'halt'}, sorted(t))
drv.stop()

# ── 4. safety comes first ────────────────────────────────────────────────────
print("--- 4. safety: no lidar, too close, surrounded ---")
drv, _ = planner(([], []))
drv.enable()
drv._tick()
check("no lidar -> refuse a heading, no bogus stop",
      drv.suggested_turn == 0.0 and drv.last_decision == "no lidar data"
      and drv.halt is False, drv.last_decision)
drv.stop()

drv, _ = planner(scan(sectors={0: 200}))
drv.enable()
drv._tick()
check("<250mm ahead -> halt + zero turn",
      drv.halt and drv.suggested_turn == 0.0 and "too close" in drv.last_decision,
      drv.last_decision)
drv.stop()

drv, _ = planner(scan(front_mm=500))
drv.enable()
drv.pursue("chair")   # the veto only exists while pursuing
drv._tick()
check("everything blocked while pursuing -> hold position",
      drv.halt and drv.suggested_turn == 0.0
      and drv.last_decision == "surrounded — holding position", drv.last_decision)
drv.stop()

# ── 5. cruise behavior unchanged ─────────────────────────────────────────────
print("--- 5. plain cruise ---")
drv, _ = planner()
drv.enable()
drv._tick()
check("clear room, no target -> straight ahead",
      drv.suggested_turn == 0.0 and drv.last_decision.startswith("heading +0°"),
      drv.last_decision)
check("scores still published for the UI", len(drv.last_scores) == 13)
drv.stop()

# ── 6. pursuit: aim, smoothness, arrival, search, veto ──────────────────────
print("--- 6. pursuit behaviors ---")
left_det = [{"name": "chair", "confidence": 0.9, "box": [60, 100, 140, 300]}]
drv, _ = planner(dets=left_det)
drv.enable()
drv.pursue("chair")
drv._tick()
t = drv.status()['target']
check("left-of-frame object -> + bearing, approaching",
      t['bearing_deg'] > 0 and t['state'] == 'approaching' and t['seen'], t)
aim = t['bearing_deg'] / 45.0
discrete_snap = 15.0 / 90.0
check("aims proportionally at the object, not at the discrete +15 snap",
      abs(drv.suggested_turn - aim) < 0.01
      and abs(drv.suggested_turn - discrete_snap) > 0.01,
      "turn=%s aim=%s snap=%s" % (drv.suggested_turn, round(aim, 3), discrete_snap))
check("decision names target + range",
      drv.last_decision.startswith("approaching chair bearing"), drv.last_decision)
drv.stop()

right_det = [{"name": "chair", "confidence": 0.9, "box": [440, 100, 520, 300]}]
drv, _ = planner(dets=right_det)
drv.enable()
drv.pursue("chair")
drv._tick()
check("right-of-frame object -> aims right", drv.suggested_turn < 0, drv.suggested_turn)
drv.stop()

near_det = [{"name": "refrigerator", "confidence": 0.66, "box": [280, 100, 315, 300]}]
drv, _ = planner(dets=near_det)
drv.enable()
drv.pursue("refrigerator")
turns = []
for _ in range(4):
    drv._tick()
    turns.append(round(drv.suggested_turn, 3))
check("near-centre target: identical turn every tick (no +/-15 jitter)",
      len(set(turns)) == 1, turns)
drv.stop()

# left_det sits at bearing +20.6°, so the near returns have to cover that
# bearing for it to be the *object* the lidar sees, not something beside it.
AT_BEARING = {d: 500 for d in range(11, 31)}
drv, _ = planner(scan(sectors=AT_BEARING), dets=left_det)
drv.enable()
drv.pursue("chair")
drv._tick()
check("0.5m object down its own bearing -> arrived + halt",
      drv.halt and drv.status()['target']['state'] == 'arrived', drv.last_decision)
# The executor's guard reads active+halt, so turning self-drive off has to clear
# both — otherwise a manual user could not drive away from the object.
drv.disable()
check("after arrival, disable() clears halt and active (manual driving unaffected)",
      not drv.halt and not drv.active)
drv.stop()

# Arrival has to be sticky. The object leaving the camera view is what happens
# the instant the robot is on top of it; re-deciding arrival each tick used to
# release halt right there and send the robot off again having reached it.
drv, cv = planner(scan(sectors=AT_BEARING), dets=left_det)
drv.enable()
drv.pursue("chair")
drv._tick()
cv.last_detections = []                      # object out of view now
for _ in range(3):
    drv._tick()
check("object lost from view after arrival -> halt still held, no turn",
      drv.halt and drv.suggested_turn == 0.0
      and drv.status()['target']['state'] == 'arrived',
      "halt=%s turn=%s %s" % (drv.halt, drv.suggested_turn, drv.last_decision))
# ...but seeing it again beyond the arrival band means it (or we) moved, so the
# chase must resume rather than stay frozen for good.
FAR_OUT = scan(sectors={d: 3000 for d in range(11, 31)})
drv, _ = planner(scan_pair=FAR_OUT, dets=left_det)
drv.enable()
drv.pursue("chair")
drv._tick()
check("object seen again beyond arrive_m -> resumes approaching, halt released",
      not drv.halt and drv.status()['target']['state'] == 'approaching',
      drv.last_decision)
drv.stop()

# The defect this replaced: the forward cone measured a wall beside the object,
# so the robot declared arrival at the wall's distance and stopped short.
BESIDE = {d: 500 for d in range(-40, -5)}
drv, _ = planner(scan(sectors=BESIDE), dets=left_det)
drv.enable()
drv.pursue("chair")
drv._tick()
t = drv.status()['target']
check("0.5m wall beside the object -> still approaching, no false arrival",
      not drv.halt and t['state'] == 'approaching' and t['range_m'] > 1.0,
      "range=%s halt=%s %s" % (t['range_m'], drv.halt, drv.last_decision))
drv.stop()

mem = spatial_memory.SpatialMemory()
mem.observe_object("chair", 40.0, 1.5, 0.9)          # remembered on the left
drv, _ = planner(mem=mem)
drv.enable()
drv.pursue("chair")
drv._tick()
first = drv.suggested_turn
check("not in view -> sweep toward the remembered bearing",
      first > 0 and "looking for chair" in drv.last_decision, drv.last_decision)
check("sweep flips direction after SCAN_FLIP_S",
      drv.target.next_scan_turn(now=time.time() + target_pursuit.SCAN_FLIP_S + 1) < 0)
drv.stop()

mem2 = spatial_memory.SpatialMemory()
mem2.observe_object("chair", -40.0, 1.5, 0.9)        # remembered on the right
drv, _ = planner(mem=mem2)
drv.enable()
drv.pursue("chair")
drv._tick()
check("sweep direction follows the memory sign", drv.suggested_turn < 0,
      drv.suggested_turn)
drv.stop()

wall = {d: 900 for d in range(-12, 13)}
drv, _ = planner(scan(sectors=wall), dets=near_det)
drv.enable()
drv.pursue("refrigerator")
drv._tick()
check("wall across the bearing -> veto, route around, keep driving",
      dict(drv.last_scores).get(0) is None and drv.suggested_turn != 0.0
      and not drv.halt and "(going around)" in drv.last_decision,
      drv.last_decision)
drv.stop()

# ── 7. open-vocabulary top-up (now DetectionSource) ─────────────────────────
print("--- 7. detections: closed-set live stream + open-vocabulary top-up ---")
coco = [{"name": "person", "confidence": 0.9, "box": [280, 100, 360, 300]}]
world = [{"name": "refrigerator", "confidence": 0.66, "box": [60, 100, 140, 300]}]
drv, cv = planner(dets=coco, world=world)
drv.enable()
drv._tick()
check("no target -> no open-vocabulary scan", cv.world_calls == 0, cv.world_calls)
drv.pursue("refrigerator")
drv._tick()
t = drv.status()['target']
check("pursues an object only the open-vocabulary model can name",
      t['seen'] and t['state'] == 'approaching' and t['bearing_deg'] > 0, t)
check("scan throttled to one call", cv.world_calls == 1, cv.world_calls)
drv._tick()
check("throttled: next tick reuses the cache", cv.world_calls == 1, cv.world_calls)
src = DetectionSource(cv, world_scan_s=5.0)
src.for_target("refrigerator", now=100.0)
src.for_target("refrigerator", now=101.0)
check("DetectionSource throttle independent of the planner", cv.world_calls == 2,
      cv.world_calls)
drv.stop()

# object fusion still writes the corrected bearing into memory
mem3 = spatial_memory.SpatialMemory()
drv, _ = planner(dets=left_det, mem=mem3)
drv.enable()
drv._tick()
check("detections fused into memory with + bearing (left object)",
      mem3.objects and mem3.objects[0]['bearing_deg'] > 0 and
      mem3.objects[0]['name'] == 'chair', mem3.objects[:1])
drv.stop()

# ── 8. memory: ownership, versioning, planner shortcuts ────────────────────
print("--- 8. memory ---")
tmp = os.path.join(tempfile.gettempdir(), "_sd_restructure_probe.json")
with open(tmp, "w") as fh:
    json.dump({"grid": [[7] * 121] * 121, "objects": [{"name": "x"}]}, fh)
old = spatial_memory.SpatialMemory(path=tmp)
check("v1 (pre-frame-fix) map is refused", old.busy_cells == 0 and old.objects == [])
old.observe_lidar(*[list(x) for x in ((),)]) if False else None
angles, dists = scan(front_mm=1000)
mem4 = spatial_memory.SpatialMemory(path=tmp)
mem4.observe_lidar([perception.robot_angle(a) for a in angles], dists)
drv, _ = planner(mem=mem4)
check("planner.save_memory() routes to the memory owner", drv.save_memory())
check("reloaded v2 map round-trips",
      spatial_memory.SpatialMemory(path=tmp).busy_cells > 0)
drv.clear_memory()
check("planner.clear_memory() empties the map", drv.memory.busy_cells == 0)
drv.load_memory()
check("planner.load_memory() reloads it", drv.memory.busy_cells > 0)
os.remove(tmp)

# ── 9. "drive to the <object>" reaches pursuit without the language model ────
print("--- 9. pursuit intent is read, not guessed ---")
for phrase, want in (("drive towards the chair", "chair"),
                     ("go to the door", "door"),
                     ("head for the person", "person"),
                     ("approach the table", "table"),
                     ("move over to the monitor", "monitor"),
                     ("navigate towards the tv", "tv"),
                     ("Drive To The Coffee Maker Please", "coffee maker"),
                     ("drive to the bin and then forward", "bin"),
                     ("drive towards a chair for 2 seconds", "chair"),
                     ("go to the 3rd chair", "3rd chair"),
                     ("drive to the mug on the table", "mug")):
    check("%r -> %r" % (phrase, want), lance.parse_pursuit_intent(phrase) == want,
          lance.parse_pursuit_intent(phrase))
for phrase in ("drive forward", "go back", "drive to the left",
               "drive for 2 seconds", "drive to 5 metres", "spin right",
               "turn left 90 degrees", "stop", "what do you see",
               "take a picture", "learn that this is a mug",
               "drive to the", "go to a", "approach the", "drive to"):
    check("%r is not a pursuit request" % phrase,
          lance.parse_pursuit_intent(phrase) is None,
          lance.parse_pursuit_intent(phrase))
check("approach/goto aliases all reach target pursuit",
      all(lance.ACTIONS[a] is lance._approach
          for a in ("approach", "goto", "go_to", "drive_to")))
check("pursuing is reachable the way the router calls it",
      lance.ACTIONS["approach"] is lance._approach)

print()
print("RESULT: %d failures" % len(FAILS))
if FAILS:
    print("FAILED: " + ", ".join(FAILS))
    raise SystemExit(1)
print("ALL PROBES PASSED")
