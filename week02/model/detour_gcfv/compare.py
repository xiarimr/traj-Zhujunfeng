"""对比出图 —— 实验 / 主模型 / baseline1。

    python week02/model/detour_gcfv/compare.py

读 week02/results/out/ 里 run.py 落下的轨迹，出图到 week02/results/figures/。

轨迹图沿用 week02/model/plot_circle.py 的视觉规范（细线 + 方位角色相环 + 起终点标记），
所以三格里的颜色含义完全一致，可以逐条对着看。颜色直接 import 那个模块，不复制一份 ——
同一条配色规则在两处各自实现，早晚会漂。

分布对比用分类色第 1/2/3 槽（蓝 / 橙 / 青），顺序固定：实验永远是蓝的。

只出亮色版（本项目口径），不生成深色版。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D

# 直接跑脚本时子目录不是包，把 model/ 挂进 sys.path（plot_circle.py 就在那里）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from plot_circle import MODES, hue_color  # noqa: E402
from detour_gcfv.data import RING_RADIUS_M, load_experiment  # noqa: E402
from detour_gcfv.metrics import CENTER_CROSSING_THRESHOLD, evaluate  # noqa: E402
from detour_gcfv.paths import FIGURES_DIR as FIG_DIR, OUT_DIR  # noqa: E402

# 分类色固定槽位：实验 = 1 蓝，主模型 = 2 橙，baseline = 3 青。顺序不可换 ——
# 换色号会破坏"实验永远是蓝的"这个记忆点。
SERIES_COLORS = {
    "实验": "#2a78d6",
    "detour-aware": "#eb6834",
    "baseline1 (no detour)": "#1baf7a",
}

# CSV 文件名 -> 图上标签
MODEL_LABELS = {"main": "detour-aware", "baseline1": "baseline1 (no detour)"}

AZIMUTH_STEPS = 361


def _wheel(palette) -> list:
    return [hue_color(palette["wheel_L"], palette["wheel_C"], a)
            for a in np.linspace(0, 360, AZIMUTH_STEPS)]


def load_sim(path: Path, frames: np.ndarray, n_ped: int) -> np.ndarray:
    """读回 run.py 落下的轨迹 CSV（`行人ID 帧号 x y`，厘米），返回 (N,T,2) 米。"""
    table = np.loadtxt(path)
    positions = np.full((n_ped, frames.size, 2), np.nan)
    frame_index = {int(f): k for k, f in enumerate(frames)}
    for pid, frame, x_cm, y_cm in table:
        positions[int(pid) - 1, frame_index[int(frame)]] = (x_cm, y_cm)
    if np.isnan(positions).any():
        raise ValueError(f"{path.name} 缺少采样点，无法与实验逐帧对齐")
    return positions / 100.0


def draw_tracks(ax, positions: np.ndarray, palette, wheel, title: str) -> None:
    """画一屏轨迹：线色 = 出发方位角，起点空心、终点实心（与 plot_circle 同规范）。"""
    start_angle = np.degrees(np.arctan2(positions[:, 0, 1], positions[:, 0, 0])) % 360.0
    colors = [wheel[int(round(a / 360.0 * (AZIMUTH_STEPS - 1)))] for a in start_angle]

    limit = RING_RADIUS_M + 1.3
    ax.set_aspect("equal", adjustable="box")
    ax.set_xlim(-limit, limit)
    ax.set_ylim(-limit, limit)
    ax.set_facecolor(palette["surface"])

    ax.add_patch(plt.Circle((0, 0), RING_RADIUS_M, fill=False, linestyle=(0, (5, 4)),
                            linewidth=1.0, edgecolor=palette["ring"], zorder=1))
    ax.add_collection(LineCollection(
        [positions[i] for i in range(positions.shape[0])], colors=colors,
        linewidths=1.3, alpha=0.85, capstyle="round", zorder=3))
    ax.scatter(positions[:, -1, 0], positions[:, -1, 1], s=22, c=colors,
               edgecolors=palette["surface"], linewidths=1.0, zorder=5)
    ax.scatter(positions[:, 0, 0], positions[:, 0, 1], s=44, facecolors=palette["surface"],
               edgecolors=colors, linewidths=1.6, zorder=6)

    ax.grid(True, color=palette["grid"], linewidth=0.5)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(palette["axis"])
    ax.tick_params(colors=palette["muted"], labelsize=9, length=3)
    ax.set_title(title, color=palette["ink"], fontsize=14, fontweight="bold", pad=10)
    ax.set_xlabel("x (m)", color=palette["ink2"], fontsize=10)
    ax.set_ylabel("y (m)", color=palette["ink2"], fontsize=10)


def figure_trajectories(exp_pos, sim_positions: dict, sim_metrics: dict, path: Path, dpi: int) -> None:
    palette = MODES["light"]
    wheel = _wheel(palette)
    panels = [("实验", exp_pos)] + [(sim_metrics[name].label, sim_positions[name]) for name in sim_positions]

    fig, axes = plt.subplots(1, len(panels), figsize=(5.1 * len(panels), 5.6))
    fig.patch.set_facecolor(palette["surface"])
    for ax, (title, positions) in zip(np.atleast_1d(axes), panels):
        draw_tracks(ax, positions, palette, wheel, title)
    axes[0].legend(
        handles=[
            Line2D([], [], marker="o", linestyle="none", markersize=7, markerfacecolor="none",
                   markeredgecolor=palette["ink2"], markeredgewidth=1.5, label="起点"),
            Line2D([], [], marker="o", linestyle="none", markersize=5,
                   markerfacecolor=palette["ink2"], label="终点"),
        ],
        loc="upper left", frameon=False, labelcolor=palette["ink2"], fontsize=9,
    )
    fig.tight_layout()
    fig.savefig(path, dpi=dpi, facecolor=palette["surface"])
    plt.close(fig)
    print(f"  图 -> {path.name}")


def figure_distributions(exp_metrics, sim_metrics: dict, path: Path, dpi: int) -> None:
    """左：d_center 分档柱状（直穿 vs 绕行的直接对照）；右：速率 ECDF。"""
    palette = MODES["light"]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12.4, 5.0))
    fig.patch.set_facecolor(palette["surface"])

    bins = np.arange(0, 10, 1.0)
    series = [exp_metrics] + list(sim_metrics.values())
    width = 0.8 / len(series)
    for k, metrics in enumerate(series):
        counts, _ = np.histogram(np.clip(metrics.d_center, 0, 9.99), bins=bins)
        offset = (k - (len(series) - 1) / 2) * width
        ax1.bar(bins[:-1] + 0.5 + offset, counts, width=width * 0.92,
                color=SERIES_COLORS[metrics.label], label=metrics.label, zorder=3)
    ax1.axvline(CENTER_CROSSING_THRESHOLD, color=palette["muted"], linewidth=1.0,
                linestyle=(0, (4, 4)), zorder=2)
    ax1.set_xlabel("距圆心最近距离 d_center (m)", color=palette["ink2"], fontsize=11)
    ax1.set_ylabel("人数", color=palette["ink2"], fontsize=11)
    ax1.set_title("直穿圆心还是绕开（虚线以左 = 直穿）", color=palette["ink"], fontsize=13)

    for metrics in series:
        speed = np.sort(metrics.mean_speed)
        ax2.plot(speed, np.arange(1, speed.size + 1) / speed.size,
                 color=SERIES_COLORS[metrics.label], linewidth=2.0, label=metrics.label)
    ax2.set_xlabel("全程平均速度 (m/s)", color=palette["ink2"], fontsize=11)
    ax2.set_ylabel("累计比例", color=palette["ink2"], fontsize=11)
    ax2.set_title("速度分布", color=palette["ink"], fontsize=13)

    for ax in (ax1, ax2):
        ax.set_facecolor(palette["surface"])
        ax.grid(True, color=palette["grid"], linewidth=0.6, zorder=0)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(palette["axis"])
        ax.tick_params(colors=palette["muted"], labelsize=10)
        ax.legend(frameon=False, labelcolor=palette["ink2"], fontsize=10)

    fig.tight_layout()
    fig.savefig(path, dpi=dpi, facecolor=palette["surface"])
    plt.close(fig)
    print(f"  图 -> {path.name}")


def figure_individual(exp_metrics, sim_metrics: dict, path: Path, dpi: int) -> None:
    """逐人对照：路径长度与旅行时间，实验 vs 仿真。点贴着 y=x 说明个体层面也对上了。"""
    palette = MODES["light"]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.4, 5.2))
    fig.patch.set_facecolor(palette["surface"])

    for ax, key, label, unit in ((ax1, "path_length", "路径长度", "m"),
                                 (ax2, "travel_time", "旅行时间", "s")):
        reference = getattr(exp_metrics, key)
        for metrics in sim_metrics.values():
            values = getattr(metrics, key)
            finite = np.isfinite(reference) & np.isfinite(values)
            ax.scatter(reference[finite], values[finite], s=34, alpha=0.85,
                       color=SERIES_COLORS[metrics.label], edgecolors=palette["surface"],
                       linewidths=0.8, label=metrics.label, zorder=3)
        span = [0, float(np.nanmax(reference)) * 1.1]
        ax.plot(span, span, color=palette["muted"], linewidth=1.0,
                linestyle=(0, (4, 4)), zorder=2)
        ax.set_xlabel(f"实验 {label} ({unit})", color=palette["ink2"], fontsize=11)
        ax.set_ylabel(f"仿真 {label} ({unit})", color=palette["ink2"], fontsize=11)
        ax.set_title(f"逐人{label}（虚线为 y = x）", color=palette["ink"], fontsize=13)

    for ax in (ax1, ax2):
        ax.set_facecolor(palette["surface"])
        ax.grid(True, color=palette["grid"], linewidth=0.6, zorder=0)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(palette["axis"])
        ax.tick_params(colors=palette["muted"], labelsize=10)
        ax.legend(frameon=False, labelcolor=palette["ink2"], fontsize=10)

    fig.tight_layout()
    fig.savefig(path, dpi=dpi, facecolor=palette["surface"])
    plt.close(fig)
    print(f"  图 -> {path.name}")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="实验 / 主模型 / baseline 对比出图")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--figures", type=Path, default=FIG_DIR)
    parser.add_argument("--dpi", type=int, default=200)
    args = parser.parse_args()

    matplotlib.rcParams.update({
        "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
        "font.family": "sans-serif",
        "axes.unicode_minus": False,
    })

    exp = load_experiment()
    exp_metrics = evaluate(exp.positions, exp, label="实验")

    sim_positions, sim_metrics = {}, {}
    for name in ("main", "baseline1"):
        csv = args.out / f"trajectories_{name}.csv"
        if not csv.exists():
            print(f"跳过 {name}：{csv.name} 不存在（先跑 run.py）")
            continue
        positions = load_sim(csv, exp.frames, exp.n_ped)
        sim_positions[name] = positions
        sim_metrics[name] = evaluate(positions, exp, label=MODEL_LABELS[name])

    if not sim_metrics:
        print("没有任何仿真输出可画。先运行：python week02/detour_gcfv/run.py")
        return

    args.figures.mkdir(parents=True, exist_ok=True)
    figure_trajectories(exp.positions, sim_positions, sim_metrics,
                        args.figures / "trajectories_compare.png", args.dpi)
    figure_distributions(exp_metrics, sim_metrics,
                         args.figures / "distributions.png", args.dpi)
    figure_individual(exp_metrics, sim_metrics,
                      args.figures / "individual_compare.png", args.dpi)


if __name__ == "__main__":
    main()
