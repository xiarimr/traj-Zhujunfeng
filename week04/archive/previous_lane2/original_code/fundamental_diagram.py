"""按可配置窗口计算 Edie 密度/流量，并绘制统一坐标范围基本图。

运行示例：
    python fundamental_diagram.py --t 10 60
    python fundamental_diagram.py --t 5 10 30 60 --k-max 150 --q-max 2500

依赖 numpy、pandas、matplotlib。读取全量原始 SI 轨迹及已固定的 scope_config.json。
"""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent


def clip_segments(data, config):
    """线性连接同车连续采样点，裁剪车道、空间边界，返回 [进入时刻,离开时刻,速度]。

    换道发生时刻不可由离散 lane_id 精确确定，采用相邻采样时刻中点。
    前半段归前帧车道，后半段归后帧车道。不会跨缺帧连接或外推首末点。
    """
    columns = ['vehicle_id', 'frame_id', 'time_s', 'local_y_m', 'lane_id']
    if data[columns].isna().any().any() or not np.isfinite(data[columns].to_numpy()).all():
        raise ValueError('必要字段存在缺失/非有限数值，请先处理。')
    if data.duplicated(['vehicle_id', 'frame_id']).any() or data.duplicated(['vehicle_id', 'time_s']).any():
        raise ValueError('车辆-帧或车辆-时间键重复，禁止静默去重。')
    d = data.sort_values(['vehicle_id', 'time_s'])
    a, b = d.iloc[:-1], d.iloc[1:]
    t0, t1 = a.time_s.to_numpy(), b.time_s.to_numpy()
    dt = t1 - t0
    same = a.vehicle_id.to_numpy() == b.vehicle_id.to_numpy()
    continuous = same & np.isclose(dt, config['nominal_sampling_interval_s'], atol=1e-7, rtol=0)
    if (same & (dt <= 0)).any():
        raise ValueError('车辆时间不严格递增。')
    y0, y1 = a.local_y_m.to_numpy(), b.local_y_m.to_numpy()
    if (continuous & (y1 < y0 - 1e-6)).any():
        raise ValueError('连续轨迹存在逆向位移，请核查后再计算。')
    t0, t1, y0, y1 = [v[continuous] for v in [t0, t1, y0, y1]]
    lane0, lane1 = a.lane_id.to_numpy()[continuous], b.lane_id.to_numpy()[continuous]
    v = (y1 - y0) / (t1 - t0)
    moving = v > 0
    enter = np.full(len(v), -np.inf)
    leave = np.full(len(v), np.inf)
    enter[moving] = t0[moving] + (config['spatial_start_m_inclusive'] - y0[moving]) / v[moving]
    leave[moving] = t0[moving] + (config['spatial_end_m_exclusive'] - y0[moving]) / v[moving]
    stationary_inside = ((y0 >= config['spatial_start_m_inclusive']) &
                         (y0 < config['spatial_end_m_exclusive']))
    eligible = moving | stationary_inside
    midpoint = (t0 + t1) / 2
    pieces = []
    for left, right, lane in [(t0, midpoint, lane0), (midpoint, t1, lane1)]:
        start = np.maximum.reduce([left, enter, np.full(len(v), config['time_start_s_inclusive'])])
        end = np.minimum.reduce([right, leave, np.full(len(v), config['time_end_s_exclusive'])])
        keep = eligible & (lane == config['lane_id']) & (end > start)
        pieces.append(np.column_stack([start[keep], end[keep], v[keep]]))
    segments = np.concatenate(pieces)
    info = {
        'continuous_vehicle_intervals': int(continuous.sum()),
        'skipped_noncontinuous_vehicle_intervals': int((same & ~continuous).sum()),
        'lane_transition_intervals': int((lane0 != lane1).sum()),
        'clipped_pieces': len(segments),
    }
    return segments, info


def aggregate(segments, t, start, end, length):
    """每个非重叠窗口累计 veh*s 和 veh*m，尾部不足 t 时按实际窗口长度计算。"""
    if not np.isfinite(t) or t <= 0 or end <= start or length <= 0:
        raise ValueError('窗口、路段长度及分析时长必须为正。')
    rows = []
    count = int(np.ceil((end - start) / t - 1e-10))
    for i in range(count):
        left, right = start + i * t, min(start + (i + 1) * t, end)
        duration = right - left
        overlap = np.maximum(0, np.minimum(segments[:, 1], right) - np.maximum(segments[:, 0], left))
        total_time = overlap.sum()
        total_distance = np.dot(overlap, segments[:, 2])
        k = 1000 * total_time / (length * duration)
        q = 3600 * total_distance / (length * duration)
        rows.append({
            'window_index': i, 'requested_t_s': t, 'start_s': left, 'end_s': right,
            'duration_s': duration, 'is_partial_window': duration < t - 1e-8,
            'total_vehicle_time_s': total_time, 'total_vehicle_distance_m': total_distance,
            'density_veh_km': k, 'flow_veh_h': q,
            'speed_km_h': q / k if k > 0 else np.nan,
        })
    return pd.DataFrame(rows)


def self_check():
    # 一辆车以 10 m/s 通过 100 m，10秒内 k=10veh/km，q=360veh/h。
    seg = np.array([[0., 10., 10.]])
    a = aggregate(seg, 10, 0, 10, 100)
    assert np.isclose(a.density_veh_km.iloc[0], 10)
    assert np.isclose(a.flow_veh_h.iloc[0], 360)
    # 停车只贡献停留时间，不贡献距离；部分窗口使用实际时长。
    a = aggregate(np.array([[0., 12., 0.]]), 10, 0, 12, 100)
    assert np.allclose(a.density_veh_km, 10) and np.allclose(a.flow_veh_h, 0)
    assert a.duration_s.iloc[-1] == 2 and a.is_partial_window.iloc[-1]
    cfg = {'nominal_sampling_interval_s': .1, 'lane_id': 2,
           'spatial_start_m_inclusive': 200, 'spatial_end_m_exclusive': 300,
           'time_start_s_inclusive': 0, 'time_end_s_exclusive': 1}
    d = pd.DataFrame({'vehicle_id': [1, 1], 'frame_id': [1, 2],
                      'time_s': [0., .1], 'local_y_m': [199.5, 200.5], 'lane_id': [1, 2]})
    seg, _ = clip_segments(d, cfg)
    assert np.isclose((seg[:, 1] - seg[:, 0]).sum(), .05)
    assert np.isclose(np.dot(seg[:, 1] - seg[:, 0], seg[:, 2]), .5)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--t', nargs='+', type=float, default=[10, 60], help='统计窗口（秒），可同时传多个值')
    parser.add_argument('--config', type=Path, default=ROOT / 'analysis_scope' / 'scope_config.json')
    parser.add_argument('--output', type=Path, default=ROOT / 'fundamental_diagram_outputs')
    parser.add_argument('--k-max', type=float, help='统一密度坐标上限，veh/km')
    parser.add_argument('--q-max', type=float, help='统一流量坐标上限，veh/h')
    args = parser.parse_args()
    if any(not np.isfinite(t) or t < .1 for t in args.t):
        parser.error('--t 必须为有限数值且不小于原始采样间隔 0.1 秒。')
    self_check()
    cfg = json.loads(args.config.read_text(encoding='utf-8'))
    source = ROOT / cfg['source']
    data = pd.read_csv(source, usecols=['vehicle_id', 'frame_id', 'time_s', 'local_y_m', 'lane_id'])
    segments, info = clip_segments(data, cfg)
    start = max(cfg['time_start_s_inclusive'], float(data.time_s.min()))
    end = min(cfg['time_end_s_exclusive'], float(data.time_s.max()))
    # 最后采样是899.9秒，无900秒采样点，因此不外推最后0.1秒。
    length = cfg['spatial_end_m_exclusive'] - cfg['spatial_start_m_inclusive']
    results = {t: aggregate(segments, t, start, end, length) for t in dict.fromkeys(args.t)}
    all_rows = pd.concat(results.values(), ignore_index=True)
    kmax = args.k_max if args.k_max is not None else max(10., np.ceil(all_rows.density_veh_km.max() * 1.08 / 10) * 10)
    qmax = args.q_max if args.q_max is not None else max(100., np.ceil(all_rows.flow_veh_h.max() * 1.08 / 100) * 100)
    if not np.isfinite(kmax) or not np.isfinite(qmax) or kmax <= 0 or qmax <= 0:
        parser.error('坐标上限必须为有限正数。')
    if kmax < all_rows.density_veh_km.max() or qmax < all_rows.flow_veh_h.max():
        parser.error('指定坐标上限小于计算结果，会裁掉数据点，请调大。')
    args.output.mkdir(parents=True, exist_ok=True)
    colors = plt.get_cmap('tab10')
    fig, axes = plt.subplots(1, len(results), figsize=(5 * len(results), 4.5), sharex=True, sharey=True, squeeze=False)
    overlay, overlay_ax = plt.subplots(figsize=(6, 4.8))
    for i, (t, table) in enumerate(results.items()):
        label = f'T = {t:g} s ({len(table)} windows)'
        ax = axes[0, i]
        for target in [ax, overlay_ax]:
            target.scatter(table.density_veh_km, table.flow_veh_h, s=32, alpha=.75, color=colors(i % 10), label=label)
        ax.set_title(label)
        table.to_csv(args.output / f'fundamental_T{t:g}s.csv', index=False, encoding='utf-8-sig')
    for ax in [*axes[0], overlay_ax]:
        ax.set_xlim(0, kmax)
        ax.set_ylim(0, qmax)
        ax.set_xlabel('Density (veh/km/lane)')
        ax.set_ylabel('Flow (veh/h/lane)')
        ax.grid(alpha=.25)
    title = f'I-80 eastbound | Lane {cfg["lane_id"]} | {cfg["spatial_start_m_inclusive"]:g}-{cfg["spatial_end_m_exclusive"]:g} m'
    fig.suptitle(title)
    overlay_ax.set_title(title)
    overlay_ax.legend()
    for f, filename in [(fig, 'fundamental_comparison'), (overlay, 'fundamental_overlay')]:
        f.tight_layout()
        f.savefig(args.output / f'{filename}.png', dpi=180)
        f.savefig(args.output / f'{filename}.svg')
        plt.close(f)
    # 不同窗口应保存相同的累计停留时间、行驶距离。
    totals = [(r.total_vehicle_time_s.sum(), r.total_vehicle_distance_m.sum()) for r in results.values()]
    assert np.allclose(totals, totals[0], rtol=1e-10, atol=1e-7)
    if 10 in results and 60 in results:
        small, large = results[10], results[60]
        for _, row in large.iterrows():
            part = small[(small.start_s >= row.start_s - 1e-8) & (small.end_s <= row.end_s + 1e-8)]
            for col in ['density_veh_km', 'flow_veh_h']:
                assert np.isclose(np.average(part[col], weights=part.duration_s), row[col])
    metadata = {'scope': cfg, 'actual_time_start_s': start, 'actual_time_end_s': end,
                'requested_t_s': list(results), 'density_axis': [0, float(kmax)], 'flow_axis': [0, float(qmax)],
                'lane_transition_policy': 'assign each half of a sample interval to its corresponding endpoint lane',
                'trajectory_policy': 'linear interpolation between consecutive samples only; no endpoint extrapolation',
                'partial_window_policy': 'retain and divide by actual duration', 'checks': info,
                'window_totals_consistent': True}
    (args.output / 'calculation_metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    print(all_rows.groupby('requested_t_s').agg(windows=('window_index', 'size'), density_min=('density_veh_km', 'min'),
          density_max=('density_veh_km', 'max'), flow_min=('flow_veh_h', 'min'), flow_max=('flow_veh_h', 'max')).to_string())
    print(f'Output: {args.output}')


if __name__ == '__main__':
    main()
