"""Select three NGSIM pairs without using model outcomes, replay all models.

python two_vehicle_experiments/ngsim/run_experiments.py
Requires numpy, pandas, matplotlib. No SciPy needed.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from common import MODELS, COLORS, PARAMETERS, simulate, metrics, plot_scenario, rmse

BASE = Path(__file__).resolve().parent
SOURCE = BASE.parents[2] / "week04/data/NGSIM_I80_20050413_1600-1615_SI.csv"


def smooth_position(y, window=11):
    """Centered 1.1 s mean; linear edge extension, no extrapolation in replay."""
    k = window // 2
    left_slope = np.polyfit(np.arange(window), y[:window], 1)[0]
    right_slope = np.polyfit(np.arange(window), y[-window:], 1)[0]
    extended = np.r_[y[0] + left_slope*np.arange(-k, 0), y,
                     y[-1] + right_slope*np.arange(1, k+1)]
    return np.convolve(extended, np.ones(window)/window, mode="valid")


def position_replay(t, y):
    """Monotone cubic Hermite interpolation, speed = analytic position derivative."""
    h = np.diff(t)
    d = np.diff(y)/h
    if np.min(d) < -1e-8:
        raise ValueError("Smoothed leader position not monotone")
    slope = np.zeros(len(t))
    slope[0], slope[-1] = d[0], d[-1]
    same = (d[:-1] > 0) & (d[1:] > 0)
    w1, w2 = 2*h[1:]+h[:-1], h[1:]+2*h[:-1]
    slope[1:-1][same] = (w1[same]+w2[same])/(w1[same]/d[:-1][same]+w2[same]/d[1:][same])

    def leader(time):
        i = int(np.clip(np.searchsorted(t, time, side="right")-1, 0, len(t)-2))
        step = h[i]
        u = (time-t[i])/step
        x0, x1, v0, v1 = y[i], y[i+1], slope[i], slope[i+1]
        x = (2*u**3-3*u**2+1)*x0 + (u**3-2*u**2+u)*step*v0 + (-2*u**3+3*u**2)*x1 + (u**3-u**2)*step*v1
        v = (6*u**2-6*u)*x0/step + (3*u**2-4*u+1)*v0 + (-6*u**2+6*u)*x1/step + (3*u**2-2*u)*v1
        return x, v
    return leader


def find_candidates(source):
    df = pd.read_csv(source)
    required = ["vehicle_id", "frame_id", "time_s", "local_y_m", "vehicle_length_m", "vehicle_class", "speed_m_s", "lane_id"]
    if df[required].isna().any().any():
        raise ValueError("Missing required source values")
    if df.duplicated(["frame_id", "vehicle_id"]).any():
        raise ValueError("Duplicate vehicle/frame keys")
    # Adjacency is computed BEFORE filtering class: motorcycles/trucks cannot be skipped.
    ordered = df.sort_values(["frame_id", "lane_id", "local_y_m"])
    group = ordered.groupby(["frame_id", "lane_id"], sort=False)
    for original, name in [("vehicle_id", "leader_id"), ("local_y_m", "leader_y"),
                           ("speed_m_s", "leader_v"), ("vehicle_length_m", "leader_length"),
                           ("vehicle_class", "leader_class")]:
        ordered[name] = group[original].shift(-1)
    pair = ordered.dropna(subset=["leader_id"]).sort_values(["vehicle_id", "time_s"]).copy()
    gap = pair.leader_y-pair.local_y_m-pair.leader_length
    pair["valid"] = ((pair.vehicle_class == 2) & (pair.leader_class == 2) &
                     pair.lane_id.between(1, 5) & gap.between(1, 60) &
                     pair.speed_m_s.between(0, 35) & pair.leader_v.between(0, 35))
    new = ((pair.vehicle_id != pair.vehicle_id.shift()) |
           (pair.leader_id != pair.leader_id.shift()) |
           (pair.lane_id != pair.lane_id.shift()) |
           ((pair.time_s.diff()-0.1).abs() > 1e-5) |
           (~pair.valid) | (~pair.valid.shift(fill_value=False)))
    pair["segment"] = new.cumsum()
    candidates = []
    for _, segment in pair[pair.valid].groupby("segment", sort=False):
        # 30-second windows, 5-second stride. Require a full uninterrupted 10 Hz record.
        if len(segment) < 301:
            continue
        segment = segment.reset_index(drop=True)
        for start in range(0, len(segment)-300, 50):
            window = segment.iloc[start:start+301]
            t = window.time_s.to_numpy()
            fy, ly = window.local_y_m.to_numpy(), window.leader_y.to_numpy()
            fv, lv = window.speed_m_s.to_numpy(), window.leader_v.to_numpy()
            if ly[0] - fy[0] - float(window.leader_length.iloc[0]) < 5:
                continue
            if (np.diff(fy) < -0.01).any() or (np.diff(ly) < -0.01).any():
                continue
            if np.ptp(window.leader_length.to_numpy()) > 1e-5:
                continue
            smooth_y = smooth_position(ly)
            if (np.diff(smooth_y) < -1e-8).any():
                continue
            discrepancy = np.abs(np.gradient(smooth_y, t)-lv)
            follower_discrepancy = np.abs(np.gradient(smooth_position(fy), t)-fv)
            if max(np.quantile(discrepancy, 0.95), np.quantile(follower_discrepancy, 0.95)) > 2.0:
                continue
            candidates.append(dict(follower=int(window.vehicle_id.iloc[0]),
                leader=int(window.leader_id.iloc[0]), lane=int(window.lane_id.iloc[0]),
                start=float(t[0]), end=float(t[-1]), samples=len(t),
                leader_speed_std=float(lv.std()), leader_mean_speed=float(lv.mean()),
                speed_drop=float(lv[:50].mean()-lv[-50:].mean()),
                speed_range=float(lv.max()-lv.min()),
                position_speed_discrepancy_p95=float(np.quantile(discrepancy, .95)),
                follower_position_speed_discrepancy_p95=float(np.quantile(follower_discrepancy, .95)),
                data=window))
    print(f"Source rows={len(df)}, vehicles={df.vehicle_id.nunique()}, eligible windows={len(candidates)}", flush=True)
    if len(candidates) < 3:
        raise ValueError("Fewer than 3 eligible 30 s windows; review selection criteria")
    return candidates, dict(rows=len(df), vehicles=int(df.vehicle_id.nunique()), eligible_windows=len(candidates))


def select_cases(candidates):
    chosen, used = [], set()
    rules = [("steady", lambda c: -c["leader_speed_std"] if c["leader_mean_speed"] >= 3 else -1e6),
             ("decelerating", lambda c: c["speed_drop"]),
             ("variable_speed", lambda c: c["leader_speed_std"])]
    for name, score in rules:
        eligible = [c for c in candidates if c["follower"] not in used and c["leader"] not in used]
        if not eligible:
            raise ValueError("Not enough independent vehicle pairs")
        item = max(eligible, key=score)
        chosen.append((name, item))
        used.update([item["follower"], item["leader"]])
    return chosen


def overlay_speed(response, t, v):
    # Optional signed lag minimizing RMSE between centered speeds, on common interior interval.
    shifts = np.arange(-5, 5.0001, .1)
    interior = (t >= 5) & (t <= t[-1]-5)
    if interior.sum() < 20 or np.std(v[interior]) < .5:
        return None
    losses = [rmse(np.interp(t[interior]+lag, response["t"], response["v"])-v[interior]) for lag in shifts]
    return float(shifts[np.argmin(losses)])


def comparison_plot(all_metrics, output):
    names = list(all_metrics)
    fig, axes = plt.subplots(2, 2, figsize=(13, 9), constrained_layout=True)
    specs = [("observed_position_rmse", "Position RMSE vs measured follower [m]"),
             ("observed_speed_rmse", "Speed RMSE vs measured follower [m/s]"),
             ("min_net_gap", "Minimum valid simulated net gap [m]"),
             ("physical_failure", "Physical/numerical failure (1=yes)")]
    x = np.arange(len(names))
    for ax, (key, title) in zip(axes.flat, specs):
        for j, model in enumerate(MODELS):
            vals = [float(all_metrics[n][model][key]) for n in names]
            bars = ax.bar(x+(j-1)*.24, vals, .24, label=model, color=COLORS[model])
            for bar, n, val in zip(bars, names, vals):
                if not all_metrics[n][model]["completed"]:
                    bar.set_hatch("///")
                ax.annotate(f"{val:.2f}" if key != "physical_failure" else str(int(val)),
                            (bar.get_x()+bar.get_width()/2, bar.get_height()),
                            xytext=(0, 3), textcoords="offset points", ha="center", fontsize=8)
        ax.set(title=title, xticks=x, xticklabels=names)
        ax.grid(axis="y", alpha=.2)
        ax.legend(fontsize=8)
        ax.margins(y=.2)
    fig.suptitle("NGSIM: common-horizon observed errors; no calibration on selected cases")
    fig.savefig(output / "ngsim_comparison.png", dpi=170)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--output", type=Path, default=BASE / "results")
    parser.add_argument("--dt", type=float, default=.02)
    args = parser.parse_args()
    if not 0 < args.dt <= .1:
        parser.error("dt must be in (0, .1]")
    args.output.mkdir(parents=True, exist_ok=True)
    data_output = args.output / "data"
    data_output.mkdir(parents=True, exist_ok=True)
    candidates, audit = find_candidates(args.source)
    selected = select_cases(candidates)
    metadata, all_metrics = {}, {}
    for name, case in selected:
        window = case["data"]
        meta = {k:v for k,v in case.items() if k != "data"}
        metadata[name] = meta
        print(f"Selected {name}: {meta}", flush=True)
        t = window.time_s.to_numpy()-case["start"]
        length = float(window.leader_length.iloc[0])
        offset = float(window.leader_y.iloc[0])
        observed = dict(t=t, leader_x=window.leader_y.to_numpy()-offset,
                        leader_v=window.leader_v.to_numpy(),
                        follower_x=window.local_y_m.to_numpy()-offset,
                        follower_v=window.speed_m_s.to_numpy(), leader_length=length)
        smooth_y = smooth_position(observed["leader_x"])
        leader = position_replay(t, smooth_y)
        reconstructed = np.array([leader(time) for time in t])
        meta.update(leader_position_preprocessing_rmse=rmse(smooth_y-observed["leader_x"]),
                    leader_speed_reconstruction_rmse=rmse(reconstructed[:, 1]-observed["leader_v"]),
                    leader_length=length, follower_length=float(window.vehicle_length_m.iloc[0]),
                    measured_min_net_gap=float(np.min(observed["leader_x"]-observed["follower_x"]-length)))
        np.savez_compressed(data_output / f"{name}_observed.npz", **observed,
                            leader_reconstructed_x=reconstructed[:, 0], leader_reconstructed_v=reconstructed[:, 1])
        runs, all_metrics[name] = {}, {}
        for model in MODELS:
            result, failure = simulate(model, leader, t[-1], t[1:],
                        [observed["follower_x"][0], observed["follower_v"][0]], args.dt, length)
            runs[model] = result
            m = metrics(result, failure, t[-1], None, observed)
            # Real leader is not assumed to become constant at the end.
            # Failure means physical/numerical termination; fit quality is a separate flag.
            m.update(physical_failure=failure is not None, following_failed=failure is not None,
                     failure_reason=failure["reason"] if failure else None,
                     recovered=None, final_10s_speed_mae=None)
            all_metrics[name][model] = m
            np.savez_compressed(data_output / f"{name}_{model.lower()}.npz", **result)
        # Evaluate all three on exactly the same available MEASURED timestamps.
        end = min(r["t"][-1] for r in runs.values())
        mask = observed["t"] <= end+1e-10
        for model, result in runs.items():
            m = all_metrics[name][model]
            shared = {k:(v[mask] if isinstance(v, np.ndarray) else v) for k,v in observed.items()}
            mm = metrics(result, None, t[-1], None, shared)
            for key in ("observed_position_rmse", "observed_speed_rmse", "observed_gap_rmse"):
                m["own_horizon_"+key] = m[key]
                m[key] = mm[key]
            m.update(comparison_end=float(end), comparison_samples=int(mask.sum()),
                     comparison_coverage=float(end/t[-1]),
                     poor_fit=(m["observed_position_rmse"] > 10 or m["observed_speed_rmse"] > 2),
                     speed_response_lag_vs_observed_follower=overlay_speed(result, shared["t"], shared["follower_v"]),
                     speed_response_lag_vs_leader=overlay_speed(result, shared["t"], reconstructed[mask, 1]))
            print(f"  {model}: x_RMSE={m['observed_position_rmse']:.3f} m, "
                  f"v_RMSE={m['observed_speed_rmse']:.3f} m/s, failure={m['failure_reason']}", flush=True)
        plot_scenario(f"NGSIM {name}: F{case['follower']} / L{case['leader']} / lane {case['lane']}",
                      runs, all_metrics[name], leader, t[-1], args.output, observed)
    comparison_plot(all_metrics, args.output)
    payload = dict(source=str(args.source.resolve()), source_sha256=hashlib.sha256(args.source.read_bytes()).hexdigest(),
                   dt=args.dt, parameters=PARAMETERS, audit=audit, selected=metadata, results=all_metrics,
                   selection="No simulation outcomes used; steady=min speed std (mean>=3), decelerating=max 5s-mean speed drop, variable=max speed std; disjoint vehicle IDs",
                   coordinate_definition="front-center; net gap=leader_y-follower_y-leader_length",
                   preprocessing="Leader only: 11-point centered moving mean, linear edge extension, monotone cubic Hermite; speed=analytic position derivative. Raw follower retained for errors.")
    (args.output / "metrics.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    report = ["# NGSIM 实测双车实验", "", "与双车实验中的人工前车轨迹实验并列。三个场景均为30秒、301个实测帧；前车由实测位置重建，仅后车采用模型。未标定模型参数。", "",
              "|类型|后车/前车|车道|数据相对时段(s)|前车速度标准差(m/s)|", "|---|---|---|---|---|"]
    for name, c in metadata.items():
        report.append(f"|{name}|{c['follower']}/{c['leader']}|{c['lane']}|{c['start']:.1f}–{c['end']:.1f}|{c['leader_speed_std']:.3f}|")
    report += ["", "|场景|模型|位置RMSE(m)|速度RMSE(m/s)|净间距RMSE(m)|最小净间距(m)|失败|", "|---|---|---:|---:|---:|---:|---|"]
    for name, ms in all_metrics.items():
        for model, m in ms.items():
            report.append(f"|{name}|{model}|{m['observed_position_rmse']:.3f}|{m['observed_speed_rmse']:.3f}|{m['observed_gap_rmse']:.3f}|{m['min_net_gap']:.3f}|{m['failure_reason'] or '无'}|")
    report += ["", "## 如何理解结果", "",
        "误差以原始实测后车为基准；每个场景的三模型RMSE取共同有效时段，避免失败模型因提前终止获得虚假的低误差。完整覆盖比例、各自时段误差和失败时间见 metrics.json。最小净间距按各模型有效轨迹统计。",
        "跟驰失败指碰撞、倒退或数值异常导致终止；poor_fit 单列为位置RMSE>10 m或速度RMSE>2 m/s，不与物理失败混为一谈。原模型不裁剪负速度；倒退触发停止，不代表实测司机倒退。",
        "速度响应同时输出相对于前车及实测后车的最优时间平移（-5至5秒、0.1秒步长）；正值表示模拟响应较晚，边界值表示搜索范围可能不足，稳速数据或波动标准差<0.5 m/s时N/A。这是描述性对齐指标，不是驾驶员反应时间估计。",
        "## 数据筛选与处理", "",
        "源文件没有前车编号，先按每帧同车道纵向排序，取最近前车，再筛选两者均为小汽车、车道1–5、关系连续不变、0.1秒无缺帧、净间距1–60 m且初始净间距>=5 m、速度0–35 m/s、位置无明显倒退、前车车长不变。每段取30秒窗口，步进5秒；前后车均要求平滑位置的导数与报告速度的绝对差95分位不超过2 m/s。筛选未使用模型仿真结果。",
        "按低速度波动、最大减速量、高速度波动挑选三个互不共享车辆的示例。这是案例比较，不代表全NGSIM的模型排名。前后车均在整个窗口保持原车道，最近前车关系为推断值，非原始前车ID真值。",
        "前车位置做11点中心移动平均（1.1秒，边界线性延伸），再做单调三次Hermite插值，速度由位置解析求导，保证输入速度与位置相容。实测后车位置、速度不平滑，用于误差评估；前车原始速度与重建速度差及位置平滑误差均记录在JSON。",
        "使用前车实际长度计算净间距，所有模型从同一实测后车位置和速度出发。OVM采用Jiang论文给出的有量纲V函数与kappa=0.85；FVDM用kappa=0.41、lambda=0.5；IDM使用原论文表I。未进行参数拟合，不能将默认参数的误差解读为模型能力上限。",
        "", "字段依据：[FHWA I-80数据字典](https://ops.fhwa.dot.gov/publications/fhwahop08054/sect7.htm)。源文件路径、SHA256、车辆ID、时间范围、筛选数和全部指标见 metrics.json。"]
    (args.output / "实验报告.md").write_text("\n".join(report), encoding="utf-8")
    print(f"Saved to {args.output.resolve()}")


if __name__ == "__main__":
    main()
