"""比较Edie、逐帧路段平均、断面计数与调和速度估计。读取当前主结果窗口。

python code/compare_density_methods.py
python code/compare_density_methods.py --t 10 30 60
"""
import argparse
import json

from fundamental_diagram import ROOT, np, pd, plt


def crossing_events(data, cfg):
    """线性插值穿越中点的时间及原始速度；按中点换道规则确定穿越车道。"""
    d = data.sort_values(['vehicle_id', 'time_s'])
    a, b = d.iloc[:-1], d.iloc[1:]
    t0, t1 = a.time_s.to_numpy(), b.time_s.to_numpy()
    y0, y1 = a.local_y_m.to_numpy(), b.local_y_m.to_numpy()
    x = (cfg['spatial_start_m_inclusive'] + cfg['spatial_end_m_exclusive']) / 2
    mask = ((a.vehicle_id.to_numpy() == b.vehicle_id.to_numpy()) &
            np.isclose(t1 - t0, cfg['nominal_sampling_interval_s'], atol=1e-7, rtol=0) &
            (y0 < x) & (y1 >= x))
    fraction = (x - y0[mask]) / (y1[mask] - y0[mask])
    lane = np.where(fraction < .5, a.lane_id.to_numpy()[mask], b.lane_id.to_numpy()[mask])
    speed = a.speed_m_s.to_numpy()[mask] + fraction * (b.speed_m_s.to_numpy()[mask] - a.speed_m_s.to_numpy()[mask])
    events = pd.DataFrame({'vehicle_id': a.vehicle_id.to_numpy()[mask],
                           'time_s': t0[mask] + fraction * (t1[mask] - t0[mask]),
                           'speed_m_s': speed, 'lane_id': lane})
    return events.loc[events.lane_id == cfg['lane_id']].copy()


def section_estimate(events, left, right):
    e = events.loc[(events.time_s >= left) & (events.time_s < right)]
    n = len(e)
    flow = 3600 * n / (right - left)
    # 无过车或非正过车速度时不能可靠反推密度，不用0伪装不可估计值。
    if n == 0 or (e.speed_m_s <= 0).any():
        return flow, np.nan, np.nan, n
    harmonic_kmh = 3.6 * n / (1 / e.speed_m_s).sum()
    return flow, flow / harmonic_kmh, harmonic_kmh, n


def self_check():
    events = pd.DataFrame({'time_s': [1., 3.], 'speed_m_s': [10., 20.]})
    q, k, v, n = section_estimate(events, 0, 10)
    assert n == 2 and np.isclose(q, 720) and np.isclose(v, 48) and np.isclose(k, 15)
    assert section_estimate(events, 10, 20)[0] == 0
    assert np.isnan(section_estimate(events, 10, 20)[1])
    cfg = {'lane_id': 1, 'spatial_start_m_inclusive': 200, 'spatial_end_m_exclusive': 300,
           'nominal_sampling_interval_s': .1}
    test = pd.DataFrame({'vehicle_id': [1, 1], 'time_s': [0., .1],
                         'local_y_m': [249.5, 250.5], 'lane_id': [2, 1], 'speed_m_s': [10., 10.]})
    e = crossing_events(test, cfg)
    assert len(e) == 1 and np.isclose(e.time_s.iloc[0], .05)


def expanded_figures(result, stats, out, kmax, qmax):
    """叠加图、一对一配对图、窗口敏感性和计数分布；不新增计算方法。"""
    available = list(result.requested_t_s.unique())
    focus = [t for t in [5, 20, 60] if t in available]
    if not focus:
        focus = available[:3]
    methods = ['Edie', 'Snapshot', 'Section']
    colors = dict(zip(methods, ['tab:blue', 'tab:orange', 'tab:green']))
    fig, axes = plt.subplots(3, len(focus), figsize=(5 * len(focus), 12), squeeze=False, layout='constrained')
    for j, t in enumerate(focus):
        edie = result[(result.method == 'Edie') & (result.requested_t_s == t)].set_index('window_index')
        for method in methods:
            a = result[(result.method == method) & (result.requested_t_s == t)].set_index('window_index')
            axes[0, j].scatter(a.density_veh_km, a.flow_veh_h, s=25, alpha=.65, color=colors[method], label=method)
            if method != 'Edie':
                for i, col in [(1, 'density_veh_km'), (2, 'flow_veh_h')]:
                    axes[i, j].scatter(edie[col], a[col], s=24, alpha=.65, color=colors[method], label=method)
        axes[0, j].set(xlim=(0, kmax), ylim=(0, qmax), xlabel='Density (veh/km/lane)', ylabel='Flow (veh/h/lane)', title=f'T={t:g}s | overlay')
        for i, limit, unit in [(1, kmax, 'Density (veh/km/lane)'), (2, qmax, 'Flow (veh/h/lane)')]:
            axes[i, j].plot([0, limit], [0, limit], '--', color='0.45', lw=1, label='1:1 agreement')
            axes[i, j].set(xlim=(0, limit), ylim=(0, limit), xlabel=f'Edie {unit}', ylabel=f'Alternative {unit}', title=f'T={t:g}s | paired windows')
        for ax in axes[:, j]:
            ax.grid(alpha=.2)
            ax.legend(fontsize=8)
    fig.suptitle('Methods: overlapping point clouds and same-window agreement')
    fig.savefig(out / 'method_agreement.png', dpi=180)
    plt.close(fig)

    fig, axes = plt.subplots(2, 2, figsize=(12, 8), layout='constrained')
    for method in ['Snapshot', 'Section']:
        a = stats[stats.method == method].sort_values('t_s')
        for ax, col, unit in [(axes[0, 0], 'k_mae_vs_edie', 'Density MAE vs Edie (veh/km)'),
                              (axes[0, 1], 'q_mae_vs_edie', 'Flow MAE vs Edie (veh/h)')]:
            ax.plot(a.t_s, a[col], 'o-', color=colors[method], label=method)
            ax.set(xlabel='Window T (s)', ylabel=unit, yscale='log')
            ax.set_xticks(sorted(available))
            ax.grid(alpha=.25, which='both')
            ax.legend()
    t = min(available)
    section = result[(result.method == 'Section') & (result.requested_t_s == t)]
    histogram = section.crossing_count.value_counts().sort_index()
    axes[1, 0].bar(histogram.index, histogram.values, color='tab:green', alpha=.75)
    axes[1, 0].set(xlabel='Vehicles crossing 250 m in one window', ylabel='Number of windows', title=f'Section counts | T={t:g}s')
    axes[1, 0].set_xticks(histogram.index)
    for x, n in histogram.items():
        axes[1, 0].text(x, n, str(n), ha='center', va='bottom')
    a = stats[stats.method == 'Section'].sort_values('t_s')
    labels = [f'{t:g}s' for t in a.t_s]
    percentage = 100 * a.valid_kq_points / a.windows
    axes[1, 1].bar(labels, percentage, color='tab:green', alpha=.75)
    axes[1, 1].set(ylabel='Windows with estimable density (%)', ylim=(0, 110), title='Section density availability')
    for x, pct, valid, total in zip(labels, percentage, a.valid_kq_points, a.windows):
        axes[1, 1].text(x, pct, f'{int(valid)}/{int(total)}', ha='center', va='bottom')
    fig.suptitle('Window effects: method differences, count quantization and availability')
    fig.savefig(out / 'method_window_effects.png', dpi=180)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--t', nargs='+', type=float, help='默认使用当前主结果的全部窗口')
    args = parser.parse_args()
    self_check()
    out = ROOT / 'results'
    cfg = json.loads((out / 'scope_config.json').read_text(encoding='utf-8'))
    edie = pd.read_csv(out / 'density_flow_windows.csv')
    if args.t is not None:
        if not set(args.t).issubset(set(edie.requested_t_s)):
            parser.error('请先用run_analysis.py生成相应时间窗口的Edie结果。')
        edie = edie.loc[edie.requested_t_s.isin(args.t)].copy()
    data = pd.read_csv(ROOT / cfg['source'], usecols=['vehicle_id', 'time_s', 'local_y_m', 'lane_id', 'speed_m_s'])
    if data.isna().any().any() or not np.isfinite(data.to_numpy()).all() or (data.speed_m_s < 0).any():
        raise ValueError('输入存在缺失、非有限值或负速度。')
    if data.duplicated(['vehicle_id', 'time_s']).any():
        raise ValueError('车辆-时间键重复。')
    ticks = np.sort(data.time_s.unique())
    if not np.allclose(np.diff(ticks), .1, atol=1e-7, rtol=0):
        raise ValueError('全局时间网格存在缺失。')
    selected = data.loc[(data.lane_id == cfg['lane_id']) &
                        (data.local_y_m >= cfg['spatial_start_m_inclusive']) &
                        (data.local_y_m < cfg['spatial_end_m_exclusive'])]
    frames = selected.groupby('time_s').agg(n=('vehicle_id', 'size'), sum_speed=('speed_m_s', 'sum')).reindex(ticks, fill_value=0)
    # 相邻帧统计量取均值，作为0.1秒区间内常值；按与窗口交集时长加权。
    n_mid = (frames.n.to_numpy()[:-1] + frames.n.to_numpy()[1:]) / 2
    speed_mid = (frames.sum_speed.to_numpy()[:-1] + frames.sum_speed.to_numpy()[1:]) / 2
    length = cfg['spatial_end_m_exclusive'] - cfg['spatial_start_m_inclusive']
    events = crossing_events(data, cfg)
    records = []
    for _, row in edie.iterrows():
        base = {key: row[key] for key in ['window_index', 'requested_t_s', 'start_s', 'end_s', 'duration_s', 'is_partial_window']}
        records.append(dict(base, method='Edie', density_veh_km=row.density_veh_km,
                            flow_veh_h=row.flow_veh_h, speed_km_h=row.speed_km_h, crossing_count=np.nan))
        overlap = np.maximum(0, np.minimum(ticks[1:], row.end_s) - np.maximum(ticks[:-1], row.start_s))
        k = 1000 * np.dot(overlap, n_mid) / (length * row.duration_s)
        q = 3600 * np.dot(overlap, speed_mid) / (length * row.duration_s)
        records.append(dict(base, method='Snapshot', density_veh_km=k, flow_veh_h=q,
                            speed_km_h=q / k if k > 0 else np.nan, crossing_count=np.nan))
        q, k, v, n = section_estimate(events, row.start_s, row.end_s)
        records.append(dict(base, method='Section', density_veh_km=k, flow_veh_h=q,
                            speed_km_h=v, crossing_count=n))
    result = pd.DataFrame(records)
    result.to_csv(out / 'density_flow_methods.csv', index=False, encoding='utf-8-sig')
    methods = ['Edie', 'Snapshot', 'Section']
    windows = list(edie.requested_t_s.unique())
    valid = result.dropna(subset=['density_veh_km', 'flow_veh_h'])
    kmax = max(10, np.ceil(valid.density_veh_km.max() * 1.08 / 10) * 10)
    qmax = max(100, np.ceil(valid.flow_veh_h.max() * 1.08 / 100) * 100)
    fig, axes = plt.subplots(3, len(windows), figsize=(4 * len(windows), 10),
                             sharex=True, sharey=True, squeeze=False, layout='constrained')
    summary = []
    for i, method in enumerate(methods):
        for j, t in enumerate(windows):
            a = result[(result.method == method) & (result.requested_t_s == t)]
            paired = a.dropna(subset=['density_veh_km', 'flow_veh_h'])
            ax = axes[i, j]
            ax.scatter(paired.density_veh_km, paired.flow_veh_h, s=18, alpha=.7, color=plt.get_cmap('tab10')(i))
            ax.set_title(f'{method} | T={t:g}s | {len(paired)}/{len(a)} points', fontsize=10)
            ax.set_xlim(0, kmax)
            ax.set_ylim(0, qmax)
            ax.grid(alpha=.2)
            if j == 0:
                ax.set_ylabel('Flow (veh/h/lane)')
            if i == 2:
                ax.set_xlabel('Density (veh/km/lane)')
            ref = edie.loc[edie.requested_t_s == t].reset_index(drop=True)
            aligned = a.reset_index(drop=True)
            summary.append({'method': method, 't_s': t, 'windows': len(a), 'valid_kq_points': len(paired),
                            'k_min': paired.density_veh_km.min(), 'k_max': paired.density_veh_km.max(),
                            'q_min': a.flow_veh_h.min(), 'q_max': a.flow_veh_h.max(),
                            'corr_k_q': paired.density_veh_km.corr(paired.flow_veh_h),
                            'k_mae_vs_edie': (aligned.density_veh_km - ref.density_veh_km).abs().mean(),
                            'q_mae_vs_edie': (aligned.flow_veh_h - ref.flow_veh_h).abs().mean()})
    fig.suptitle(f'I-80 eastbound | Lane {cfg["lane_id"]} | 200-300 m | three measurement methods')
    fig.savefig(out / 'fundamental_methods.png', dpi=170)
    plt.close(fig)
    support = ROOT / 'archive/current_support/methods'
    support.mkdir(parents=True, exist_ok=True)
    stats = pd.DataFrame(summary)
    expanded_figures(result, stats, out, kmax, qmax)
    stats.to_csv(support / 'summary.csv', index=False, encoding='utf-8-sig')
    events.to_csv(support / 'section_crossings.csv', index=False, encoding='utf-8-sig')
    totals = result.groupby(['method', 'requested_t_s']).apply(
        lambda a: pd.Series({'k_time': (a.density_veh_km * a.duration_s).sum(),
                              'q_time': (a.flow_veh_h * a.duration_s).sum()}), include_groups=False)
    for method in ['Edie', 'Snapshot']:
        assert np.allclose(totals.loc[method], totals.loc[method].iloc[0], atol=1e-7, rtol=1e-10)
    counts = result[result.method == 'Section'].groupby('requested_t_s').crossing_count.sum()
    assert counts.nunique() == 1
    (support / 'metadata.json').write_text(json.dumps({
        'section_position_m': (cfg['spatial_start_m_inclusive'] + cfg['spatial_end_m_exclusive']) / 2,
        'crossing_count': int(counts.iloc[0]), 'axis_k_max': float(kmax), 'axis_q_max': float(qmax),
        'snapshot_rule': 'piecewise constant average of adjacent frame counts and summed source velocities',
        'section_speed': 'interpolated source speed, harmonic mean across crossings',
        'undefined_section_density': 'NaN if no crossing or any nonpositive crossing speed',
        'checks': 'conserved area-method totals and identical section counts across windows'}, indent=2), encoding='utf-8')
    print(stats.round(3).to_string(index=False))


if __name__ == '__main__':
    main()
