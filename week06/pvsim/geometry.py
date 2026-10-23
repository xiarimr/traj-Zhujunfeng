"""Physical rectangle envelopes and continuous checks for linear timestep paths."""
import math


def separation(a, b):
    dx = max(abs(a.x - b.x) - (a.spec.length + b.spec.length) / 2, 0.0)
    dy = max(abs(a.y - b.y) - (a.spec.width + b.spec.width) / 2, 0.0)
    return math.hypot(dx, dy)


def swept_contact(a0, a1, b0, b1):
    """First contact fraction in [0,1], or None; touching counts as contact."""
    enter, leave = 0.0, 1.0
    for c0, c1, radius in (
        (a0.x - b0.x, a1.x - b1.x, (a0.spec.length + b0.spec.length) / 2),
        (a0.y - b0.y, a1.y - b1.y, (a0.spec.width + b0.spec.width) / 2),
    ):
        delta = c1 - c0
        if abs(delta) < 1e-14:
            if abs(c0) > radius:
                return None
        else:
            t0, t1 = sorted(((-radius - c0) / delta, (radius - c0) / delta))
            enter, leave = max(enter, t0), min(leave, t1)
            if enter > leave:
                return None
    return enter if enter <= 1 and leave >= 0 else None


def swept_separation(a0, a1, b0, b1):
    """Exact minimum Euclidean rectangle separation on a linear segment."""
    bases = [a0.x - b0.x, a0.y - b0.y]
    changes = [(a1.x - b1.x) - bases[0], (a1.y - b1.y) - bases[1]]
    radii = [(a0.spec.length + b0.spec.length) / 2, (a0.spec.width + b0.spec.width) / 2]
    cuts = {0.0, 1.0}
    for z, d, r in zip(bases, changes, radii):
        if abs(d) > 1e-14:
            for v in (-r, 0.0, r):
                t = (v - z) / d
                if 0 < t < 1:
                    cuts.add(t)
    cuts = sorted(cuts)
    def distance2(t):
        return sum(max(abs(z + d * t) - r, 0.0) ** 2 for z, d, r in zip(bases, changes, radii))
    best = min(distance2(t) for t in cuts)
    for lo, hi in zip(cuts, cuts[1:]):
        mid = (lo + hi) / 2
        aa, ab = 0.0, 0.0
        for z, d, r in zip(bases, changes, radii):
            v = z + d * mid
            if abs(v) > r:
                sign = 1.0 if v > 0 else -1.0
                intercept, slope = sign * z - r, sign * d
                aa += slope * slope
                ab += intercept * slope
        if aa > 0:
            t = max(lo, min(hi, -ab / aa))
            best = min(best, distance2(t))
    return math.sqrt(best)


def wall_gap(road, a):
    width = road.min_width(a.x - a.spec.length / 2, a.x + a.spec.length / 2)
    return width / 2 - abs(a.y) - a.spec.width / 2


def swept_wall_gap(road, a0, a1):
    """Exact minimum for piecewise-linear symmetric walls and linear motion."""
    fractions = {0.0, 1.0}
    dx = a1.x - a0.x
    if abs(dx) > 1e-14:
        for knot, _ in road.profile:
            for offset in (-a0.spec.length / 2, a0.spec.length / 2):
                t = (knot - a0.x - offset) / dx
                if 0 < t < 1:
                    fractions.add(t)
    minimum = float("inf")
    for t in fractions:
        x = a0.x + dx * t
        y = a0.y + (a1.y - a0.y) * t
        width = road.min_width(x - a0.spec.length / 2, x + a0.spec.length / 2)
        minimum = min(minimum, width / 2 - abs(y) - a0.spec.width / 2)
    return minimum
