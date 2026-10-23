"""Uncalibrated Helbing-style baseline with common rectangular envelopes.

A and wall_A are accelerations. This is an adapted SFM, not a verbatim
implementation of the original circular-pedestrian 1995 model.
"""
from dataclasses import dataclass, asdict
import math
from .policy import Control, ReciprocalPolicy, clip
from .topology import neighbor_images


@dataclass(frozen=True)
class SocialForceParameters:
    A: float = 8.0
    B: float = 1.5
    wall_A: float = 3.0
    wall_B: float = 0.2
    anisotropy: float = 0.3

    def __post_init__(self):
        if min(self.A, self.B, self.wall_A, self.wall_B) <= 0 or not 0 <= self.anisotropy <= 1:
            raise ValueError("Invalid social-force parameters")


def repulsion(a, b):
    dx, dy = a.x - b.x, a.y - b.y
    distance = math.hypot(dx, dy)
    if distance < 1e-12:
        return -min(a.spec.width, b.spec.width), float(a.spec.direction), 0.0
    nx, ny = dx / distance, dy / distance
    hx, hy = (a.spec.length + b.spec.length) / 2, (a.spec.width + b.spec.width) / 2
    # SFM uses a centre-to-centre normal. A directional effective radius adapts
    # circular personal space to the common rectangle dimensions; it is NOT
    # the exact gradient of rectangle distance. Collision checks remain exact.
    radius = min(hx / max(abs(nx), 1e-12), hy / max(abs(ny), 1e-12))
    return distance - radius, nx, ny


class SocialForcePolicy:
    name = "social_force"

    def __init__(self, parameters=None, resolved_gate=False):
        self.parameters = parameters or SocialForceParameters()
        self.resolved_gate = resolved_gate

    def control(self, agent, agents, road, settings):
        p, q, c = agent.spec, self.parameters, settings
        desired_vy = clip((p.home_y - agent.y) / p.lateral_tau, -p.lateral_speed, p.lateral_speed)
        ax = (p.direction * p.desired_speed - agent.vx) / p.speed_tau
        ay = (desired_vy - agent.vy) / p.lateral_tau
        for other in neighbor_images(agent, agents, road):
            if (self.resolved_gate and p.direction != other.spec.direction and
                abs(agent.y - other.y) - (p.width + other.spec.width) / 2 >=
                c.lateral_clearance - c.clearance_tolerance):
                continue
            distance, nx, ny = repulsion(agent, other)
            cos_front = -p.direction * nx
            weight = q.anisotropy + (1 - q.anisotropy) * (1 + cos_front) / 2
            strength = q.A * math.exp(clip(-distance / q.B, -50, 10)) * weight
            ax += strength * nx
            ay += strength * ny
        width = road.min_width(agent.x - p.length / 2, agent.x + p.length / 2)
        lower = agent.y + width / 2 - p.width / 2
        upper = width / 2 - agent.y - p.width / 2
        ay += q.wall_A * (math.exp(clip(-lower / q.wall_B, -50, 10)) - math.exp(clip(-upper / q.wall_B, -50, 10)))
        speed = clip(agent.speed + clip(p.direction * ax, -p.max_brake, p.max_accel) * c.dt, 0, p.desired_speed)
        vy = clip(agent.vy + clip(ay, -p.lateral_accel, p.lateral_accel) * c.dt, -p.lateral_speed, p.lateral_speed)
        if math.hypot(speed, vy) < c.stop_speed:
            mode = "WAIT"
        elif speed < agent.speed - 1e-6:
            mode = "BRAKE"
        elif abs(vy) > c.stop_speed:
            mode = "SIDESTEP"
        else:
            mode = "FREE"
        return Control(speed, vy, mode, False)


class GuidedSocialForcePolicy:
    """Ablation repair: keep SFM longitudinal force, add route choice + speed cap.

The lateral command is explicitly replaced by the shared rule planner; report
this as a hybrid, never as evidence that a pure SFM guarantees safe navigation.
"""
    name = "sfm_guided"

    def __init__(self, parameters=None, release_resolved=True):
        self.base = SocialForcePolicy(parameters, resolved_gate=release_resolved)
        self.parameters = self.base.parameters
        self.guide = ReciprocalPolicy()
        if not release_resolved:
            self.name = "sfm_guided_ungated"

    def control(self, agent, agents, road, settings):
        sf = self.base.control(agent, agents, road, settings)
        rule = self.guide.control(agent, agents, road, settings)
        return Control(min(sf.speed, rule.speed), rule.vy, rule.mode, rule.committed, rule.braking_infeasible)


def make_policy(name, parameters=None):
    if name == "reciprocal":
        return ReciprocalPolicy()
    if name == "social_force":
        return SocialForcePolicy(parameters)
    if name == "sfm_guided":
        return GuidedSocialForcePolicy(parameters)
    if name == "sfm_guided_ungated":
        return GuidedSocialForcePolicy(parameters, release_resolved=False)
    raise ValueError(f"Unknown policy: {name}")
