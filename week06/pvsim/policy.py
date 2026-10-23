"""One policy for all agents: desire relaxation + reciprocal braking envelopes.

This is a transparent baseline, not ORCA, a calibrated SFM, or a safety proof.
All controls are computed from the same pre-step snapshot.
"""
from dataclasses import dataclass
from typing import Protocol, Sequence
import math
from .domain import AgentState, Road, Settings
from .topology import neighbor_images


def clip(value, low, high):
    return max(low, min(high, value))


def safe_speed(distance, brake, reserve):
    return max(0.0, math.sqrt((brake * reserve) ** 2 + 2 * brake * max(distance, 0.0)) - brake * reserve)


@dataclass(frozen=True)
class Control:
    speed: float
    vy: float
    mode: str
    committed: bool
    braking_infeasible: bool = False


class Policy(Protocol):
    def control(self, agent: AgentState, agents: Sequence[AgentState], road: Road, settings: Settings) -> Control:
        ...


class ReciprocalPolicy:
    name = "reciprocal"

    def control(self, agent, agents, road, settings):
        p, c = agent.spec, settings
        active = neighbor_images(agent, agents, road)
        encounters = []
        for b in active:
            if b.spec.direction == p.direction:
                continue
            front = p.direction * (b.x - agent.x)
            extent = (p.length + b.spec.length) / 2
            # Nominal speeds avoid losing sight of the interaction after braking.
            detection = max(8.0, (p.desired_speed + b.spec.desired_speed) * c.horizon)
            if -extent - c.longitudinal_clearance < front < detection + extent:
                encounters.append(b)

        committed = bool(encounters)
        # Look ahead to narrow walls using map geometry; no width oracle forces a stop.
        look = max(4.0, p.desired_speed * c.horizon)
        forward_x = agent.x + p.direction * look
        narrow = road.min_width(min(agent.x, forward_x) - p.length / 2,
                                max(agent.x, forward_x) + p.length / 2)
        limit = max(0.0, narrow / 2 - p.width / 2 - c.wall_clearance)
        if p.lateral_speed > 0:
            target_y = p.side * limit if committed else clip(p.home_y, -limit, limit)
        else:
            target_y = agent.y  # Exactly zero lateral mobility, same equation otherwise.
        error = target_y - agent.y
        desired_vy = clip(error / p.lateral_tau, -p.lateral_speed, p.lateral_speed)
        bound = safe_speed(abs(error), p.lateral_accel, c.dt)
        desired_vy = clip(desired_vy, -bound, bound)
        vy = agent.vy + clip(desired_vy - agent.vy, -p.lateral_accel * c.dt, p.lateral_accel * c.dt)

        target = p.desired_speed
        if encounters:
            spare = min(narrow - p.width - b.spec.width - 2 * c.wall_clearance - c.lateral_clearance
                        for b in encounters)
            factor = c.squeeze_speed_fraction + (1 - c.squeeze_speed_fraction) * clip(spare / c.comfort_extra_gap, 0.0, 1.0)
            target = min(target, p.encounter_speed * factor)
        # One speed budget for the velocity vector, including sideways motion.
        target = min(target, math.sqrt(max(p.desired_speed ** 2 - vy ** 2, 0.0)))
        speed = agent.speed + clip((target - agent.speed) / p.speed_tau,
                                   -p.max_brake, p.max_accel) * c.dt
        ceiling = p.desired_speed
        reserve = c.reaction_buffer + c.dt
        obstructed = False
        for b in active:
            front = p.direction * (b.x - agent.x)
            extent = (p.length + b.spec.length) / 2
            lat_extent = (p.width + b.spec.width) / 2
            lat_gap = abs(agent.y - b.y) - lat_extent
            # Include one-step lateral closure; never release solely on future intent.
            next_gap = abs((agent.y + vy * c.dt) - (b.y + b.vy * c.dt)) - lat_extent
            separated = min(lat_gap, next_gap) >= c.lateral_clearance - c.clearance_tolerance
            if separated:
                continue
            if b.spec.direction != p.direction:
                if front <= -extent - c.longitudinal_clearance:
                    continue
                gap = front - extent - c.longitudinal_clearance
                # Equal stopping-space allocation; each side responds independently.
                candidate = safe_speed(0.5 * gap, p.max_brake, reserve)
            else:
                if front <= 0:
                    continue
                gap = front - extent - c.longitudinal_clearance
                # Stationary-leader bound is conservative, avoids a hidden leader model.
                candidate = safe_speed(gap, p.max_brake, reserve)
            ceiling = min(ceiling, candidate)
            obstructed = obstructed or candidate < target

        infeasible = ceiling < agent.speed - p.max_brake * c.dt - 1e-9
        speed = clip(min(speed, ceiling), max(0.0, agent.speed - p.max_brake * c.dt),
                     agent.speed + p.max_accel * c.dt)
        if speed < c.stop_speed and abs(vy) < c.stop_speed:
            mode = "WAIT"
        elif speed < agent.speed - 1e-6:
            mode = "BRAKE"
        elif committed and abs(error) > 0.03 and p.lateral_speed > 0:
            mode = "SIDESTEP"
        elif committed:
            mode = "PASS"
        elif abs(error) > 0.03:
            mode = "RECOVER"
        elif obstructed:
            mode = "FOLLOW"
        else:
            mode = "FREE"
        return Control(speed, vy, mode, committed, infeasible)
