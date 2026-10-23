"""Necessary cross-section tests; deliberately not a global reachability proof."""
from itertools import combinations


def feasibility(scenario):
    c, road = scenario.settings, scenario.road
    pairs = [(a, b) for a, b in combinations(scenario.agents, 2)
             if a.spec.direction != b.spec.direction]
    physical = max((a.spec.width + b.spec.width for a, b in pairs), default=0.0)
    safe = physical + 2 * c.wall_clearance + c.lateral_clearance
    pose = True
    for a, b in pairs:
        for fixed, mobile in ((a, b), (b, a)):
            if fixed.spec.lateral_speed == 0:
                w = road.min_width()
                # Mobile's committed passing side is part of the controller's constraints.
                room = w / 2 - mobile.spec.side * fixed.y - fixed.spec.width / 2 - c.wall_clearance
                if room + c.clearance_tolerance < mobile.spec.width + c.lateral_clearance:
                    pose = False
    w = road.min_width()
    return {"minimum_road_width_m": w, "physical_width_threshold_m": physical,
            "safe_width_threshold_m": safe,
            "physical_cross_section_fits": w + c.clearance_tolerance >= physical,
            "safe_cross_section_fits": w + c.clearance_tolerance >= safe,
            "fixed_pose_cross_section_fits": pose,
            "scope": "Necessary cross-section conditions at the narrowest section; no global path or liveness guarantee."}


def classify_stall(scenario, agents):
    facts = feasibility(scenario)
    if not facts["physical_cross_section_fits"]:
        return "waiting_geometry"
    if not facts["safe_cross_section_fits"]:
        return "waiting_clearance"
    if not facts["fixed_pose_cross_section_fits"]:
        return "waiting_alignment"
    return "deadlock_policy"
