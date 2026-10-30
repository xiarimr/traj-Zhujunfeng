"""Independent trajectory checks, inter-sample collision test, timestep check."""
from pathlib import Path
import json
import numpy as np
from simulation import Config, simulate, swept_distances

ROOT = Path(__file__).resolve().parent


def verify(run):
    cfg = run['config']
    p, reached = run['positions'], run['reached']
    n, dt = cfg['count'], cfg['dt']
    assert p.shape[1:] == (100, 3)
    assert np.all(np.isfinite(p))
    assert np.allclose(np.linalg.norm(p[0], axis=1), cfg['sphere_radius'])
    assert np.allclose(run['goals'], -p[0])
    assert np.all(run['velocities'][0] == 0)
    step = np.diff(p, axis=0)
    speeds = np.linalg.norm(step, axis=2) / dt
    assert speeds.max() <= cfg['max_speed'] + 1e-9
    assert np.all(reached[-1])
    assert run['time'][-1] <= cfg['time_limit']
    assert np.all(np.diff(reached.astype(int), axis=0) >= 0)
    for i in range(n):
        arrived = np.flatnonzero(reached[:, i])[0]
        assert np.linalg.norm(p[arrived, i] - run['goals'][i]) <= cfg['goal_tolerance'] + 1e-9
        assert np.all(p[arrived:, i] == p[arrived, i])
        assert np.all(run['velocities'][arrived:, i] == 0)
        if arrived:
            assert np.all(np.linalg.norm(p[:arrived, i] - run['goals'][i], axis=1) > cfg['goal_tolerance'] - 1e-9)
    # Different implementation from swept_distances: quadratic minimization
    # using relative velocities, in seconds, batched over all saved time steps.
    minimum = float('inf')
    violating = 0
    for i in range(n):
        for j in range(i + 1, n):
            relative = p[:-1, i] - p[:-1, j]
            velocity = (step[:, i] - step[:, j]) / dt
            square_speed = np.einsum('ij,ij->i', velocity, velocity)
            closest_t = np.clip(-np.einsum('ij,ij->i', relative, velocity) / np.maximum(square_speed, 1e-30), 0, dt)
            closest = relative + closest_t[:, None] * velocity
            pair_min = float(np.sqrt(np.min(np.einsum('ij,ij->i', closest, closest))))
            minimum = min(minimum, pair_min)
            violating += pair_min < 2 * cfg['body_radius'] - 1e-9
    assert minimum >= 2 * cfg['body_radius'] - 1e-9
    assert abs(minimum - run['metrics']['minimum_separation_m']) < 1e-8
    assert violating == 0
    return {'passed': True, 'independent_min_separation_m': minimum,
            'checked_pairs': n * (n - 1) // 2, 'checked_intervals': len(p) - 1,
            'arrived': int(reached[-1].sum()), 'max_segment_speed_m_s': float(speeds.max())}


def main():
    folder = ROOT / 'results' / 'predictive'
    run = dict(np.load(folder / 'trajectories.npz'))
    run.update(json.loads((folder / 'metrics.json').read_text(encoding='utf-8')))
    checks = verify(run)
    # Endpoints are safe, but two moving agents collide between samples.
    old = np.array([[-2., 0, 0], [2., 0, 0]])
    new = old[::-1].copy()
    assert np.linalg.norm(old[0] - old[1]) == 4
    assert swept_distances(old, new, np.array([0]), np.array([1]))[0] == 0
    checks['inter_sample_crossing_test'] = 'passed'
    finer = simulate(Config(dt=0.05))
    checks['half_timestep_validation'] = verify(finer)
    checks['half_timestep_metrics'] = finer['metrics']
    # Saved metrics must agree with a deterministic replay of the same inputs.
    repeat = simulate(Config(**run['config']))
    assert np.array_equal(run['positions'], repeat['positions'])
    checks['deterministic_repeat'] = 'passed'
    (ROOT / 'results' / 'validation.json').write_text(json.dumps(checks, indent=2), encoding='utf-8')
    print(json.dumps(checks, indent=2))


if __name__ == '__main__':
    main()
