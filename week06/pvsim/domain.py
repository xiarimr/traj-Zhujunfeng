from dataclasses import dataclass, field
from typing import List, Tuple
import math


@dataclass(frozen=True)
class AgentSpec:
    """Kind is metadata only: the policy never branches on pedestrian/vehicle."""
    id: str
    kind: str
    length: float
    width: float
    desired_speed: float
    max_accel: float
    max_brake: float
    lateral_speed: float
    lateral_accel: float
    direction: int
    side: int
    home_y: float
    mass: float = 1.0  # Metadata, not a social priority or an interaction force.
    speed_tau: float = 0.7
    lateral_tau: float = 0.8
    encounter_speed: float = 1.0

    def __post_init__(self):
        for name in ("length", "width", "desired_speed", "max_accel", "max_brake",
                     "lateral_accel", "mass", "speed_tau", "lateral_tau", "encounter_speed"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{self.id}: {name} must be positive and finite")
        if not math.isfinite(self.lateral_speed) or self.lateral_speed < 0:
            raise ValueError("lateral_speed must be finite and nonnegative")
        if self.direction not in (-1, 1) or self.side not in (-1, 1):
            raise ValueError("direction and side must be -1 or +1")


@dataclass
class AgentState:
    spec: AgentSpec
    x: float
    y: float
    speed: float  # Nonnegative speed along direction.
    vy: float = 0.0
    mode: str = "FREE"
    committed: bool = False
    done: bool = False
    exit_time: float = None
    waiting_time: float = 0.0
    path_length: float = 0.0
    peak_decel: float = 0.0

    @property
    def vx(self):
        return self.spec.direction * self.speed


@dataclass(frozen=True)
class Road:
    """Symmetric, piecewise-linear road width w(x), extended at both ends."""
    length: float
    profile: Tuple[Tuple[float, float], ...]
    periodic: bool = False

    def __post_init__(self):
        if self.length <= 0 or len(self.profile) < 2:
            raise ValueError("Road needs positive length and >=2 profile points")
        if any(not math.isfinite(x) or not math.isfinite(w) or w <= 0 for x, w in self.profile):
            raise ValueError("Invalid width profile")
        if any(b[0] <= a[0] for a, b in zip(self.profile, self.profile[1:])):
            raise ValueError("Profile x coordinates must strictly increase")
        if self.profile[0][0] != 0 or self.profile[-1][0] != self.length:
            raise ValueError("Profile must cover [0, length]")
        if self.periodic and len(set(w for _, w in self.profile)) != 1:
            raise ValueError("The periodic-strip baseline currently requires constant width")

    def width_at(self, x):
        if x <= self.profile[0][0]:
            return self.profile[0][1]
        for (x0, w0), (x1, w1) in zip(self.profile, self.profile[1:]):
            if x <= x1:
                return w0 + (w1 - w0) * (x - x0) / (x1 - x0)
        return self.profile[-1][1]

    def min_width(self, x0=None, x1=None):
        if x0 is None:
            return min(w for _, w in self.profile)
        lo, hi = sorted((x0, x1))
        return min([self.width_at(lo), self.width_at(hi)] +
                   [w for x, w in self.profile if lo <= x <= hi])


@dataclass(frozen=True)
class Settings:
    dt: float = 0.05
    max_time: float = 160.0
    horizon: float = 6.0
    reaction_buffer: float = 0.6  # Planning reserve, NOT a delayed-observation simulator.
    lateral_clearance: float = 0.20
    wall_clearance: float = 0.10
    longitudinal_clearance: float = 0.60
    stall_time: float = 8.0
    stop_speed: float = 0.025
    record_every: int = 4
    clearance_tolerance: float = 1e-5
    squeeze_speed_fraction: float = 0.35
    comfort_extra_gap: float = 0.60

    def __post_init__(self):
        for name in ("dt", "max_time", "horizon", "stall_time", "stop_speed"):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) <= 0:
                raise ValueError(f"{name} must be positive and finite")
        for name in ("reaction_buffer", "lateral_clearance", "wall_clearance", "longitudinal_clearance"):
            if not math.isfinite(getattr(self, name)) or getattr(self, name) < 0:
                raise ValueError(f"{name} must be nonnegative and finite")
        if self.record_every < 1:
            raise ValueError("record_every must be >=1")
        if not 0 < self.squeeze_speed_fraction <= 1 or self.comfort_extra_gap <= 0:
            raise ValueError("Invalid squeeze-speed parameters")


@dataclass
class Scenario:
    name: str
    road: Road
    agents: List[AgentState]
    settings: Settings = field(default_factory=Settings)
    seed: int = 0
    metadata: dict = field(default_factory=dict)
