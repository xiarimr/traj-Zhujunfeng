"""Fixed-heading oriented rectangles; continuous SAT for linear translations."""
import math


def basis(angle):
    return (math.cos(angle), math.sin(angle)), (-math.sin(angle), math.cos(angle))


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def support(spec, angle, axis):
    e, n = basis(angle)
    return abs(dot(e, axis)) * spec.length / 2 + abs(dot(n, axis)) * spec.width / 2


def axes(ha, hb):
    return (*basis(ha), *basis(hb))


def projected_gap(a, b, ha, hb):
    """SAT separation lower bound, not exact Euclidean clearance."""
    delta = (a.x - b.x, a.y - b.y)
    return max(abs(dot(delta, axis)) - support(a.spec, ha, axis) - support(b.spec, hb, axis)
               for axis in axes(ha, hb))


def swept_obb_contact(a, an, b, bn, ha, hb):
    enter, leave = 0.0, 1.0
    delta = (a.x - b.x, a.y - b.y)
    change = (an.x - bn.x - delta[0], an.y - bn.y - delta[1])
    for axis in axes(ha, hb):
        z, dz = dot(delta, axis), dot(change, axis)
        radius = support(a.spec, ha, axis) + support(b.spec, hb, axis)
        if abs(dz) < 1e-12:
            if abs(z) > radius:
                return None
        else:
            lo, hi = sorted(((-radius - z) / dz, (radius - z) / dz))
            enter, leave = max(enter, lo), min(leave, hi)
            if enter > leave:
                return None
    return max(0.0, enter) if enter <= 1 and leave >= 0 else None


def swept_gap_bound(a, an, b, bn, ha, hb):
    """Conservative whole-step clearance: starting SAT gap minus relative travel."""
    distance = math.hypot((an.x-a.x)-(bn.x-b.x), (an.y-a.y)-(bn.y-b.y))
    return max(0.0, projected_gap(a, b, ha, hb) - distance)
