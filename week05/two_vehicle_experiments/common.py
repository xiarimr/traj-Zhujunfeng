"""Three physical-unit, leader-follower experiments. Requires numpy, matplotlib.

python two_vehicle_experiments/artificial/run_experiments.py
python two_vehicle_experiments/artificial/run_experiments.py --dt 0.01 --output results_fine

Optional measured NPZ: t, leader_x, leader_v, follower_x, follower_v (SI units).
Measured leader is replayed with cubic Hermite interpolation; all models start
from the measured follower state. No measured follower data is used for tuning.
"""
import argparse
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

MODELS = ("OVM", "FVDM", "IDM")
COLORS = dict(OVM="#d95f02", FVDM="#1b9e77", IDM="#7570b3")
LENGTH = 5.0
PARAMETERS = {
    "OVM": {"kappa": 0.85, "V1": 6.75, "V2": 7.91, "C1": 0.13, "C2": 1.57},
    "FVDM": {"kappa": 0.41, "lambda": 0.5, "cutoff_headway": 100.0,
              "V1": 6.75, "V2": 7.91, "C1": 0.13, "C2": 1.57},
    "IDM": {"v0": 120 / 3.6, "T": 1.6, "a": 0.73, "b": 1.67,
            "delta": 4, "s0": 2, "s1": 0},
}
# Segments: (duration seconds, prescribed leader acceleration m/s^2).
SCENARIOS = {
    "constant": dict(segments=[(120, 0)], gap=20, initial_v=10, event=None),
    "brake_recover": dict(segments=[(30, 0), (5, -1), (20, 0), (5, 1), (60, 0)],
                          gap=20, initial_v=10, event=(30, 35, 10, 5)),
    "stop_restart": dict(segments=[(30, 0), (10, -1), (20, 0), (10, 1), (50, 0)],
                         gap=20, initial_v=10, event=(30, 40, 10, 0)),
    "emergency_tight": dict(segments=[(2, -5), (30, 0)], gap=4, initial_v=10,
                            event=(0, 2, 10, 0)),
}


class FailedStep(Exception):
    def __init__(self, reason, time, gap=None):
        self.reason, self.time, self.gap = reason, float(time), gap


def acceleration(model, gap, v, dv, leader_length=LENGTH):
    """dv = leader minus follower. No clipping, caps or emergency overrides."""
    p = PARAMETERS[model]
    if model in ("OVM", "FVDM"):
        optimal = p["V1"] + p["V2"] * np.tanh(p["C1"] * gap - p["C2"])
        result = p["kappa"] * (optimal - v)
        if model == "FVDM" and gap + leader_length <= p["cutoff_headway"]:
            result += p["lambda"] * dv
        return float(result)
    desired = p["s0"] + p["T"] * v - v * dv / (2 * np.sqrt(p["a"] * p["b"]))
    return float(p["a"] * (1 - (v / p["v0"]) ** p["delta"] - (desired / gap) ** 2))


def make_leader(spec):
    segments = []
    t, x, v = 0.0, 0.0, float(spec["initial_v"])
    for duration, a in spec["segments"]:
        segments.append((t, t + duration, x, v, a))
        x += v * duration + 0.5 * a * duration ** 2
        v += a * duration
        t += duration

    def leader(time):
        for start, end, x0, v0, a in segments:
            if time <= end + 1e-10:
                u = time - start
                return x0 + v0 * u + 0.5 * a * u * u, v0 + a * u
        raise ValueError("Time beyond leader trajectory")
    return leader, t, [s[1] for s in segments]


def load_observed(path):
    with np.load(path, allow_pickle=False) as raw:
        data = {key: np.asarray(raw[key], dtype=float) for key in
                ("t", "leader_x", "leader_v", "follower_x", "follower_v")}
    n = len(data["t"])
    if n < 2 or any(a.shape != (n,) or not np.isfinite(a).all() for a in data.values()):
        raise ValueError("Measured arrays must be finite 1D arrays of equal length >= 2")
    if np.any(np.diff(data["t"]) <= 0) or np.min(data["leader_v"]) < 0:
        raise ValueError("Measured timestamps must increase and leader speeds be nonnegative")
    data["t"] = data["t"] - data["t"][0]
    if data["leader_x"][0] - data["follower_x"][0] - LENGTH <= 0:
        raise ValueError("Initial measured net gap must be positive (assumes 5 m vehicles)")

    def leader(t):
        i = int(np.clip(np.searchsorted(data["t"], t, side="right") - 1, 0, n - 2))
        h = data["t"][i + 1] - data["t"][i]
        u = (t - data["t"][i]) / h
        x0, x1 = data["leader_x"][i:i + 2]
        v0, v1 = data["leader_v"][i:i + 2]
        x = (2*u**3-3*u**2+1)*x0 + (u**3-2*u**2+u)*h*v0 + (-2*u**3+3*u**2)*x1 + (u**3-u**2)*h*v1
        v = (6*u**2-6*u)*x0/h + (3*u**2-4*u+1)*v0 + (-6*u**2+6*u)*x1/h + (3*u**2-2*u)*v1
        return x, v
    return data, leader


def simulate(model, leader, duration, boundaries, initial, dt, leader_length=LENGTH):
    # Include leader breakpoints exactly so steps never straddle acceleration changes.
    grid = np.unique(np.r_[np.arange(0, duration, dt), boundaries, duration])
    times, states = [0.0], [np.array(initial, dtype=float)]
    failure = None

    def rhs(t, state):
        if not np.isfinite(state).all():
            raise FailedStep("nonfinite_state", t)
        lx, lv = leader(t)
        gap = lx - state[0] - leader_length
        if gap <= 0:
            raise FailedStep("collision", t, float(gap))
        if state[1] < -1e-3:
            raise FailedStep("reverse_motion", t, float(gap))
        acc = acceleration(model, gap, state[1], lv - state[1], leader_length)
        if not np.isfinite(acc):
            raise FailedStep("nonfinite_acceleration", t, float(gap))
        return np.array([state[1], acc])

    for start, end in zip(grid[:-1], grid[1:]):
        h, y = end - start, states[-1]
        try:
            k1 = rhs(start, y)
            k2 = rhs(start + h/2, y + h*k1/2)
            k3 = rhs(start + h/2, y + h*k2/2)
            k4 = rhs(end, y + h*k3)
            new = y + h*(k1 + 2*k2 + 2*k3 + k4)/6
            rhs(end, new)
        except FailedStep as error:
            failure = dict(reason=error.reason, first_detected_time=error.time,
                           sampled_gap=error.gap, last_valid_time=times[-1],
                           note="Detected at an RK4 stage; event time is approximate, refine dt.")
            break
        times.append(float(end))
        states.append(new)
    t, state = np.asarray(times), np.asarray(states)
    front = np.array([leader(time) for time in t])
    gap = front[:, 0] - state[:, 0] - leader_length
    acc = np.array([acceleration(model, s, v, lv-v, leader_length) for s, v, lv in zip(gap, state[:, 1], front[:, 1])])
    return dict(t=t, x=state[:, 0], v=state[:, 1], leader_x=front[:, 0],
                leader_v=front[:, 1], s=gap, acceleration=acc), failure


def rmse(values):
    return float(np.sqrt(np.mean(np.square(values))))


def crossing(t, v, target, start, descending):
    indices = np.flatnonzero((t >= start) & ((v <= target) if descending else (v >= target)))
    if not len(indices):
        return None
    i = indices[0]
    if i == 0 or t[i-1] < start or v[i] == v[i-1]:
        return float(t[i])
    return float(t[i-1] + (target-v[i-1])*(t[i]-t[i-1])/(v[i]-v[i-1]))


def metrics(data, failure, duration, event, observed=None):
    t, v, lv, gap = (data[key] for key in ("t", "v", "leader_v", "s"))
    tail = t >= max(0, duration - 10)
    completed = failure is None
    tail_mae = float(np.mean(abs(v[tail]-lv[tail]))) if completed and tail.any() else None
    recovered = tail_mae <= 0.5 if tail_mae is not None else None
    closing = v - lv
    ttc = gap[closing > 1e-6] / closing[closing > 1e-6]
    result = dict(completed=completed, failure_event=failure,
                  following_failed=(not completed) or (recovered is False),
                  failure_reason=failure["reason"] if failure else ("not_recovered" if recovered is False else None),
                  simulated_until=float(t[-1]), coverage_fraction=float(t[-1]/duration),
                  speed_tracking_rmse=rmse(v-lv), max_speed_difference=float(abs(v-lv).max()),
                  min_net_gap=float(gap.min()), min_gap_is_pre_failure=not completed,
                  min_ttc=float(ttc.min()) if len(ttc) else None,
                  min_acceleration=float(data["acceleration"].min()),
                  max_acceleration=float(data["acceleration"].max()),
                  final_speed_difference=float(v[-1]-lv[-1]),
                  final_10s_speed_mae=tail_mae, recovered=recovered,
                  response_delay=None, response_delay_status="not_applicable",
                  observed_position_rmse=None, observed_speed_rmse=None,
                  observed_gap_rmse=None, observed_status="no_measured_trajectory")
    if event:
        start, end, before, after = event
        target = (before + after)/2
        front_time = crossing(t, lv, target, start, before > after)
        back_time = crossing(t, v, target, start, before > after)
        result["response_delay"] = back_time - front_time if front_time is not None and back_time is not None else None
        result["response_delay_status"] = "midpoint_crossing" if result["response_delay"] is not None else "target_not_reached_before_end_or_failure"
    if observed is not None:
        # RMSE only over available measured timestamps; never extrapolate a failed run.
        mask = observed["t"] <= t[-1] + 1e-10
        ot = observed["t"][mask]
        ox, ov = observed["follower_x"][mask], observed["follower_v"][mask]
        measured_gap = observed["leader_x"][mask] - ox - observed.get("leader_length", LENGTH)
        result.update(observed_position_rmse=rmse(np.interp(ot, t, data["x"])-ox),
                      observed_speed_rmse=rmse(np.interp(ot, t, v)-ov),
                      observed_gap_rmse=rmse(np.interp(ot, t, gap)-measured_gap),
                      observed_status="full_run" if completed else "valid_prefix_only",
                      observed_samples_used=int(mask.sum()))
    return result


def plot_scenario(name, runs, results, leader, duration, output, observed=None):
    fig, axes = plt.subplots(2, 2, figsize=(13, 8), constrained_layout=True)
    lt = np.linspace(0, duration, 2500)
    front = np.array([leader(t) for t in lt])
    axes[0, 0].plot(lt, front[:, 0], "k--", label="Prescribed leader")
    axes[0, 1].plot(lt, front[:, 1], "k--", label="Prescribed leader")
    for model, data in runs.items():
        for ax, key in zip(axes.flat, ("x", "v", "s", "acceleration")):
            ax.plot(data["t"], data[key], color=COLORS[model], label=model, lw=1.5)
            if not results[model]["completed"]:
                ax.plot(data["t"][-1], data[key][-1], "x", color=COLORS[model], ms=9)
    if observed is not None:
        axes[0, 0].plot(observed["t"], observed["follower_x"], "k:", label="Measured follower")
        axes[0, 1].plot(observed["t"], observed["follower_v"], "k:", label="Measured follower")
        axes[1, 0].plot(observed["t"], observed["leader_x"]-observed["follower_x"]-observed.get("leader_length", LENGTH), "k:", label="Measured gap")
    for ax, label in zip(axes.flat, ("Position [m]", "Speed [m/s]", "Net gap [m]", "Acceleration [m/s^2]")):
        ax.set(xlabel="Time [s]", ylabel=label)
        ax.grid(alpha=0.2)
        ax.legend(fontsize=8)
    axes[1, 0].axhline(0, color="red", ls="--", lw=0.8)
    fig.suptitle(f"{name}: leader prescribed; follower modeled (x = last valid point)")
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
    fig.savefig(output / f"{safe_name}.png", dpi=160)
    plt.close(fig)


def plot_overview(summary, output):
    names = list(summary)
    fig, axes = plt.subplots(2, 2, figsize=(14, 9), constrained_layout=True)
    positions = np.arange(len(names))
    for index, model in enumerate(MODELS):
        offset = (index-1)*0.24
        for ax, key in [(axes[0, 0], "speed_tracking_rmse"), (axes[0, 1], "min_net_gap")]:
            values = [summary[name][model][key] for name in names]
            bars = ax.bar(positions+offset, values, 0.24, color=COLORS[model], label=model)
            for bar, name in zip(bars, names):
                if not summary[name][model]["completed"]:
                    bar.set_hatch("///")
        values = [int(summary[name][model]["following_failed"]) for name in names]
        axes[1, 0].bar(positions+offset, values, 0.24, color=COLORS[model], label=model)
    axes[0, 0].set(ylabel="Speed tracking RMSE vs leader [m/s]", title="Hatched bars: valid prefix only; not equal horizons")
    axes[0, 1].set(ylabel="Minimum valid net gap [m]", title="Failure may occur after last valid sample")
    axes[1, 0].set(ylabel="Following failed (1=yes)", yticks=[0, 1], ylim=(0, 1.25))
    for ax in [axes[0, 0], axes[0, 1], axes[1, 0]]:
        ax.set_xticks(positions, names, rotation=15, ha="right")
        ax.legend(fontsize=8)
        ax.grid(axis="y", alpha=0.2)
    measured = [name for name in names if summary[name]["OVM"]["observed_position_rmse"] is not None]
    if measured:
        for i, model in enumerate(MODELS):
            axes[1, 1].bar(np.arange(len(measured))+(i-1)*0.24,
                           [summary[n][model]["observed_position_rmse"] for n in measured],
                           0.24, color=COLORS[model], label=model)
        axes[1, 1].set_xticks(np.arange(len(measured)), measured)
        axes[1, 1].set(ylabel="Observed follower position RMSE [m]")
        axes[1, 1].legend()
    else:
        axes[1, 1].axis("off")
        axes[1, 1].text(0.5, 0.5, "Observed trajectory error: N/A\n\nNo measured follower trajectory supplied.\nLeader tracking error is a different metric.\nUse --observed measured.npz to evaluate.",
                         ha="center", va="center", transform=axes[1, 1].transAxes, fontsize=12)
    fig.suptitle("Two-vehicle comparison: identical initial states within each scenario")
    fig.savefig(output / "comparison.png", dpi=160)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dt", type=float, default=0.02)
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent / "artificial" / "results")
    parser.add_argument("--observed", type=Path)
    args = parser.parse_args()
    if not np.isfinite(args.dt) or not 0 < args.dt <= 0.1:
        parser.error("dt must lie in (0, 0.1]")
    args.output.mkdir(parents=True, exist_ok=True)
    data_output = args.output / "data"
    data_output.mkdir(parents=True, exist_ok=True)
    cases = []
    for name, spec in SCENARIOS.items():
        leader, duration, boundaries = make_leader(spec)
        cases.append((name, leader, duration, boundaries,
                      [-spec["gap"]-LENGTH, spec["initial_v"]], spec["event"], None))
    if args.observed:
        observed, leader = load_observed(args.observed)
        cases.append(("measured_replay", leader, float(observed["t"][-1]), observed["t"][1:],
                      [observed["follower_x"][0], observed["follower_v"][0]], None, observed))
    summary = {}
    for name, leader, duration, boundaries, initial, event, observed in cases:
        runs, summary[name] = {}, {}
        for model in MODELS:
            data, failure = simulate(model, leader, duration, boundaries, initial, args.dt)
            runs[model] = data
            np.savez_compressed(data_output / f"{name}_{model.lower()}.npz", **data)
            summary[name][model] = metrics(data, failure, duration, event, observed)
            print(f"{name:18} {model:5} min_gap={data['s'].min():.4f} "
                  f"status={summary[name][model]['failure_reason'] or 'completed'}", flush=True)
        plot_scenario(name, runs, summary[name], leader, duration, args.output, observed)
    plot_overview(summary, args.output)
    (args.output / "metrics.json").write_text(json.dumps(dict(dt=args.dt, parameters=PARAMETERS,
             vehicle_length=LENGTH, scenarios=SCENARIOS, results=summary), ensure_ascii=False,
             indent=2, allow_nan=False), encoding="utf-8")
    report = ["# 人工前车轨迹双车实验", "", "前车轨迹按解析公式设定，仅后车采用跟驰模型。与双车实验中的NGSIM实测轨迹实验并列。单位：米、秒。", "",
              "|场景|模型|速度跟踪 RMSE (m/s)|最小净间距 (m)|减速响应延迟 (s)|跟驰失败原因|",
              "|---|---|---:|---:|---:|---|"]
    for name, results in summary.items():
        for model, m in results.items():
            delay = "N/A" if m["response_delay"] is None else f"{m['response_delay']:.3f}"
            prefix = "（失败前）" if not m["completed"] else ""
            report.append(f"|{name}|{model}|{m['speed_tracking_rmse']:.4f}{prefix}|{m['min_net_gap']:.4f}{prefix}|{delay}|{m['failure_reason'] or '无'}|")
    report += ["", "速度跟踪误差是后车与前车速度之差，不是真实轨迹误差。不同初始平衡间距导致的初始响应也包含在统计中。",
               "真实轨迹误差：" + ("已计算，详见 metrics.json。" if args.observed else "N/A，人工场景没有实测后车真值；NGSIM实验提供此项指标。"),
               "", "失败：净间距<=0、速度<-0.001 m/s、数值非有限，或完整运行后最后10秒速度差MAE>0.5 m/s。",
               "碰撞/倒退在 RK4 阶段检测到即停止；事件时间为近似值。最小间距与RMSE仅覆盖已保存的有效轨迹，失败案例不能按较小RMSE判定更好。",
               "减速响应延迟：后车首次到达减速前后速度中点的时刻减前车相应时刻；未到达则N/A。负值表示提前越过该速度，不能当作驾驶员反应时间。",
               "完整参数、覆盖比例、失败时间、TTC和真实轨迹误差保存在 metrics.json。"]
    (args.output / "结果说明.md").write_text("\n".join(report), encoding="utf-8")
    print(f"Saved to {args.output.resolve()}")


if __name__ == "__main__":
    main()
