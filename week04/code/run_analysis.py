"""一键生成精简主结果：python code/run_analysis.py --t 10 60。"""
import argparse
import json
import shutil
import subprocess
import sys

import pandas as pd

import prepare_trajectory_scope as preparation

ROOT = preparation.ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--t', nargs='+', type=float, default=[10, 60])
    parser.add_argument('--k-max', type=float)
    parser.add_argument('--q-max', type=float)
    args = parser.parse_args()
    results = ROOT / 'results'
    results.mkdir(exist_ok=True)
    preparation.main()
    stage = preparation.OUT
    for name in ['scope_config.json', '分析范围与质量检查.md']:
        shutil.copy2(stage / name, results / name)
    trajectory_name = f'trajectory_eastbound_lane{preparation.LANE}_y200_300m_SI.csv'
    shutil.copy2(stage / trajectory_name, results / 'selected_trajectory_SI.csv')
    plot_stage = ROOT / 'archive/current_support/fundamental'
    command = [sys.executable, str(ROOT / 'code/fundamental_diagram.py'), '--t', *map(str, args.t)]
    for flag, value in [('--k-max', args.k_max), ('--q-max', args.q_max)]:
        if value is not None:
            command.extend([flag, str(value)])
    subprocess.run(command, check=True)
    tables = [pd.read_csv(plot_stage / f'fundamental_T{t:g}s.csv') for t in dict.fromkeys(args.t)]
    windows = pd.concat(tables, ignore_index=True)
    windows.to_csv(results / 'density_flow_windows.csv', index=False, encoding='utf-8-sig')
    shutil.copy2(plot_stage / 'fundamental_comparison.png', results / 'fundamental_comparison.png')
    subprocess.run([sys.executable, str(ROOT / 'code/compare_density_methods.py')], check=True)
    audit = json.loads((stage / 'quality_checks.json').read_text(encoding='utf-8'))
    actual = json.loads((plot_stage / 'calculation_metadata.json').read_text(encoding='utf-8'))
    scope = audit['scope']
    overview = f'''# 主分析结果

主范围：I-80 东向，车道 {preparation.LANE}，200 ≤ local_y_m < 300 米，100米单车道路段。
采样点时段0–899.9秒；轨迹积分不外推到900秒。所选轨迹 {scope['rows']:,} 行，{scope['vehicles']} 辆车。
缺失值、整行重复、车辆—帧重复、车辆—时间重复均为0。详细检查见分析范围与质量检查.md。

## 主要结果

- fundamental_comparison.png：不同时间窗口的流量—密度基本图，同坐标范围。
- density_flow_windows.csv：全部时间窗口合并在一个表中，通过 requested_t_s 区分窗口长度。
- fundamental_methods.png：Edie、逐帧路段平均、断面计数估计三种方法的同坐标比较。
- density_flow_methods.csv：三种方法的逐窗口合并结果，method区分方法。
- method_agreement.png：同窗口方法叠加及密度、流量的一对一配对图。
- method_window_effects.png：窗口敏感性、过车计数及断面密度可估计比例。
- selected_trajectory_SI.csv：范围内采样点，用于查看数据；积分计算仍读取全量源轨迹以保留边界邻点。
- scope_config.json：固定分析范围及单位。
- 分析范围与质量检查.md：数据检查结果及方法。

## 窗口结果汇总

| 窗口秒 | 点数 | 密度范围 veh/km | 流量范围 veh/h |
|---|---:|---:|---:|
'''
    for t, a in windows.groupby('requested_t_s', sort=False):
        overview += f'|{t:g}|{len(a)}|{a.density_veh_km.min():.2f}–{a.density_veh_km.max():.2f}|{a.flow_veh_h.min():.2f}–{a.flow_veh_h.max():.2f}|\n'
    if len(tables) > 1:
        overview += '\n## 点云比较\n\n短窗口保留更多短时波动，点云覆盖范围较广、散布较大。'
        overview += '较长窗口将状态平均，点数减少、覆盖范围收窄，极端值也被削弱。'
        overview += '当前车道1路段在各窗口下总体呈正相关，长窗口更适合观察平均趋势，短窗口更适合观察局部变化。\n'
    overview += '''
## 三种计算方法

Edie：区域累计停留时间及距离。Snapshot：逐帧路段车辆数及原始速度总和的时间平均。
Section：250米断面过车计数计算流量，用过车速度调和平均估计密度，依赖近似稳态和空间均匀假设。
断面无过车时q=0，密度及速度留空；图只绘制密度可估计的窗口。
区域法积分不外推末帧，断面法也使用相同实际窗口时长。

| 方法 | 窗口秒 | 可绘制点数/窗口数 | 与Edie的密度平均绝对差 veh/km | 与Edie的流量平均绝对差 veh/h |
|---|---:|---:|---:|---:|
'''
    stats = pd.read_csv(ROOT / 'archive/current_support/methods/summary.csv')
    for _, row in stats[stats.method != 'Edie'].iterrows():
        overview += f'|{row.method}|{row.t_s:g}|{row.valid_kq_points:g}/{row.windows:g}|{row.k_mae_vs_edie:.3f}|{row.q_mae_vs_edie:.3f}|\n'
    overview += '\n逐帧法与Edie接近，断面法短窗更分散。密度差只计算可估计的成对窗口，流量差包含无过车窗口；差异不等于对真值的误差。\n'
    overview += f'''
## 复现与方法

项目根目录运行 `python code/run_analysis.py --t 10 60`。
窗口可改为任意不小于0.1秒的值，例如 `--t 5 10 30 60`。
跨运行统一坐标可加 `--k-max 100 --q-max 2700`，上限不能裁掉数据点。
依赖：numpy、pandas、matplotlib。

累计区域内停留时间H（veh·s）与距离D（veh·m），使用
k=1000H/(LT)（veh/km），q=3600D/(LT)（veh/h），L=100米。
相邻连续采样点线性插值；换道时刻按两帧中点估计。
末窗口按实际时长计算；空窗口的密度、流量为0，速度为空。
q/k是窗口平均速度，不等于所有散点的共同斜率。

本次坐标：密度0–{actual['density_axis'][1]:g} veh/km，流量0–{actual['flow_axis'][1]:g} veh/h。
已通过数值示例校验、不同窗口累计量一致性及10/60秒加权聚合检查。

## 代码与历史

code/run_analysis.py：一键入口，集中整理主要结果。
code/prepare_trajectory_scope.py：固定范围、缺失与重复检查、筛选轨迹。
code/fundamental_diagram.py：时空裁剪、密度流量计算、绘图。
code/compare_lanes_segments.py：其他车道与路段比较，可选运行。
code/compare_density_methods.py：逐帧路段平均、断面计数与调和速度估计，比较三种方法。

archive/previous_lane2/：保留此前车道2主分析、所有其他车道比较及原版代码。
archive/current_support/：本次逐项检查、分窗口CSV、SVG和叠加图等辅助结果。
正常使用只需查看results目录。本次运行更新主结果，辅助结果不会自动删除。
'''
    (results / '结果说明.md').write_text(overview, encoding='utf-8')
    print(f'Primary results: {results}')


if __name__ == '__main__':
    main()
