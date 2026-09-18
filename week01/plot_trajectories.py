"""绘制 ETH / UCY 五个场景的行人轨迹图，每个场景单独出一张。

覆盖的标准评测集五场景：zara01、zara02、students03、seq_hotel、seq_eth。

图的形态选的是「空间轨迹图」：每位行人画成一条细线，线段颜色按**场景内归一化时间**
取单一蓝色顺序色阶 —— 浅色代表刚出场，深色代表快离场，配合色条就能读出人流方向。

两个刻意的取舍：

1. **逐场景独立成图，不叠小倍数**。五个场景各在自己的世界坐标系里，
   坐标轴没有可比性（zara01 的 y 与 zara02 的 y 首尾相接但并不相邻，students03 是另一片区域）；
   而且小倍数每格太小，几百条轨迹挤在一起只剩一团。独立成图后每张都能给足尺寸。
2. **线条画得很淡（0.7 px，alpha 0.45）**。这是这张图好看与否的关键：
   密集走廊里几千条线段重叠，线一粗一实就糊成一块实心色块，什么结构都看不见；
   调淡之后重叠会逐层累积，密度自己长成浓淡，也就是「越多人走过的地方越深」。

这个脚本只画图，不改任何数据文件。原始 txt 才是表格视图，本图不引入任何 txt 里没有的信息。

用法：
    python week01/plot_trajectories.py [--dpi 200] [--mode light|dark|all]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # 无窗口后端，直接出文件

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.colors import LinearSegmentedColormap, Normalize

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = REPO_ROOT / "datasets"       # ETH / UCY 原始数据都在这里

# 在范围内的五个场景，顺序按用户指定。五个都自带 obsmat.txt，
# 所以读取路径统一，不需要分格式。
#
# 注意 students03 另有一份 students003.txt（Social-GAN 的 4 列格式），
# 它和 obsmat.txt **不是同一套世界坐标**（实测两组点无一重合，范围也不同），
# 这里是两份独立标注，不是换个原点。本脚本统一用 obsmat.txt。
SCENES = [
    ("zara01", DATA_ROOT / "UCY" / "zara01" / "obsmat.txt"),
    ("zara02", DATA_ROOT / "UCY" / "zara02" / "obsmat.txt"),
    ("students03", DATA_ROOT / "UCY" / "students03" / "obsmat.txt"),
    ("seq_hotel", DATA_ROOT / "ETH" / "seq_hotel" / "obsmat.txt"),
    ("seq_eth", DATA_ROOT / "ETH" / "seq_eth" / "obsmat.txt"),
]

# 采样间隔。两个 info.txt 都写明标注为 2.5 fps，即每 0.4 s 一个采样点。
# 注意各场景的**帧号步长**并不一致（seq_eth 是 6，其余是 10），
# 所以帧差要先除以步长再乘 0.4 s，不能直接拿帧差当时间。
SAMPLE_SECONDS = 0.4

# 绘图区最长边的英寸数。每张图按各自数据的长宽比反推另一边，
# 这样五个场景的图和各自场景形状一致，也不会出现大片留白。
PLOT_LONG_SIDE = 10.0
# 四周留白（英寸）。下边留得最宽，因为色条放在图下方：
# x 刻度 -> x 轴标题 -> 色条 -> 色条刻度 -> 色条标题，一路排下来。
MARGIN = {"left": 1.15, "right": 0.55, "bottom": 2.10, "top": 1.45}

# 色条高度（英寸）与它相对绘图区底边的位置（英寸）。
# 色条横放是刻意的：竖放的色条标题要旋转 90°，中文竖排非常难读。
COLORBAR_HEIGHT = 0.20
COLORBAR_DROP = 1.32

# 两套配色都来自数据可视化参考调色板：单一蓝色顺序色阶（浅 -> 深），外加图表铬色。
# 两端的对比度都过了 2:1 的「贴面端」门槛，也就是最贴近背景的那一端仍然看得见。
# 深色模式是单独选出来的一套步进，不是把浅色模式自动反色。
MODES = {
    "light": {
        "surface": "#fcfcfb",
        "ink": "#0b0b0b",
        "ink2": "#52514e",
        "muted": "#898781",
        "grid": "#e1e0d9",
        "axis": "#c3c2b7",
        "alpha": 0.45,
        # 300 -> 700 步：浅端 #6da7ec 对底 2.44:1
        "ramp": ["#6da7ec", "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"],
    },
    "dark": {
        "surface": "#1a1a19",
        "ink": "#ffffff",
        "ink2": "#c3c2b7",
        "muted": "#898781",
        "grid": "#2c2c2a",
        "axis": "#383835",
        "alpha": 0.55,
        "ramp": ["#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#256abf"],
    },
}


def read_tracks(path: Path):
    """读 obsmat 世界坐标轨迹，返回 {行人 id: (帧数组, x 数组, y 数组)}。

    行内 8 列：帧 id x z y vx vz vy，单位米。
    极易踩的坑：**y 在第 5 列（下标 4）** —— 第 4 列是恒为 0 的 z，
    把它当 y 读出来的是一整列 0。

    速度列（下标 5、7）本脚本不读，这里只画位置。它们确实是位置列的有限差分，
    但各场景约定不同（zara01/02 后向、students03 前向、两个 ETH 场景中心），
    要用得先确认场景，别一种约定套五个场景。

    仓库里另有 4 列的格式（UCY 的 crowds_*.txt、students03/students003.txt，
    列序是 帧 id x y，y 在下标 3）。本脚本范围内用不到 —— 五个场景都自带 obsmat.txt。
    """
    y_col = 4

    ids, frames, xs, ys = [], [], [], []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            fields = line.split()
            if len(fields) <= y_col:  # 空行 / 被截断的行
                continue
            ids.append(int(float(fields[1])))
            frames.append(int(float(fields[0])))
            xs.append(float(fields[2]))
            ys.append(float(fields[y_col]))

    ids = np.asarray(ids)
    frames = np.asarray(frames)
    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)

    tracks = {}
    for pid in np.unique(ids):
        mask = ids == pid
        order = np.argsort(frames[mask])  # 同一人按帧号排好序
        tracks[int(pid)] = (frames[mask][order], xs[mask][order], ys[mask][order])
    return tracks


def frame_step(frames: np.ndarray) -> int:
    """估计场景的帧号步长：所有正帧差里出现次数最多的那个值。

    步长不写死常量 —— seq_eth 是 6，其余是 10。
    """
    diffs = np.diff(np.unique(frames))
    diffs = diffs[diffs > 0]
    values, counts = np.unique(diffs, return_counts=True)
    return int(values[counts.argmax()])


def build_segments(tracks: dict, step: int, first: int, last: int):
    """把轨迹切成线段，返回 (线段数组, 每段的归一化时间)。

    线段按相邻两采样点成对构造，一次画完整场，比拼几千次 plot 快得多。
    帧号断档处不连线，免得画出一条数据里并不存在的「瞬移」轨迹。
    """
    gap_limit = 1.5 * step
    segments, times = [], []
    span = max(last - first, 1)

    for frames, xs, ys in tracks.values():
        if frames.size < 2:
            continue
        points = np.column_stack([xs, ys])
        keep = np.diff(frames) <= gap_limit
        if not keep.any():
            continue

        starts = points[:-1][keep]
        ends = points[1:][keep]
        segments.append(np.stack([starts, ends], axis=1))

        midpoints = 0.5 * (frames[:-1] + frames[1:])[keep]
        times.append((midpoints - first) / span)

    return np.concatenate(segments), np.concatenate(times)


def render_scene(name: str, path: Path, mode: str, out_path: Path, dpi: int) -> None:
    palette = MODES[mode]
    cmap = LinearSegmentedColormap.from_list("time_" + mode, palette["ramp"])

    tracks = read_tracks(path)
    all_frames = np.concatenate([f for f, _, _ in tracks.values()])
    first, last = int(all_frames.min()), int(all_frames.max())
    step = frame_step(all_frames)
    samples = (last - first) // step + 1

    xs = np.concatenate([x for _, x, _ in tracks.values()])
    ys = np.concatenate([y for _, _, y in tracks.values()])
    # 四周各留 2% 余量，免得轨迹贴着边框
    pad_x = 0.02 * (xs.max() - xs.min())
    pad_y = 0.02 * (ys.max() - ys.min())
    x_lo, x_hi = xs.min() - pad_x, xs.max() + pad_x
    y_lo, y_hi = ys.min() - pad_y, ys.max() + pad_y

    # 按数据长宽比反推绘图区尺寸，再套上四周留白定出整图尺寸 ——
    # 这样绘图区刚好装得下等比尺度的数据，不会有 letterbox 的空白。
    x_span, y_span = x_hi - x_lo, y_hi - y_lo
    if x_span >= y_span:
        plot_w, plot_h = PLOT_LONG_SIDE, PLOT_LONG_SIDE * y_span / x_span
    else:
        plot_w, plot_h = PLOT_LONG_SIDE * x_span / y_span, PLOT_LONG_SIDE

    fig_w = plot_w + MARGIN["left"] + MARGIN["right"]
    fig_h = plot_h + MARGIN["bottom"] + MARGIN["top"]
    fig = plt.figure(figsize=(fig_w, fig_h))
    fig.patch.set_facecolor(palette["surface"])

    ax = fig.add_axes(
        [
            MARGIN["left"] / fig_w,
            MARGIN["bottom"] / fig_h,
            plot_w / fig_w,
            plot_h / fig_h,
        ]
    )
    ax.set_facecolor(palette["surface"])
    ax.set_aspect("equal", adjustable="box")  # 等比例尺，形状不许变形
    ax.set_xlim(x_lo, x_hi)
    ax.set_ylim(y_lo, y_hi)

    segments, times = build_segments(tracks, step, first, last)
    ax.add_collection(
        LineCollection(
            segments,
            array=times,
            cmap=cmap,
            norm=Normalize(0.0, 1.0),
            linewidths=0.7,
            alpha=palette["alpha"],
            capstyle="round",
            zorder=2,
        )
    )

    ax.grid(True, color=palette["grid"], linewidth=0.6, linestyle="-")
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(palette["axis"])
        ax.spines[side].set_linewidth(0.8)
    ax.tick_params(colors=palette["muted"], labelsize=11, length=4, width=0.8)
    ax.set_xlabel("x (m)", color=palette["ink2"], fontsize=12, labelpad=8)
    ax.set_ylabel("y (m)", color=palette["ink2"], fontsize=12, labelpad=8)

    ax.set_title(name, color=palette["ink"], fontsize=22, fontweight="bold", loc="left", pad=30)
    # 副标题用「偏移点」定位，不用 axes 分数坐标 —— 各场景绘图区尺寸不同，
    # 分数坐标会让副标题的相对高度跟着漂，压到标题上去。
    ax.annotate(
        f"{len(tracks)} 人 · {samples} 个采样点 · 帧步长 {step} · 约 {samples * SAMPLE_SECONDS:.0f} s",
        xy=(0.0, 1.0),
        xycoords="axes fraction",
        xytext=(0, 8),
        textcoords="offset points",
        ha="left",
        va="bottom",
        color=palette["ink2"],
        fontsize=12,
    )

    # 顺序色阶必须配色条 —— 连续色不能只靠颜色本身表意
    scalar = plt.cm.ScalarMappable(norm=Normalize(0.0, 1.0), cmap=cmap)
    scalar.set_array([])
    cax = fig.add_axes(
        [
            MARGIN["left"] / fig_w,
            (MARGIN["bottom"] - COLORBAR_DROP) / fig_h,
            plot_w / fig_w,
            COLORBAR_HEIGHT / fig_h,
        ]
    )
    cbar = fig.colorbar(scalar, cax=cax, orientation="horizontal")
    cbar.set_label("场景内归一化时间（0 = 该场景首帧，1 = 末帧）", color=palette["ink2"], fontsize=11, labelpad=8)
    cbar.ax.tick_params(colors=palette["muted"], labelsize=10, length=3, width=0.8)
    cbar.outline.set_visible(False)

    fig.savefig(out_path, dpi=dpi, facecolor=palette["surface"])
    plt.close(fig)
    print(f"  {name:<10} {len(tracks):>4} 人  {samples:>5} 采样点  步长 {step:<3} 图 {fig_w:.1f}×{fig_h:.1f} in  -> {out_path.name}")


def main() -> None:
    # 输出里有中文。Windows 下 Python 默认按本地代码页（简中为 cp936）写管道，
    # 而终端通常按 UTF-8 解读，会显示成乱码，所以这里显式改成 UTF-8。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="绘制 ETH / UCY 各场景的轨迹图")
    parser.add_argument("--dpi", type=int, default=200, help="输出分辨率，默认 200")
    parser.add_argument("--mode", choices=("light", "dark", "all"), default="all", help="配色模式")
    args = parser.parse_args()

    matplotlib.rcParams.update(
        {
            "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
            "font.family": "sans-serif",
            "axes.unicode_minus": False,
        }
    )

    out_dir = Path(__file__).resolve().parent / "results" / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)

    modes = ("light", "dark") if args.mode == "all" else (args.mode,)
    for mode in modes:
        print(f"[{mode}]")
        for name, path in SCENES:
            render_scene(name, path, mode, out_dir / f"{name}_{mode}.png", args.dpi)


if __name__ == "__main__":
    main()
