"""固定车辆轨迹分析范围并审计数据。运行: python prepare_trajectory_scope.py

依赖: pandas, numpy。原始 CSV 只读，结果写入 analysis_scope/。
"""
from pathlib import Path
import hashlib
import json

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / 'data' / 'NGSIM_I80_20050413_1600-1615_SI.csv'
OUT = ROOT / 'analysis_scope'
START_MS = 1113433200000
LANE = 2
Y_START, Y_END = 200.0, 300.0
UNITS = {
    'vehicle_id': 'identifier', 'frame_id': 'identifier', 'time_s': 's',
    'global_time_ms': 'ms (source timestamp)', 'local_x_m': 'm',
    'local_y_m': 'm', 'vehicle_length_m': 'm', 'vehicle_class': 'category',
    'speed_m_s': 'm/s', 'acceleration_m_s2': 'm/s^2', 'lane_id': 'category',
}


def audit(df):
    """检查数值缺失、非有限值、重复键与全量轨迹内部采样断档。"""
    ordered = df.sort_values(['vehicle_id', 'global_time_ms', 'frame_id'])
    delta = ordered.groupby('vehicle_id')['global_time_ms'].diff()
    gaps = ordered.loc[delta > 100,
                       ['vehicle_id', 'frame_id', 'global_time_ms', 'time_s']].copy()
    gaps['previous_time_ms'] = ordered.groupby('vehicle_id')['global_time_ms'].shift()[delta > 100]
    gaps['gap_s'] = delta[delta > 100] / 1000
    gaps['missing_sample_count'] = (delta[delta > 100] / 100 - 1).astype(int)
    result = {
        'rows': len(df), 'vehicles': int(df.vehicle_id.nunique()),
        'missing_by_column': df.isna().sum().astype(int).to_dict(),
        'nonfinite_nonmissing_by_column': {
            c: int((df[c].notna() & ~np.isfinite(df[c])).sum()) for c in df.columns
        },
        'exact_duplicate_excess_rows': int(df.duplicated().sum()),
        'vehicle_frame_duplicate_excess_rows': int(df.duplicated(['vehicle_id', 'frame_id']).sum()),
        'vehicle_time_duplicate_excess_rows': int(df.duplicated(['vehicle_id', 'global_time_ms']).sum()),
        'time_min_s': float(df.time_s.min()), 'time_max_s': float(df.time_s.max()),
        'observed_time_ticks': int(df.global_time_ms.nunique()),
        'off_100ms_grid_rows': int(((df.global_time_ms - START_MS) % 100 != 0).sum()),
        'relative_time_mismatch_rows': int((np.abs(df.time_s - (df.global_time_ms - START_MS) / 1000) > 1e-6).sum()),
        'internal_gap_events': len(gaps),
        'negative_speed_rows': int((df.speed_m_s < 0).sum()),
        'nonpositive_vehicle_length_rows': int((df.vehicle_length_m <= 0).sum()),
        'invalid_lane_rows': int((~df.lane_id.isin(range(1, 8))).sum()),
    }
    return result, gaps


def main():
    OUT.mkdir(exist_ok=True)
    d = pd.read_csv(SOURCE)
    if set(d.columns) != set(UNITS):
        raise ValueError('输入字段发生变化，请先核对字段及单位。')
    for c in d.columns:
        d[c] = pd.to_numeric(d[c], errors='raise')
    full, gaps = audit(d)
    full['missing_global_ticks'] = int(len(set(range(START_MS, START_MS + 900000, 100)) - set(d.global_time_ms)))
    sha256 = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    metadata = json.loads((ROOT / 'data' / 'source_and_checks.json').read_text(encoding='utf-8'))
    full['sha256'] = sha256
    full['source_checksum_matches_metadata'] = sha256 == metadata['files'][SOURCE.name]['sha256']
    full['actual_global_time_ms_range'] = [int(d.global_time_ms.min()), int(d.global_time_ms.max())]
    full['metadata_global_time_ms_range'] = metadata['global_time_ms']
    full['metadata_time_range_matches'] = full['actual_global_time_ms_range'] == metadata['global_time_ms']

    # 候选仅用于核查覆盖；最终范围是固定常量，不随流量变化重新选择。
    candidates = []
    for lane in [2, 3, 4]:
        for y in [100, 200, 300]:
            s = d.loc[(d.lane_id == lane) & (d.local_y_m >= y) & (d.local_y_m < y + 100)]
            candidates.append({'lane_id': lane, 'start_m': y, 'end_m': y + 100,
                               'rows': len(s), 'vehicles': s.vehicle_id.nunique(),
                               'occupied_ticks': s.global_time_ms.nunique(),
                               'occupied_10m_bins': ((s.local_y_m - y) // 10).nunique(),
                               'last_record_s': s.time_s.max()})
    pd.DataFrame(candidates).to_csv(OUT / 'candidate_coverage.csv', index=False, encoding='utf-8-sig')

    mask = ((d.lane_id == LANE) & (d.local_y_m >= Y_START) &
            (d.local_y_m < Y_END) & (d.time_s >= 0) & (d.time_s < 900))
    selected = d.loc[mask].sort_values(['vehicle_id', 'global_time_ms', 'frame_id']).copy()
    scoped, scope_gaps = audit(selected)
    # 筛选后不连续通常源于出入路段或换道，不能计作原始数据缺失。
    scoped['filtered_sequence_breaks'] = scoped.pop('internal_gap_events')
    scoped['empty_scope_ticks'] = 9000 - scoped['observed_time_ticks']
    minute = selected.assign(minute_index=(selected.time_s // 60).astype(int)).groupby('minute_index').agg(
        rows=('vehicle_id', 'size'), vehicles=('vehicle_id', 'nunique'),
        occupied_ticks=('global_time_ms', 'nunique'), y_min_m=('local_y_m', 'min'), y_max_m=('local_y_m', 'max'))
    minute = minute.reindex(range(15))
    minute.index.name = 'minute_index'
    minute.to_csv(OUT / 'minute_coverage.csv', encoding='utf-8-sig')
    spatial = selected.assign(bin_start_m=Y_START + ((selected.local_y_m - Y_START) // 10) * 10).groupby('bin_start_m').agg(
        rows=('vehicle_id', 'size'), vehicles=('vehicle_id', 'nunique'))
    spatial.to_csv(OUT / 'spatial_coverage.csv', encoding='utf-8-sig')
    selected.to_csv(OUT / 'trajectory_eastbound_lane2_y200_300m_SI.csv', index=False, encoding='utf-8-sig')
    gaps.to_csv(OUT / 'source_internal_gaps.csv', index=False, encoding='utf-8-sig')
    scope_gaps.to_csv(OUT / 'filtered_sequence_breaks.csv', index=False, encoding='utf-8-sig')
    config = {
        'source': str(SOURCE.relative_to(ROOT)), 'direction': 'eastbound',
        'direction_evidence': 'data/使用说明.txt；CSV 没有独立的方向字段',
        'lane_id': LANE, 'longitudinal_coordinate': 'local_y_m',
        'spatial_start_m_inclusive': Y_START, 'spatial_end_m_exclusive': Y_END,
        'segment_length_m': 100, 'time_start_s_inclusive': 0, 'time_end_s_exclusive': 900,
        'source_local_time': '2005-04-13 16:00–16:15 PDT',
        'nominal_sampling_interval_s': 0.1, 'units': UNITS,
        'unit_policy': '输入已是 SI，保留原值不重复换算；global_time_ms 为追溯字段，分析使用 time_s。',
        'lane_policy': '逐条记录按 lane_id 筛选，允许车辆在范围外换道。',
        'missing_policy': '报告缺失，不插补；原始车辆首次出现之前和最后出现之后不视为缺帧。',
        'duplicate_policy': '报告整行、车辆-帧、车辆-时间重复；本次无重复，不删除记录。',
    }
    for name, obj in [('scope_config.json', config), ('quality_checks.json', {'source': full, 'scope': scoped})]:
        (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding='utf-8')
    report = f'''# 车辆轨迹范围与质量检查

## 固定分析范围
I-80 东向，lane_id = {LANE}，{Y_START:g} ≤ local_y_m < {Y_END:g} 米，长度 100 米。
时间为 2005-04-13 16:00–16:15 PDT，相对时间 0 ≤ time_s < 900 秒，采样间隔 0.1 秒。
东向依据 data/使用说明.txt；CSV 本身没有独立方向字段。
选定路段位于观测坐标范围内部，10 个 10 米区间均有记录，覆盖全部 9000 个采样时刻。
覆盖记录用于判断可用性，不表示整个路段在每个时刻都有完整空间观测，也不保证无测量误差。

## 统一单位
输入已经是 SI：坐标和车长为 m，速度为 m/s，加速度为 m/s²，相对时间为 s。
直接保留这些值，不再次进行英尺换算。global_time_ms 保留为原始毫秒时间戳用于追溯。
数据说明记录的原始换算为 1 US survey foot = 1200/3937 m，SI 字段保留 6 位小数。
当前文件夹没有 raw CSV，不能独立复核原始英尺到 SI 的逐值转换。

## 实际检查结果
| 检查 | 全量数据 | 固定范围 |
|---|---:|---:|
| 记录数 | {full['rows']:,} | {scoped['rows']:,} |
| 车辆数 | {full['vehicles']:,} | {scoped['vehicles']:,} |
| 各列缺失值总数 | {sum(full['missing_by_column'].values())} | {sum(scoped['missing_by_column'].values())} |
| 非缺失的非有限数值 | {sum(full['nonfinite_nonmissing_by_column'].values())} | {sum(scoped['nonfinite_nonmissing_by_column'].values())} |
| 完全重复的多余行 | {full['exact_duplicate_excess_rows']} | {scoped['exact_duplicate_excess_rows']} |
| 车辆—帧重复的多余行 | {full['vehicle_frame_duplicate_excess_rows']} | {scoped['vehicle_frame_duplicate_excess_rows']} |
| 车辆—时间重复的多余行 | {full['vehicle_time_duplicate_excess_rows']} | {scoped['vehicle_time_duplicate_excess_rows']} |
| 偏离 0.1 秒网格的记录 | {full['off_100ms_grid_rows']} | {scoped['off_100ms_grid_rows']} |
| 相对时间与原时间戳不一致 | {full['relative_time_mismatch_rows']} | {scoped['relative_time_mismatch_rows']} |

全量数据内部采样断档事件：{full['internal_gap_events']}；全局缺失采样时刻：{full['missing_global_ticks']}。
筛选后的车辆序列中有 {scoped['filtered_sequence_breaks']} 处不连续，属于范围筛选造成的间断候选，不能当成原始缺失。
未插补、平滑或删除异常轨迹。负速度、非正车长及非法车道的检查计数见 quality_checks.json。
文件 SHA-256 与随附元数据匹配：{full['source_checksum_matches_metadata']}。

## 元数据问题
随附 source_and_checks.json 的 global_time_ms 下界写为 {metadata['global_time_ms'][0]}，
实际最早时间戳是 {full['actual_global_time_ms_range'][0]}。实际值与查询条件及 time_s 一致。
配置使用实际时间起点，原始元数据保持不变。

## 后续使用规则
使用 trajectory_eastbound_lane2_y200_300m_SI.csv 的固定筛选结果。
逐帧判断车道和空间归属，不要求一辆车在整个 15 分钟内始终保持 lane_id = 2。
该 CSV 是范围内采样点，不是完整的边界裁剪轨迹片段。
后续计算流量、密度时需要回到原始数据取相邻点并在空间、时间边界裁剪，
不能连接筛选后不连续的点，也不能把每个记录直接视为完整 0.1 秒的范围内停留时间。

## 复现
在项目目录运行 `python prepare_trajectory_scope.py`（依赖 pandas、numpy）。
配置、逐列审计、分钟覆盖、空间覆盖和候选路段覆盖均保存在同目录。
'''
    (OUT / '分析范围与质量检查.md').write_text(report, encoding='utf-8')
    assert len(selected) == 50118 and selected.vehicle_id.nunique() == 371
    assert selected.lane_id.eq(LANE).all()
    assert selected.local_y_m.ge(Y_START).all() and selected.local_y_m.lt(Y_END).all()
    print(json.dumps({'source': full, 'scope': scoped, 'output': str(OUT)}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
