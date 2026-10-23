"""Synchronous simulator, independent from the policy, scenario factories and UI."""
from dataclasses import asdict, replace
from itertools import combinations
import copy
import math
from .geometry import swept_contact, swept_separation, swept_wall_gap, wall_gap, separation
from .policy import ReciprocalPolicy
from .diagnostics import feasibility, classify_stall
from .topology import pair_images, relative_front


def snapshot(t, agents):
    return {"time": round(t, 6), "agents": [
        {"id": a.spec.id, "x": round(a.x, 6), "y": round(a.y, 6),
         "speed": round(a.speed, 6), "vy": round(a.vy, 6), "mode": a.mode, "done": a.done}
        for a in agents]}


def validate(scenario):
    if not scenario.agents:
        raise ValueError("Scenario must contain agents")
    ids = [a.spec.id for a in scenario.agents]
    if len(set(ids)) != len(ids):
        raise ValueError("Agent ids must be unique")
    for a in scenario.agents:
        if not all(math.isfinite(v) for v in (a.x, a.y, a.speed, a.vy, a.spec.home_y)) or a.speed < 0:
            raise ValueError(f"Invalid initial state: {a.spec.id}")
        if wall_gap(scenario.road, a) < -1e-9:
            raise ValueError(f"Initial footprint leaves road: {a.spec.id}")
        if not scenario.road.periodic and (a.x - a.spec.length / 2 < 0 or a.x + a.spec.length / 2 > scenario.road.length):
            raise ValueError(f"Initial footprint outside road ends: {a.spec.id}; use fewer agents or custom positions")
        if scenario.road.periodic and (a.spec.length >= scenario.road.length / 2 or
                                      max(a.spec.desired_speed, a.speed) * scenario.settings.dt >= scenario.road.length / 4):
            raise ValueError("Periodic footprints/steps must be small relative to circumference")
    for a, b in combinations(scenario.agents, 2):
        if any(swept_contact(a, a, bi, bi) is not None for bi, _ in pair_images(a, b, b, scenario.road)):
            raise ValueError(f"Initial contact/overlap: {a.spec.id}, {b.spec.id}")


def simulate(scenario, policy=None, record=True):
    validate(scenario)
    policy = policy or ReciprocalPolicy()
    agents = copy.deepcopy(scenario.agents)
    c, road = scenario.settings, scenario.road
    trace = [snapshot(0.0, agents)] if record else []
    status, events, t, quiet_time = "timeout", [], 0.0, 0.0
    min_gap = min((separation(a, bi) for a, b in combinations(agents, 2)
                   for bi, _ in pair_images(a, b, b, road)), default=float("inf"))
    min_wall = min(wall_gap(road, a) for a in agents)
    collisions, violations, braking_infeasible_steps = set(), set(), 0
    exit_times = {}
    detector_crossings = {a.spec.id: 0 for a in agents}
    pair_passages = 0
    max_steps = math.ceil(c.max_time / c.dt)
    for step in range(1, max_steps + 1):
        dt = min(c.dt, c.max_time - t)
        if dt <= 1e-12:
            break
        step_settings = replace(c, dt=dt)
        # No control sees another agent's already-updated position.
        controls = {a.spec.id: policy.control(a, agents, road, step_settings) for a in agents if not a.done}
        following = []
        for a in agents:
            if a.done:
                following.append(a)
                continue
            u = controls[a.spec.id]
            b = replace(a, x=a.x + a.spec.direction * u.speed * dt,
                        y=a.y + u.vy * dt, speed=u.speed, vy=u.vy,
                        mode=u.mode, committed=u.committed)
            b.path_length += math.hypot(b.x - a.x, b.y - a.y)
            if math.hypot(b.speed, b.vy) < c.stop_speed:
                b.waiting_time += dt
            b.peak_decel = max(a.peak_decel, (a.speed - b.speed) / dt)
            braking_infeasible_steps += int(u.braking_infeasible)
            following.append(b)
        for i, j in combinations(range(len(agents)), 2):
            a, b, an, bn = agents[i], agents[j], following[i], following[j]
            if a.done or b.done:
                continue
            contacts = []
            for bi, bni in pair_images(a, b, bn, road):
                contact = swept_contact(a, an, bi, bni)
                min_gap = min(min_gap, swept_separation(a, an, bi, bni))
                if contact is not None:
                    contacts.append(contact)
            if contacts:
                pair = tuple(sorted((a.spec.id, b.spec.id)))
                collisions.add(pair)
                events.append({"time": t + min(contacts) * dt, "type": "collision", "agents": pair})
            threshold = -(a.spec.length + b.spec.length) / 2 - c.longitudinal_clearance
            if (a.spec.direction != b.spec.direction and not contacts and
                relative_front(a, b, road) >= threshold > relative_front(an, bn, road)):
                pair_passages += 1
                events.append({"time": t + dt, "type": "pair_passage", "agents": [a.spec.id, b.spec.id]})
        for a, b in zip(agents, following):
            if a.done:
                continue
            gap = swept_wall_gap(road, a, b)
            min_wall = min(min_wall, gap)
            if gap < -1e-8:
                violations.add(a.spec.id)
                events.append({"time": t + dt, "type": "wall_violation", "agent": a.spec.id})
            if road.periodic:
                detector_crossings[b.spec.id] += abs(math.floor(b.x / road.length) - math.floor(a.x / road.length))
            crossed = (b.x - b.spec.length / 2 >= road.length if b.spec.direction == 1 else b.x + b.spec.length / 2 <= 0) if not road.periodic else False
            if crossed:
                # Count only when the trailing edge leaves. Retain final footprint in trace.
                b.done, b.mode = True, "DONE"
                boundary = road.length + b.spec.length / 2 if b.spec.direction == 1 else -b.spec.length / 2
                fraction = (boundary - a.x) / (b.x - a.x)
                b.exit_time = t + fraction * dt
                exit_times[b.spec.id] = b.exit_time
                events.append({"time": b.exit_time, "type": "exit", "agent": b.spec.id})
        t += dt
        agents = following
        if record and step % c.record_every == 0:
            trace.append(snapshot(t, agents))
        if collisions or violations:
            status = "collision" if collisions else "boundary_violation"
            break
        if all(a.done for a in agents):
            status = "completed"
            break
        live = [a for a in agents if not a.done]
        quiet = all(math.hypot(a.speed, a.vy) < c.stop_speed for a in live)
        quiet_time = quiet_time + dt if quiet else 0.0
        if quiet_time >= c.stall_time:
            status = classify_stall(scenario, agents)
            events.append({"time": t, "type": "stall", "classification": status})
            break
    if road.periodic and status == "timeout":
        status = "sustained"
    if record and (not trace or abs(trace[-1]["time"] - t) > 1e-7):
        trace.append(snapshot(t, agents))
    counts = {kind: sum(a.done and a.spec.kind == kind for a in agents) for kind in ("pedestrian", "vehicle")}
    total = {kind: sum(a.spec.kind == kind for a in agents) for kind in counts}
    finish = max(exit_times.values()) if status == "completed" else None
    metrics = {"status": status, "observation_time_s": t, "completion_time_s": finish,
               "pedestrians_passed": counts["pedestrian"], "vehicles_passed": counts["vehicle"],
               "pedestrians_total": total["pedestrian"], "vehicles_total": total["vehicle"],
               "collision_pairs": len(collisions), "boundary_violations": len(violations),
               "pair_passages": pair_passages,
               "detector_crossings": detector_crossings if road.periodic else None,
               "total_laps": sum(int(abs(a.x - start.x) / road.length) for a, start in zip(agents, scenario.agents)) if road.periodic else None,
               "longitudinal_distance_m": sum(abs(a.x - start.x) for a, start in zip(agents, scenario.agents)),
               "mean_longitudinal_speed_m_s": sum(abs(a.x - start.x) for a, start in zip(agents, scenario.agents)) / (t * len(agents)) if t else 0,
               "effective_speed_planned_horizon_m_s": sum(abs(a.x - start.x) for a, start in zip(agents, scenario.agents)) / (c.max_time * len(agents)) if road.periodic else None,
               "pair_passages_per_min_planned": 60 * pair_passages / c.max_time if road.periodic else None,
               "safety_margins_satisfied": not collisions and not violations and min_gap >= c.lateral_clearance - c.clearance_tolerance and min_wall >= c.wall_clearance - c.clearance_tolerance,
               "min_pair_gap_m": min_gap if math.isfinite(min_gap) else None,
               "min_wall_gap_m": min_wall,
               "speed_ceiling_unreachable_agent_steps": braking_infeasible_steps,
               "total_agent_waiting_s": sum(a.waiting_time for a in agents),
               "pedestrian_flow_per_min": 60 * counts["pedestrian"] / t if t else 0,
               "vehicle_flow_per_min": 60 * counts["vehicle"] / t if t else 0,
               "agents": [{"id": a.spec.id, "exit_time_s": a.exit_time,
                           "waiting_time_s": a.waiting_time, "path_length_m": a.path_length,
                           "peak_decel_m_s2": a.peak_decel} for a in agents]}
    return {"policy": {"name": getattr(policy, "name", type(policy).__name__),
                       "parameters": asdict(policy.parameters) if hasattr(policy, "parameters") else {}},
            "scenario": {"name": scenario.name, "seed": scenario.seed, "road": asdict(road),
                         "settings": asdict(c), "agents": [asdict(a.spec) for a in scenario.agents],
                         "initial_states": [asdict(a) for a in scenario.agents], "metadata": scenario.metadata},
            "feasibility": feasibility(scenario), "metrics": metrics, "events": events, "trace": trace}
