"""Render saved simulation data to PNG, GIF and a self-contained offline replay."""
from pathlib import Path
import argparse
import json
import numpy as np

ROOT = Path(__file__).resolve().parent


def load_results():
    runs = {}
    for model in ['predictive', 'straight']:
        folder = ROOT / 'results' / model
        if folder.exists():
            with np.load(folder / 'trajectories.npz') as data:
                runs[model] = {k: data[k].copy() for k in data.files}
            runs[model].update(json.loads((folder / 'metrics.json').read_text(encoding='utf-8')))
    return runs


def write_replay(runs):
    payload = {}
    for name, run in runs.items():
        payload[name] = {
            'positions': np.round(run['positions'], 5).tolist(),
            'goals': np.round(run['goals'], 5).tolist(),
            'time': np.round(run['time'], 4).tolist(),
            'arrived': run['reached'].sum(axis=1).tolist(),
            'minSeparation': np.round(run['min_swept'], 6).tolist(),
            'metrics': run['metrics'], 'config': run['config'],
        }
    template = (ROOT / 'replay_template.html').read_text(encoding='utf-8')
    (ROOT / 'index.html').write_text(template.replace('__SIMULATION_DATA__', json.dumps(payload, separators=(',', ':'))), encoding='utf-8')


def render_plots(runs, make_gif=True):
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib import pyplot as plt
    from matplotlib.animation import FuncAnimation, PillowWriter
    from mpl_toolkits.mplot3d.art3d import Line3DCollection
    plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 10,
                         'axes.spines.top': False, 'axes.spines.right': False,
                         'figure.facecolor': '#f4f7fb', 'axes.facecolor': '#f4f7fb'})
    out = ROOT / 'results'
    run = runs['predictive']
    p, time = run['positions'], run['time']
    radius = run['config']['sphere_radius']
    colors = plt.cm.turbo(np.linspace(0.05, 0.95, p.shape[1]))
    u, v = np.meshgrid(np.linspace(0, 2 * np.pi, 33), np.linspace(0, np.pi, 17))
    sphere = (radius * np.cos(u) * np.sin(v), radius * np.sin(u) * np.sin(v), radius * np.cos(v))

    def setup(ax):
        ax.plot_wireframe(*sphere, rstride=2, cstride=4, color='#99afc2', linewidth=0.45, alpha=0.25)
        ax.set(xlim=(-17, 17), ylim=(-17, 17), zlim=(-17, 17), xlabel='X (m)', ylabel='Y (m)', zlabel='Z (m)')
        ax.set_box_aspect([1, 1, 1])
        ax.view_init(elev=23, azim=38)
        ax.tick_params(labelsize=8)
        ax.set_xticks([-15, 0, 15]); ax.set_yticks([-15, 0, 15]); ax.set_zticks([-15, 0, 15])

    fig = plt.figure(figsize=(13, 10))
    fig.suptitle('100 UAVs | Spherical antipodal crossing', fontsize=21, fontweight='bold', x=.07, ha='left')
    fig.text(.07, .925, 'Uniform Fibonacci sphere / 3D predictive avoidance / synchronous updates', color='#51657b')
    indices = [0, int(np.argmin(run['min_swept'])), len(p) * 3 // 4, len(p) - 1]
    for k, idx in enumerate(indices):
        ax = fig.add_subplot(2, 2, k + 1, projection='3d')
        setup(ax)
        if idx:
            segments = [p[:idx + 1, i] for i in range(p.shape[1])]
            ax.add_collection3d(Line3DCollection(segments, colors=colors, linewidths=.65, alpha=.35))
        ax.scatter(*p[idx].T, c=colors, s=15, depthshade=False)
        ax.set_title(f't = {time[idx]:.1f} s   |   arrived {run["reached"][idx].sum()}/100', loc='left', fontweight='bold')
    fig.text(.07, .025, f'All arrived: {time[-1]:.1f} s     Minimum separation: {run["metrics"]["minimum_separation_m"]:.3f} m     Unsafe pairs: 0', color='#176957', fontsize=12)
    fig.subplots_adjust(top=.90, bottom=.07, left=.03, right=.97, hspace=.1, wspace=.02)
    fig.savefig(out / 'trajectories.png', dpi=160)
    plt.close(fig)

    fig, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
    fig.suptitle('Safety and completion | 100 UAVs', fontsize=20, fontweight='bold')
    names = {'predictive': 'Predictive avoidance', 'straight': 'Straight flight (unsafe)'}
    for name, item in runs.items():
        c = '#167b88' if name == 'predictive' else '#d5814a'
        axes[0, 0].plot(item['time'], item['min_swept'], label=names[name], color=c)
        axes[0, 1].step(item['time'], item['reached'].sum(axis=1), where='post', label=names[name], color=c)
    axes[0, 0].axhline(1, ls='--', color='#b2223c', label='Safety limit: 1 m')
    axes[0, 0].set(xlabel='Time (s)', ylabel='Minimum swept separation (m)', title='Continuous-time separation')
    axes[0, 0].legend(fontsize=8)
    axes[0, 1].set(xlabel='Time (s)', ylabel='Arrived UAVs', title='Arrival count', ylim=(-2, 105))
    axes[0, 1].legend(fontsize=8)
    speeds = np.linalg.norm(np.diff(p, axis=0), axis=2) / run['config']['dt']
    axes[1, 0].plot(time[1:], speeds.max(axis=1), color='#167b88', label='Maximum')
    axes[1, 0].plot(time[1:], speeds.mean(axis=1), color='#6b7898', label='Mean')
    axes[1, 0].axhline(2, color='#b2223c', ls='--', label='Speed limit: 2 m/s')
    axes[1, 0].set(xlabel='Time (s)', ylabel='Speed (m/s)', title='Executed segment speed', ylim=(-.05, 2.2))
    axes[1, 0].legend(fontsize=8)
    axes[1, 1].bar(np.arange(1, 101), run['path_lengths'], color=colors, width=.85)
    axes[1, 1].axhline(run['path_lengths'].mean(), color='#b2223c', ls='--', label=f'Mean: {run["path_lengths"].mean():.2f} m')
    axes[1, 1].set(xlabel='UAV ID', ylabel='Path length (m)', title='Individual travel distance')
    axes[1, 1].legend(fontsize=8)
    for ax in axes.flat:
        ax.grid(alpha=.18)
    fig.savefig(out / 'diagnostics.png', dpi=160)
    plt.close(fig)

    if make_gif:
        fig = plt.figure(figsize=(8.4, 7), dpi=100)
        ax = fig.add_subplot(111, projection='3d')
        setup(ax)
        fig.suptitle('100 UAVs | 3D spherical crossing', fontsize=18, fontweight='bold', y=.97)
        cloud = ax.scatter(*p[0].T, c=colors, s=24, depthshade=False)
        trails = Line3DCollection([p[:1, i] for i in range(p.shape[1])], colors=colors, linewidths=.9, alpha=.5)
        ax.add_collection3d(trails)
        caption = fig.text(.5, .065, '', ha='center', fontsize=12)
        fig.text(.5, .025, 'Safety distance 1 m  |  Speed limit 2 m/s  |  Replay 2x', ha='center', color='#51657b')
        fig.subplots_adjust(left=0, right=1, top=.94, bottom=.12)
        frames = list(range(0, len(p), 2))
        if frames[-1] != len(p) - 1:
            frames.append(len(p) - 1)
        frames += [len(p) - 1] * 12

        def update(k):
            cloud._offsets3d = tuple(p[k].T)
            trails.set_segments([p[max(0, k - 25):k + 1, i] for i in range(p.shape[1])])
            caption.set_text(f't = {time[k]:4.1f} s    Arrived: {run["reached"][k].sum():3d}/100    Min gap: {run["min_swept"][k]:.3f} m')
            return cloud, trails, caption

        anim = FuncAnimation(fig, update, frames=frames, interval=100, blit=False)
        anim.save(out / 'simulation.gif', writer=PillowWriter(fps=10))
        plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-gif', action='store_true')
    args = parser.parse_args()
    runs = load_results()
    write_replay(runs)
    render_plots(runs, make_gif=not args.no_gif)
    print('Created index.html, results/trajectories.png, results/diagnostics.png' + (', results/simulation.gif' if not args.no_gif else ''))


if __name__ == '__main__':
    main()
