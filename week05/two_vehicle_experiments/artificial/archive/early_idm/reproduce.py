import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

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


def leader_trajectory(t):
    """自定义前车：20 m/s -> 5 m/s -> 20 m/s；位置为速度的解析积分。"""
    if t < 30:
        return 20 * t, 20.0
    if t < 40:
        u = t - 30
        return 600 + 20 * u - 0.75 * u ** 2, 20 - 1.5 * u
    if t < 60:
        return 725 + 5 * (t - 40), 5.0
    if t < 75:
        u = t - 60
        return 825 + 5 * u + 0.5 * u ** 2, 5 + u
    return 1012.5 + 20 * (t - 75), 20.0


def run_idm(output, dt):
    p = IDM_PARAMETERS
    initial_speed = 20.0
    equilibrium_gap = (p["s0"] + p["T"] * initial_speed) / np.sqrt(1 - (initial_speed / p["v0"]) ** p["delta"])

    def rhs(t, state):
        x, v = state
        front_x, front_v = leader_trajectory(t)
        s = front_x - x - p["length"]
        if s <= 0:
            raise RuntimeError(f"IDM collision at t={t:.4f}")
        return np.array([v, idm_acceleration(s, v, front_v - v)])

    times, states = integrate(rhs, np.array([-equilibrium_gap - p["length"], initial_speed]), 150.0, dt)
    front = np.array([leader_trajectory(t) for t in times])
    gap = front[:, 0] - states[:, 0] - p["length"]
    dv = front[:, 1] - states[:, 1]
    desired = idm_desired_gap(states[:, 1], dv)
    acceleration = idm_acceleration(gap, states[:, 1], dv)
    np.savez_compressed(output / "idm.npz", t=times, x=states[:, 0], v=states[:, 1],
                        leader_x=front[:, 0], leader_v=front[:, 1], s=gap,
                        s_star=desired, acceleration=acceleration)
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
    for col, name, units in [(0, "Position", "m"), (1, "Speed", "m/s")]:
        axes[0, col].plot(times, front[:, col], label="Leader")
        axes[0, col].plot(times, states[:, col], label="IDM follower")
        axes[0, col].set(xlabel="Time [s]", ylabel=f"{name} [{units}]")
        axes[0, col].legend()
    axes[1, 0].plot(times, gap, label="Actual net gap")
    axes[1, 0].plot(times, desired, "--", label="Dynamic desired gap s*")
    axes[1, 0].set(xlabel="Time [s]", ylabel="Gap [m]")
    axes[1, 0].legend()
    axes[1, 1].plot(times, acceleration)
    axes[1, 1].axhline(0, color="gray", lw=0.7)
    axes[1, 1].set(xlabel="Time [s]", ylabel="Acceleration [m/s^2]")
    fig.suptitle("IDM: response to a prescribed slowing / accelerating leader")
    fig.savefig(output / "idm.png", dpi=160)
    plt.close(fig)
    return dict(parameters=p, initial_equilibrium_gap=float(equilibrium_gap),
                initial_acceleration=float(acceleration[0]), min_gap=float(gap.min()),
                min_speed=float(states[:, 1].min()), max_speed=float(states[:, 1].max()),
                min_acceleration=float(acceleration.min()), max_acceleration=float(acceleration.max()),
                final_speed_error=float(states[-1, 1] - front[-1, 1]),
                final_gap_error=float(gap[-1] - equilibrium_gap))

if __name__ == '__main__':
    output = Path(__file__).resolve().parent
    summary = run_idm(output, 0.05)
    (output / 'metrics.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
