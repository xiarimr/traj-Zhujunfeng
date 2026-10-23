"""Scenario factories: modify geometry and initial conditions, not the simulator."""
from dataclasses import replace
import json
import random
from pathlib import Path
from .domain import AgentSpec, AgentState, Road, Settings, Scenario


def corridor(width=3.2, pedestrians=3, vehicles=2, seed=0, settings=None,
             vehicle_speed=3.0, pedestrian_speed=1.3, lateral_speed=0.7,
             vehicle_lateral_speed=0.0, centered_vehicle=False,
             pedestrian_spacing=2.5, vehicle_spacing=9.0, speed_jitter=0.08,
             pedestrian_width=0.6, vehicle_width=1.8, initial_gap=28.0,
             mass_scale=1.0, bottleneck=False):
    c = settings or Settings()
    if width <= 0 or pedestrians < 1 or vehicles < 1:
        raise ValueError("Need positive width and at least one of each agent")
    road = Road(60.0, ((0.0, width), (60.0, width)))
    if bottleneck:
        road = Road(60.0, ((0.0, 5.0), (12.0, 5.0), (18.0, width),
                           (42.0, width), (48.0, 5.0), (60.0, 5.0)))
    rng = random.Random(seed)
    lane_y = 0.0 if centered_vehicle else -width / 2 + c.wall_clearance + vehicle_width / 2
    agents = []
    for i in range(vehicles):
        speed = vehicle_speed * (1 + rng.uniform(-speed_jitter, speed_jitter))
        p = AgentSpec(f"V{i+1}", "vehicle", 4.5, vehicle_width, speed, 1.5, 3.0,
                      vehicle_lateral_speed, 0.4, 1, -1, lane_y, 1500 * mass_scale,
                      encounter_speed=1.0)
        agents.append(AgentState(p, 16.0 - i * vehicle_spacing, lane_y, speed))
    for i in range(pedestrians):
        speed = pedestrian_speed * (1 + rng.uniform(-speed_jitter, speed_jitter))
        p = AgentSpec(f"P{i+1}", "pedestrian", 0.5, pedestrian_width, speed, 1.2, 2.0,
                      lateral_speed, 1.0, -1, 1, lane_y, 70 * mass_scale,
                      encounter_speed=1.0)
        agents.append(AgentState(p, 16.0 + initial_gap + i * pedestrian_spacing, lane_y, speed))
    return Scenario("bottleneck" if bottleneck else "corridor", road, agents, c, seed,
                    {"width": width, "centered_vehicle": centered_vehicle,
                     "vehicle_lateral_speed": vehicle_lateral_speed,
                     "initial_gap": initial_gap, "speed_jitter": speed_jitter})


def load_scenario(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    settings = Settings(**data.get("settings", {}))
    if "agents" not in data:
        factory = ring if data.get("type") in ("ring", "circle_crossing") else corridor
        return factory(settings=settings, **data.get("scenario", {}))
    road = Road(data["road"]["length"], tuple(tuple(p) for p in data["road"]["profile"]), data["road"].get("periodic", False))
    agents = []
    for row in data["agents"]:
        p = AgentSpec(**row["spec"])
        agents.append(AgentState(p, **row["state"]))
    return Scenario(data.get("name", "custom"), road, agents, settings, data.get("seed", 0))


def periodic_corridor(width=3.2, circumference=80.0, duration=180.0, settings=None, **kwargs):
    if circumference < 60:
        raise ValueError("Default initial layout needs circumference >=60 m")
    c = replace(settings or Settings(), max_time=duration)
    scenario = corridor(width=width, settings=c, **kwargs)
    scenario.road = Road(circumference, ((0.0, width), (circumference, width)), periodic=True)
    scenario.name = "ring"
    scenario.metadata.update({"topology": "periodic_unrolled_strip", "circumference_m": circumference,
                              "duration_s": duration, "rigid_body_curvature": False})
    return scenario


def ring(**kwargs):
    """Alternating agents on a circle crossing to antipodal destinations."""
    from .radial import circle_crossing
    return circle_crossing(**kwargs)
