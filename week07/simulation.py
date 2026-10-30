"""100 UAVs: uniform spherical starts, antipodal goals, synchronous 3-D motion.

Only NumPy is required for simulation. Distances are centre-to-centre, in metres.
"""
from dataclasses import asdict, dataclass
from pathlib import Path
import argparse
import csv
import json
import numpy as np


@dataclass
class Config:
    count: int = 100
    sphere_radius: float = 15.0
    body_radius: float = 0.5
    max_speed: float = 2.0
    dt: float = 0.1
    time_limit: float = 120.0
    horizon: float = 5.0
    goal_tolerance: float = 1.0
    safety_margin: float = 0.02
    swirl_speed: float = 1.2


def fibonacci_sphere(n, radius):
    """Equal-area z bands and golden-angle longitudes; no discrete latitude rings."""
    k = np.arange(n, dtype=float)
    z = 1 - 2 * (k + 0.5) / n
    phi = k * np.pi * (3 - np.sqrt(5))
    r = np.sqrt(1 - z * z)
    return radius * np.column_stack((r * np.cos(phi), r * np.sin(phi), z))


def limit_speed(v, vmax):
    return v / np.maximum(1.0, np.linalg.norm(v, axis=1) / vmax)[:, None]


def desired_velocity(p, goals, stopped, cfg):
    delta = goals - p
    distance = np.linalg.norm(delta, axis=1)
    v = delta / np.maximum(distance[:, None], 1e-12) * cfg.max_speed
    v[stopped] = 0
    return v


def preferred_velocity(p, goals, stopped, cfg, pair_i, pair_j):
    """Goal attraction + central circulation + pairwise predictive avoidance.

    tau is a collision prediction horizon, NOT an acceleration time constant.
    The circulation breaks the otherwise symmetric head-on deadlock.
    """
    goal_v = desired_velocity(p, goals, stopped, cfg)
    radial = np.linalg.norm(p, axis=1)
    axis = np.array([0.31, -0.22, 0.925])
    axis /= np.linalg.norm(axis)
    tangent = np.cross(np.broadcast_to(axis, p.shape), p)
    tangent /= np.maximum(np.linalg.norm(tangent, axis=1)[:, None], 1e-12)
    # Smoothly vanishes near each goal, preserving the exact stop condition.
    goal_dist = np.linalg.norm(goals - p, axis=1)
    swirl = cfg.swirl_speed * np.exp(-(radial / (0.7 * cfg.sphere_radius)) ** 4)
    swirl *= np.clip((goal_dist - cfg.goal_tolerance) / 4, 0, 1)
    v = limit_speed(goal_v + swirl[:, None] * tangent, cfg.max_speed)
    v[stopped] = 0

    r = p[pair_i] - p[pair_j]
    w = v[pair_i] - v[pair_j]
    ww = np.sum(w * w, axis=1)
    t = np.clip(-np.sum(r * w, axis=1) / np.maximum(ww, 1e-12), 0, cfg.horizon)
    closest = r + t[:, None] * w
    sep = np.linalg.norm(closest, axis=1)
    predicted = (t > 0) & (sep < 2.0) & (np.sum(r * w, axis=1) < 0)
    correction = np.zeros_like(v)
    for k in np.flatnonzero(predicted):
        normal = closest[k]
        norm = sep[k]
        if norm < 1e-8:
            normal = np.cross(r[k], axis)
            if np.linalg.norm(normal) < 1e-8:
                normal = np.cross(r[k], np.array([1., 0., 0.]))
            norm = np.linalg.norm(normal)
        normal = normal / max(norm, 1e-12)
        push = min(1.0, (2.0 - sep[k]) / max(t[k], 0.5)) * normal
        i, j = pair_i[k], pair_j[k]
        correction[i] += push * (1.0 if stopped[j] else 0.5)
        correction[j] -= push * (1.0 if stopped[i] else 0.5)
    v = limit_speed(v + correction, cfg.max_speed)
    v[stopped] = 0
    return v


def safety_filter(p, v, stopped, cfg, pair_i, pair_j):
    """Project velocities onto linear separation constraints and speed balls.

    n_ij . (v_i-v_j) >= -(d_ij-d_safe)/dt.
    Thus the projection of the relative position onto its OLD normal remains
    >= d_safe throughout the whole straight integration segment. All pairs
    capable of reaching d_safe in this step are included, even stationary UAVs.
    Iterative velocity changes are internal solver steps; positions update once.
    """
    safe = 2 * cfg.body_radius + cfg.safety_margin
    r = p[pair_i] - p[pair_j]
    d = np.linalg.norm(r, axis=1)
    keep = d < safe + 2 * cfg.max_speed * cfg.dt + 1e-8
    ii, jj = pair_i[keep], pair_j[keep]
    normals = r[keep] / d[keep, None]
    lower = -(d[keep] - safe) / cfg.dt
    if np.any(d < safe - 1e-7):
        raise RuntimeError('Unsafe input to velocity filter')
    for _ in range(80):
        violation = lower - np.sum(normals * (v[ii] - v[jj]), axis=1)
        if not len(violation) or np.max(violation) < 1e-10:
            break
        for k in np.flatnonzero(violation > 1e-10):
            i, j = ii[k], jj[k]
            missing = lower[k] - np.dot(normals[k], v[i] - v[j])
            if missing <= 0:
                continue
            movable = int(not stopped[i]) + int(not stopped[j])
            if not movable:
                raise RuntimeError('Two stopped agents violate safety')
            change = missing / movable * normals[k]
            if not stopped[i]:
                v[i] += change
            if not stopped[j]:
                v[j] -= change
        v = limit_speed(v, cfg.max_speed)
        v[stopped] = 0
    # Zero velocity is feasible. Uniform scaling resolves any residual solver
    # error without teleporting agents, breaking speed limits, or moving arrivals.
    relative = np.sum(normals * (v[ii] - v[jj]), axis=1)
    violated = relative < lower
    scale = 1.0
    if np.any(violated):
        scale = max(0.0, float(np.min(lower[violated] / relative[violated])))
        v *= scale * (1 - 1e-10)
    return v, scale


def swept_distances(old, new, ii, jj):
    """Exact pair minima over a synchronous, piecewise-linear time step."""
    r = old[ii] - old[jj]
    dr = (new[ii] - new[jj]) - r
    u = np.clip(-np.sum(r * dr, axis=1) / np.maximum(np.sum(dr * dr, axis=1), 1e-30), 0, 1)
    return np.linalg.norm(r + u[:, None] * dr, axis=1)


def simulate(cfg, model='predictive'):
    if cfg.count < 2 or min(cfg.sphere_radius, cfg.dt, cfg.max_speed, cfg.horizon) <= 0:
        raise ValueError('Invalid count or nonpositive physical parameters')
    p = fibonacci_sphere(cfg.count, cfg.sphere_radius)
    starts = p.copy()
    goals = -starts
    ii, jj = np.triu_indices(cfg.count, 1)
    initial_min = float(np.min(np.linalg.norm(p[ii] - p[jj], axis=1)))
    if initial_min < 2 * cfg.body_radius + cfg.safety_margin:
        raise ValueError('Initial sphere is too small for the requested population')
    stopped = np.linalg.norm(goals - p, axis=1) <= cfg.goal_tolerance
    arrival = np.full(cfg.count, np.nan)
    arrival[stopped] = 0
    positions = [p.copy()]
    velocities = [np.zeros_like(p)]  # v(0) = 0; no acceleration constraint.
    reached = [stopped.copy()]
    min_dist = [initial_min]
    min_swept = [initial_min]
    violations = np.zeros(len(ii), dtype=bool)
    path_length = np.zeros(cfg.count)
    filter_scales = []
    for step in range(1, int(round(cfg.time_limit / cfg.dt)) + 1):
        if model == 'predictive':
            v = preferred_velocity(p, goals, stopped, cfg, ii, jj)
            v, scale = safety_filter(p, v, stopped, cfg, ii, jj)
            filter_scales.append(scale)
        elif model == 'straight':
            v = desired_velocity(p, goals, stopped, cfg)
        else:
            raise ValueError(model)
        new = p + cfg.dt * v
        swept = swept_distances(p, new, ii, jj)
        violations |= swept < 2 * cfg.body_radius - 1e-9
        path_length += np.linalg.norm(new - p, axis=1)
        p = new
        new_arrivals = ~stopped & (np.linalg.norm(goals - p, axis=1) <= cfg.goal_tolerance + 1e-12)
        arrival[new_arrivals] = step * cfg.dt
        stopped |= new_arrivals
        # velocities[k] denotes the physical state just after sample k.
        # Newly arrived UAVs stop here; incoming segment speed is recovered from p.
        v[stopped] = 0
        positions.append(p.copy())
        velocities.append(v.copy())
        reached.append(stopped.copy())
        min_dist.append(float(np.min(np.linalg.norm(p[ii] - p[jj], axis=1))))
        min_swept.append(float(np.min(swept)))
        if np.all(stopped):
            break
    positions = np.asarray(positions)
    segment_speed = np.linalg.norm(np.diff(positions, axis=0), axis=2) / cfg.dt
    metrics = {
        'model': model,
        'count': cfg.count,
        'arrived': int(np.sum(stopped)),
        'arrival_rate': float(np.mean(stopped)),
        'all_arrival_time_s': float(np.nanmax(arrival)) if np.all(stopped) else None,
        'simulated_time_s': (len(positions) - 1) * cfg.dt,
        'minimum_separation_m': float(min(min_swept)),
        'minimum_sampled_separation_m': float(min(min_dist)),
        'violating_pair_count': int(np.sum(violations)),
        'max_speed_m_s': float(np.max(segment_speed)) if len(segment_speed) else 0.0,
        'mean_path_length_m': float(np.mean(path_length)),
        'max_final_goal_error_m': float(np.max(np.linalg.norm(p - goals, axis=1))),
        'initial_minimum_separation_m': initial_min,
        'initial_nearest_neighbor_cv': nearest_neighbor_cv(starts),
        'filter_scaling_steps': int(np.sum(np.asarray(filter_scales) < 0.999999)),
    }
    return dict(config=asdict(cfg), metrics=metrics, positions=positions,
                velocities=np.asarray(velocities), reached=np.asarray(reached),
                starts=starts, goals=goals, arrival_times=arrival, path_lengths=path_length,
                time=np.arange(len(positions)) * cfg.dt,
                min_separation=np.asarray(min_dist), min_swept=np.asarray(min_swept))


def nearest_neighbor_cv(p):
    d = np.linalg.norm(p[:, None, :] - p[None, :, :], axis=2)
    np.fill_diagonal(d, np.inf)
    nearest = d.min(axis=1)
    return float(nearest.std() / nearest.mean())


def save_result(result, directory):
    directory.mkdir(parents=True, exist_ok=True)
    arrays = {k: v for k, v in result.items() if isinstance(v, np.ndarray)}
    np.savez_compressed(directory / 'trajectories.npz', **arrays)
    (directory / 'metrics.json').write_text(json.dumps(
        dict(config=result['config'], metrics=result['metrics']), indent=2, ensure_ascii=False), encoding='utf-8')
    with (directory / 'trajectories.csv').open('w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['time_s', 'uav_id', 'x_m', 'y_m', 'z_m', 'vx_m_s', 'vy_m_s', 'vz_m_s', 'arrived'])
        for k, t in enumerate(result['time']):
            for i, (p, v) in enumerate(zip(result['positions'][k], result['velocities'][k])):
                writer.writerow([round(float(t), 6), i + 1, *np.round(p, 8), *np.round(v, 8), int(result['reached'][k, i])])
    with (directory / 'per_uav.csv').open('w', encoding='utf-8', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['uav_id', 'arrival_time_s', 'path_length_m', 'final_goal_error_m'])
        errors = np.linalg.norm(result['positions'][-1] - result['goals'], axis=1)
        for i in range(len(errors)):
            writer.writerow([i + 1, result['arrival_times'][i], result['path_lengths'][i], errors[i]])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path(__file__).parent / 'results')
    parser.add_argument('--radius', type=float, default=15.0)
    parser.add_argument('--dt', type=float, default=0.1)
    parser.add_argument('--baseline', action='store_true', help='Also save straight-flight failure reference')
    args = parser.parse_args()
    cfg = Config(sphere_radius=args.radius, dt=args.dt)
    all_metrics = []
    for model in (['predictive', 'straight'] if args.baseline else ['predictive']):
        result = simulate(cfg, model)
        save_result(result, args.output / model)
        all_metrics.append(result['metrics'])
        print(json.dumps(result['metrics'], indent=2), flush=True)
    with (args.output / 'comparison.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=all_metrics[0].keys())
        writer.writeheader()
        writer.writerows(all_metrics)


if __name__ == '__main__':
    main()
