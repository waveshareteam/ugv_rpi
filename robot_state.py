"""robot_state.py — reading what the robot's sensors currently say.

One owner of "the robot's live readings". Nothing here decides anything: it
reads the LIDAR scan (applying the raw->robot-frame angle correction exactly
once, via perception.robot_angle) and the ESP32 wheel odometer counters.

The LIDAR list is published by base_ctrl's receive thread and re-bound as a
fresh list on every revolution, so every read snapshots it into a list before
use — the planner must not walk a list that is being replaced underneath it.
"""

from perception import front_min_mm, robot_angle


class LidarScan:
    """One LIDAR scan, angles already in the robot frame (0 = forward, + = left)."""

    __slots__ = ('angles', 'distances', '_front_cache')

    def __init__(self, angles, distances):
        self.angles = angles
        self.distances = distances
        self._front_cache = {}

    @classmethod
    def read(cls, base):
        """Snapshot the freshest scan from a BaseController."""
        rl = getattr(base, 'rl', None)
        raw_angles = list(getattr(rl, 'lidar_angles_show', None) or [])
        distances = list(getattr(rl, 'lidar_distances_show', None) or [])
        return cls([robot_angle(a) for a in raw_angles], distances)

    @property
    def empty(self):
        return not self.angles

    def front_min_mm(self, half_deg):
        """Smallest range inside a forward cone of +-half_deg (cached per cone)."""
        if half_deg not in self._front_cache:
            self._front_cache[half_deg] = front_min_mm(self.angles,
                                                       self.distances, half_deg)
        return self._front_cache[half_deg]


def wheel_odometry(base):
    """Latest ESP32 wheel odometer counters.

    The planner only suggests headings, so without these there is no way to
    tell "steering not delivered" from "chassis cannot move" — the counters
    changing is the only hard proof the wheels actually turned.
    """
    data = getattr(base, 'base_data', None) or {}
    return {'odl': data.get('odl'), 'odr': data.get('odr'),
            'voltage': data.get('v')}
