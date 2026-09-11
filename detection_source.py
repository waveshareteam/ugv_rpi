"""detection_source.py — the camera detections the planner is allowed to see.

The frame loop publishes the closed-set model's hits into
cvf.last_detections and overwrites them every frame. That stream cannot name
an object outside its own class list ('refrigerator', 'whiteboard'), while
cvf.detect_world() — the open-vocabulary YOLO-World pass Lance speaks from —
can.

This module owns the merge between the two, including the throttle: YOLO-World
costs real CPU on the Pi, so it is only run while the target is missing from
the live stream, and at most once every `world_scan_s`. The cached result is
merged in behind the live hits, which stay authoritative when a name appears
in both.
"""

from perception import names_match


class DetectionSource:
    """Live detections, topped up with a throttled open-vocabulary scan."""

    def __init__(self, cvf, world_scan_s=1.0):
        self._cvf = cvf
        self.world_scan_s = world_scan_s
        self._world_dets = []
        self._world_scan_t = 0.0
        self._clock = None      # injectable for tests; defaults to time.time

    # ── reads ─────────────────────────────────────────────────────────────
    def live(self):
        """Whatever the closed-set frame loop last published."""
        return list(getattr(self._cvf, 'last_detections', None) or [])

    def for_target(self, name, now=None):
        """Detections for pursuing `name` (None -> just the live stream).

        When the live stream has no match, the open-vocabulary pass is
        consulted (throttled) and its hits are appended.
        """
        dets = self.live()
        if not name:
            self._world_dets = []
            return dets
        if any(names_match(d.get('name', ''), name) for d in dets):
            return dets
        now = self._now(now)
        world = getattr(self._cvf, 'detect_world', None)
        if callable(world) and now - self._world_scan_t >= self.world_scan_s:
            self._world_scan_t = now
            try:
                self._world_dets = list(world() or [])
            except Exception as e:
                print(f"[detections] open-vocabulary scan failed: {e}")
                self._world_dets = []
        if self._world_dets:
            seen = {d.get('name') for d in dets}
            dets = dets + [d for d in self._world_dets if d.get('name') not in seen]
        return dets

    # ── internals ─────────────────────────────────────────────────────────
    def _now(self, now):
        if now is not None:
            return now
        if self._clock is None:
            import time
            self._clock = time.time
        return self._clock()
