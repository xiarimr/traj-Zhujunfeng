"""OVM / FVDM / IDM 模型仿真实验（只依赖 numpy 和 matplotlib）。

运行：python platoon_experiments/run_experiments.py --model all
单个：python platoon_experiments/run_experiments.py --model ovm
精度：python platoon_experiments/run_experiments.py --model all --dt 0.025

统一约定：数组下标 i+1 为前车（环道最后一辆的前车为第 0 辆）；
h = x_front - x，s = h - length，dv = v_front - v。
不截断速度、加速度或期望间距，以保留所给原始公式；若车辆重叠则报错。

来源：
OVM: Bando et al., Phys. Rev. E 51, 1035 (1995), Eqs. (1), (24).
FVDM: Jiang et al., Phys. Rev. E 64, 017101 (2001), Eqs. (5), (7).
IDM: Treiber et al., cond-mat/0002177v2, Eqs. (6)-(8), Table I.

三个模型均用于100辆车的环道车队。OVM/FVDM 使用论文环道设置；
IDM 使用论文参数和自设环道场景，属于机制复现。
"""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def ovm_acceleration(h, v, sensitivity=1.0):
    """Bando 的无量纲 OVM。"""
    optimal = np.tanh(h - 2.0) + np.tanh(2.0)
    return sensitivity * (optimal - v)


def fvdm_acceleration(h, v, dv, sensitivity=0.41, velocity_gain=0.5):
    """h 为位置间距；最优速度函数内部再扣除 5 m 车长。"""
    optimal = 6.75 + 7.91 * np.tanh(0.13 * (h - 5.0) - 1.57)
    # 论文使用 lambda=0.5 (h<=100 m), 否则 lambda=0。
    gain = np.where(h <= 100.0, velocity_gain, 0.0)
    return sensitivity * (optimal - v) + gain * dv


IDM_PARAMETERS = dict(v0=120.0 / 3.6, T=1.6, a=0.73, b=1.67,
                      delta=4.0, s0=2.0, s1=0.0, length=5.0)


def idm_desired_gap(v, dv, p=IDM_PARAMETERS):
    # dv=前车-本车，故与 IDM 原文 approaching rate 的符号相反。
    extra = p["s1"] * np.sqrt(v / p["v0"]) if p["s1"] else 0.0
    return p["s0"] + extra + p["T"] * v - v * dv / (2 * np.sqrt(p["a"] * p["b"]))


def idm_acceleration(s, v, dv, p=IDM_PARAMETERS):
    desired = idm_desired_gap(v, dv, p)
    return p["a"] * (1 - (v / p["v0"]) ** p["delta"] - (desired / s) ** 2)


def rk4_step(rhs, t, y, dt):
    """同一时刻同步计算所有车辆，避免顺序更新造成偏差。"""
    k1 = rhs(t, y)
    k2 = rhs(t + dt / 2, y + dt * k1 / 2)
    k3 = rhs(t + dt / 2, y + dt * k2 / 2)
    k4 = rhs(t + dt, y + dt * k3)
    return y + dt * (k1 + 2 * k2 + 2 * k3 + k4) / 6


def integrate(rhs, initial, duration, dt):
    steps = int(np.ceil(duration / dt))
    times = np.linspace(0, duration, steps + 1)
    actual_dt = times[1] - times[0]
    states = np.empty((steps + 1,) + initial.shape)
    states[0] = initial
    for k in range(steps):
        states[k + 1] = rk4_step(rhs, times[k], states[k], actual_dt)
        if not np.all(np.isfinite(states[k + 1])):
            raise RuntimeError("Non-finite state; reduce --dt and inspect parameters.")
    return times, states


def ring_headways(x, road_length):
    # 位置保持展开，不逐车取模，以保留车辆顺序及精确车距。
    h = np.roll(x, -1, axis=-1) - x
    h[..., -1] += road_length
    return h


def simulate_ring(model, road_length, duration, dt):
    count = 100
    x = np.arange(count, dtype=float) * road_length / count
    x[0] += 0.1 if model == "ovm" else 1.0
    if model == "ovm":
        v = np.zeros(count)  # Bando 原文的静止初始条件。
        length = 0.0         # 原文忽略车长，采用无量纲量。
    elif model == "fvdm":
        v = np.full(count, 6.75 + 7.91 * np.tanh(0.13 * (road_length / count - 5) - 1.57))
        length = 5.0
    elif model == "idm":
        length = IDM_PARAMETERS["length"]
        gap = road_length / count - length
        # 均匀流 dv=0，通过二分求解 IDM 加速度为0的速度。
        low, high = 0.0, IDM_PARAMETERS["v0"]
        for _ in range(80):
            middle = (low + high) / 2
            if idm_acceleration(gap, middle, 0.0) > 0:
                low = middle
            else:
                high = middle
        v = np.full(count, (low + high) / 2)
    else:
        raise ValueError(f"Unknown model: {model}")

    def rhs(t, state):
        pos, speed = state
        h = ring_headways(pos, road_length)
        if np.min(h - length) <= 0:
            raise RuntimeError(f"{model}: vehicle overlap at t={t:.4f}; reduce dt or inspect dynamics.")
        dv = np.roll(speed, -1) - speed
        if model == "ovm":
            acc = ovm_acceleration(h, speed)
        elif model == "fvdm":
            acc = fvdm_acceleration(h, speed, dv)
        else:
            acc = idm_acceleration(h - length, speed, dv)
        return np.array([speed, acc])

    times, states = integrate(rhs, np.array([x, v]), duration, dt)
    h = ring_headways(states[:, 0], road_length)
    return dict(t=times, x=states[:, 0], v=states[:, 1], h=h,
                s=h - length, road_length=road_length)


def plot_ring(data, title, output, dimensional=True):
    t, x, v, s = (data[k] for k in ("t", "x", "v", "s"))
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
    stride = max(1, len(t) // 1200)
    sampled = slice(None, None, stride)
    scatter = axes[0, 0].scatter(
        (x[sampled] % data["road_length"]).ravel(),
        np.repeat(t[sampled], x.shape[1]), c=v[sampled].ravel(),
        s=1, cmap="viridis", rasterized=True)
    axes[0, 0].set(xlabel="Position [m]" if dimensional else "Position", ylabel="Time [s]" if dimensional else "Time",
                   title="Space-time diagram")
    fig.colorbar(scatter, ax=axes[0, 0], label="Speed [m/s]" if dimensional else "Speed")
    for i in [0, 25, 50, 75]:
        axes[0, 1].plot(t, v[:, i], label=f"Vehicle {i}", lw=1)
    axes[0, 1].set(xlabel="Time", ylabel="Speed", title="Speed histories")
    axes[0, 1].legend(fontsize=8)
    for moment in [0, t[-1] * 0.15, t[-1]]:
        k = np.argmin(abs(t - moment))
        axes[1, 0].plot(np.arange(v.shape[1]), v[k], label=f"t={t[k]:g}")
    axes[1, 0].set(xlabel="Vehicle index", ylabel="Speed", title="Speed snapshots")
    axes[1, 0].legend(fontsize=8)
    late = t >= t[-1] * 0.5
    axes[1, 1].plot(s[late, 0], v[late, 0], lw=0.8)
    axes[1, 1].set(xlabel="Net gap [m]" if dimensional else "Headway", ylabel="Speed", title="Late-time gap-speed orbit (vehicle 0)")
    fig.suptitle(title)
    fig.savefig(output, dpi=160)
    plt.close(fig)


def ring_metrics(data):
    tail = data["t"] >= data["t"][-1] * 0.9
    h = data["h"]
    return dict(min_gap=float(data["s"].min()), min_speed=float(data["v"].min()),
                max_speed=float(data["v"].max()),
                final_speed_std=float(data["v"][-1].std()),
                late_mean_speed_std=float(data["v"][tail].std(axis=1).mean()),
                max_ring_length_error=float(abs(h.sum(axis=1) - data["road_length"]).max()))


def run_ovm(output, dt):
    summary = {}
    # L=200 为原文 realistic model 实验；L=400 是增加的稳定对照。
    for label, road_length in [("unstable", 200.0), ("stable_control", 400.0)]:
        data = simulate_ring("ovm", road_length, 1000.0, dt)
        np.savez_compressed(output / "data" / f"ovm_{label}.npz", **data)
        plot_ring(data, f"OVM: {label}, N=100, L={road_length:g}, kappa=1",
                  output / f"ovm_{label}.png", dimensional=False)
        summary[label] = ring_metrics(data)
        summary[label]["V_prime_at_mean_headway"] = float(1 - np.tanh(road_length / 100 - 2) ** 2)
        summary[label]["stability_threshold"] = 0.5
    return summary


def run_fvdm(output, dt):
    data = simulate_ring("fvdm", 1500.0, 2000.0, dt)
    np.savez_compressed(output / "data" / "fvdm.npz", **data)
    plot_ring(data, "FVDM: N=100, L=1500 m, kappa=0.41, lambda=0.5",
              output / "fvdm.png")
    summary = ring_metrics(data)
    summary["V_prime_at_mean_headway"] = float(7.91 * 0.13 * (1 - np.tanh(0.13 * 10 - 1.57) ** 2))
    summary["stability_threshold"] = 0.41 / 2 + 0.5
    return summary






def run_idm(output, dt):
    # 与原论文的实测高速公路场景区分：这里是自设的环道车队实验。
    data = simulate_ring("idm", 2500.0, 1000.0, dt)
    np.savez_compressed(output / "data" / "idm.npz", **data)
    plot_ring(data, "IDM platoon: N=100, L=2500 m, paper parameters",
              output / "idm.png")
    summary = ring_metrics(data)
    summary.update(parameters=IDM_PARAMETERS, vehicle_count=100,
                   road_length=2500.0, duration=1000.0,
                   scenario="custom ring, uniform equilibrium speed, vehicle 0 shifted +1 m")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", choices=["all", "ovm", "fvdm", "idm"], default="all")
    parser.add_argument("--dt", type=float, default=0.05, help="RK4 integration step (default: 0.05)")
    parser.add_argument("--output", type=Path, default=Path(__file__).resolve().parent / "results")
    args = parser.parse_args()
    if not np.isfinite(args.dt) or not 0 < args.dt <= 0.1:
        parser.error("--dt must be finite and in (0, 0.1].")
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "data").mkdir(parents=True, exist_ok=True)
    runners = dict(ovm=run_ovm, fvdm=run_fvdm, idm=run_idm)
    summary = {"dt": args.dt, "method": "RK4", "dv_convention": "leader minus follower"}
    selected = runners if args.model == "all" else {args.model: runners[args.model]}
    for name, runner in selected.items():
        print(f"Running {name.upper()} ...", flush=True)
        summary[name] = runner(args.output, args.dt)
        print(json.dumps(summary[name], indent=2, ensure_ascii=False), flush=True)
    summary_path = args.output / f"summary_{args.model}.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Results saved to: {args.output.resolve()}")


if __name__ == "__main__":
    main()
