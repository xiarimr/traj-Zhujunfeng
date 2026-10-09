"""比较其他车道、100米路段。python code/compare_lanes_segments.py --t 10 60"""
import argparse
import json
from pathlib import Path

from fundamental_diagram import aggregate, clip_segments, plt, np, pd, ROOT


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--t', type=float, nargs='+', default=[10, 60])
    args = p.parse_args()
    if any(not np.isfinite(t) or t < .1 for t in args.t):
        p.error('t must be finite and >= 0.1 seconds')
    out = ROOT / 'archive' / 'other_lanes_recomputed'
    out.mkdir(parents=True, exist_ok=True)
    original = json.loads((ROOT / 'results/scope_config.json').read_text(encoding='utf-8'))
    data = pd.read_csv(ROOT / original['source'], usecols=['vehicle_id', 'frame_id', 'time_s', 'local_y_m', 'lane_id'])
    start, end = float(data.time_s.min()), float(data.time_s.max())
    tables, summaries = [], []
    for lane in range(1, 7):
        # 保留所有可能在目标车道出现车辆的完整轨迹，避免丢失换道和空间边界邻点。
        ids = data.loc[data.lane_id == lane, 'vehicle_id'].unique()
        subset = data.loc[data.vehicle_id.isin(ids)]
        for y in [100, 200, 300]:
            cfg = dict(original, lane_id=lane, spatial_start_m_inclusive=y, spatial_end_m_exclusive=y + 100)
            seg, _ = clip_segments(subset, cfg)
            for t in dict.fromkeys(args.t):
                a = aggregate(seg, t, start, end, 100)
                a['lane_id'], a['segment_start_m'], a['segment_end_m'] = lane, y, y + 100
                tables.append(a)
                k, q, v = a.density_veh_km, a.flow_veh_h, a.speed_km_h
                slope, intercept = np.polyfit(k, q, 1) if k.std() > 1e-10 else (np.nan, np.nan)
                summaries.append({'lane_id': lane, 'start_m': y, 'end_m': y + 100, 't_s': t,
                                  'windows': len(a), 'k_min': k.min(), 'k_max': k.max(),
                                  'q_min': q.min(), 'q_max': q.max(), 'v_min_km_h': v.min(),
                                  'v_max_km_h': v.max(), 'corr_k_q': k.corr(q),
                                  'ols_slope': slope, 'ols_intercept': intercept})
        print(f'Lane {lane} complete', flush=True)
    all_data = pd.concat(tables, ignore_index=True)
    summary = pd.DataFrame(summaries)
    all_data.to_csv(out / 'all_windows.csv', index=False, encoding='utf-8-sig')
    summary.to_csv(out / 'summary.csv', index=False, encoding='utf-8-sig')
    kmax = np.ceil(all_data.density_veh_km.max() * 1.08 / 10) * 10
    qmax = np.ceil(all_data.flow_veh_h.max() * 1.08 / 100) * 100
    vmax = max(60, np.ceil(all_data.speed_km_h.max() / 10) * 10)
    for t in dict.fromkeys(args.t):
        fig, axes = plt.subplots(6, 3, figsize=(12, 18), sharex=True, sharey=True, layout='constrained')
        for lane in range(1, 7):
            for j, y in enumerate([100, 200, 300]):
                ax = axes[lane - 1, j]
                a = all_data[(all_data.lane_id == lane) & (all_data.segment_start_m == y) & (all_data.requested_t_s == t)]
                # 等速射线 q=v*k；各面板同坐标，颜色显示各窗口的时空平均速度。
                for speed in [20, 40, 60]:
                    x = np.array([0, min(kmax, qmax / speed)])
                    ax.plot(x, speed * x, color='0.7', lw=.7, ls='--', zorder=0)
                sc = ax.scatter(a.density_veh_km, a.flow_veh_h, c=a.speed_km_h,
                                cmap='viridis', vmin=0, vmax=vmax, s=18, alpha=.85)
                r = summary[(summary.lane_id == lane) & (summary.start_m == y) & (summary.t_s == t)].iloc[0]
                ax.set_title(f'Lane {lane}, {y}-{y+100} m | r={r.corr_k_q:.2f}', fontsize=10)
                ax.set_xlim(0, kmax)
                ax.set_ylim(0, qmax)
                ax.grid(alpha=.2)
                if j == 0:
                    ax.set_ylabel('Flow (veh/h/lane)')
                if lane == 6:
                    ax.set_xlabel('Density (veh/km/lane)')
        fig.colorbar(sc, ax=axes, label='Space-time mean speed (km/h)', shrink=.7)
        fig.suptitle(f'I-80 eastbound | T={t:g} s | dashed rays: 20, 40, 60 km/h', fontsize=15)
        fig.savefig(out / f'comparison_T{t:g}s.png', dpi=160)
        fig.savefig(out / f'comparison_T{t:g}s.svg')
        plt.close(fig)
    # 简明对照：同一路段车道1、2、4，每行一个时间窗口长度。
    fig, axes = plt.subplots(len(set(args.t)), 3, figsize=(13, 4 * len(set(args.t))),
                             sharex=True, sharey=True, squeeze=False, layout='constrained')
    for i, t in enumerate(dict.fromkeys(args.t)):
        for j, lane in enumerate([1, 2, 4]):
            ax = axes[i, j]
            a = all_data[(all_data.requested_t_s == t) & (all_data.lane_id == lane) & (all_data.segment_start_m == 200)]
            for speed in [20, 40, 60, 80]:
                x = np.array([0, min(kmax, qmax / speed)])
                ax.plot(x, speed * x, color='0.75', lw=.7, ls='--')
                ax.text(x[1], speed * x[1], str(speed), fontsize=7, ha='right', va='top', color='0.5')
            sc = ax.scatter(a.density_veh_km, a.flow_veh_h, c=a.speed_km_h,
                            vmin=0, vmax=vmax, cmap='viridis', s=27)
            ax.set_xlim(0, kmax)
            ax.set_ylim(0, qmax)
            ax.set_title(f'Lane {lane} | T={t:g} s')
            ax.grid(alpha=.2)
            if j == 0:
                ax.set_ylabel('Flow (veh/h/lane)')
            if i == len(set(args.t)) - 1:
                ax.set_xlabel('Density (veh/km/lane)')
    fig.colorbar(sc, ax=axes, label='Space-time mean speed (km/h)', shrink=.8)
    fig.suptitle('I-80 eastbound | 200-300 m | dashed rays: constant speed (km/h)')
    fig.savefig(out / 'selected_comparison.png', dpi=170)
    plt.close(fig)
    metadata = {'lanes': list(range(1, 7)), 'segments_m': [[100, 200], [200, 300], [300, 400]],
                'window_s': args.t, 'axis_k_max': float(kmax), 'axis_q_max': float(qmax),
                'time_end_s': end, 'original_scope_preserved': True,
                'note': 'OLS slope describes this sample only, not free-flow speed or capacity. Lane 7 not included because its observed longitudinal coverage is only about 82-203 m.'}
    (out / 'comparison_metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    print(summary.round(3).to_string(index=False))


if __name__ == '__main__':
    main()
