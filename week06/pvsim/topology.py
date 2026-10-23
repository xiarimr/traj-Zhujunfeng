"""Coordinate topology is independent from behavioral rules.

Ring means a periodic unrolled strip (s mod L, y), not a rigid-body curved-road
solver. The circular display maps its rectangular footprints to annular sectors.
"""
from dataclasses import replace


def neighbor_images(agent, agents, road):
    others = []
    for other in agents:
        if other.done or other.spec.id == agent.spec.id:
            continue
        if not road.periodic:
            others.append(other)
            continue
        if other.spec.direction == agent.spec.direction:
            front = (agent.spec.direction * (other.x - agent.x)) % road.length
            x = agent.x + agent.spec.direction * front
        else:
            delta = (other.x - agent.x + road.length / 2) % road.length - road.length / 2
            x = agent.x + delta
        others.append(replace(other, x=x))
    return others


def pair_images(a, b, bn, road):
    if not road.periodic:
        return [(b, bn)]
    nearest = round((a.x - b.x) / road.length)
    return [(replace(b, x=b.x + k * road.length), replace(bn, x=bn.x + k * road.length))
            for k in (nearest - 1, nearest, nearest + 1)]


def relative_front(a, b, road):
    delta = b.x - a.x
    if road.periodic:
        delta = (delta + road.length / 2) % road.length - road.length / 2
    return a.spec.direction * delta
