"""绘制 circle-10m-64-1.txt 的轨迹图 —— 10 m 圆环上的「正对径穿越」实验。

与 week01 的区别，以及为什么不能照抄那个脚本：

1. **这是单个同步场景，不是五个场景的合订**。64 个人在同一时刻出发、同一个场地，
   坐标轴唯一，所以只出一张图，不需要 week01 的逐场景循环。
2. **画法从「时间渐变」换成「按行人着色 + 标起终点」**。week01 那条蓝色渐变线适合
   看人流走向，但这里每个人的轨迹都从圆环出发、绕到正对径点，64 条线在圆心附近
   交叉成一团 —— 时间渐变的深色端全都挤在圆环上，反而看不出「谁从哪走到哪」。
   按行人着色之后，同一个人首尾同色，配合起点空心点 / 终点实心点，单条轨迹就能跟住。

关于文件的几个坑（2026-09-18 实测确认）：

1. **列序是 `行人ID 帧号 x y RUN_ID`，不是 week01 那种 8 列 obsmat。**
   第一列恒为 1..64 共 64 个值、每个值出现 425 次；第二列才是帧号（37..461，连续无断档）。
   这和 Social-GAN 系列的 `frame id x y` 4 列格式**列序相反**，直接套过来会把帧号和
   行人号画反 —— 反着读每步中位位移 6.6 m（约 165 m/s），正着读 5.4 cm（约 1.35 m/s）。
   哪个是对的，看速度就知道。
2. **坐标单位是厘米，不是米**。圆环半径约 1000 = 10 m；出发半径实测 972~1052，
   正对径两侧都落在这个范围内。本脚本统一除以 100 换算成米再画。
3. **采样率 25 fps**（数据集文档标注）。425 帧 = 17.0 s，中位速度 1.35 m/s，
   与正常人步速相符 —— 这两个数也反过来印证了列序和单位没读错。
4. **第 5 列每个行人恒定**（取值 160/170/180，按行人号分成 1-14 / 15-39 / 40-60 / 61-64
   四段）。上游文档称其为 RUN_ID，但 170 重复出现两次、且这一列在画轨迹上没有任何用处，
   本脚本不读它。

配色说明：64 个行人远超「8 个分类色」的可用上限，硬凑 64 个互不相近的色相没有意义
（没人能分辨 64 种颜色）。这里换成一个**连续的色相环**：色相 = 该行人的出发方位角。
于是圆环上的起点按方位角排开就是一道连续的彩虹，颜色本身携带「从哪个方位出发」的信息；
真正的身份识别交给**写在起点外侧的行人编号**，不依赖颜色。色相环在 OKLCH 空间里
固定亮度、固定彩度生成，保证每个色都在该模式的亮度带内、且对比度够。

用法：
    python week02/model/plot_circle.py [--dpi 200] [--mode light|dark|all] [--no-labels]

`--mode` 默认 **light**，只出一张亮色图。深色版是可选件，要看得显式 `--mode dark`，
`--mode all` 才两套都出 —— week01 默认出明暗两套是按那边的习惯来的，这里不沿用。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # 无窗口后端，直接出文件

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.cm import ScalarMappable
from matplotlib.collections import LineCollection
from matplotlib.colors import LinearSegmentedColormap, Normalize
from matplotlib.lines import Line2D

WEEK02_DIR = Path(__file__).resolve().parent.parent   # model/ 往上一级
REPO_ROOT = WEEK02_DIR.parent
DATA_PATH = REPO_ROOT / "datasets" / "circle-10m-64-1.txt"

# 坐标单位是厘米（圆环半径 ~1000），画图前换算成米。
CM_PER_M = 100.0
# 数据集文档标注的采样率。帧差换算成秒要用它，不能凭 week01 的 0.4 s/采样点想当然 ——
# 那是 ETH/UCY 的 2.5 fps，与此处无关。
FPS = 25.0

# 参考圆半径（米）。实验的圆环就是 10 m，实测出发半径 9.72~10.52 m，取名义值画参考圆。
RING_RADIUS_M = 10.0

# 绘图区边长（英寸）。数据是个圆，正方形绘图区才不留白。
PLOT_SIDE = 9.2
MARGIN = {"left": 1.15, "right": 0.55, "bottom": 2.10, "top": 1.45}

COLORBAR_HEIGHT = 0.20
COLORBAR_DROP = 1.32

# 起点编号写在圆环外侧多远（米）。64 个起点按方位角均匀排布，相邻间隔约 1.06 m，
# 编号两位数在字号 7.5 下宽约 0.4 m，放得下不会撞。
LABEL_OFFSET_M = 0.55

# 两套配色。图表铬色沿用 week01（同一份参考调色板），只有色相环是新的：
# 在 OKLCH 里固定亮度 L、彩度 C 转一圈生成，所以每个色都在该模式的亮度带里。
# 亮度带按「浅色模式 L 0.43~0.77 / 深色模式 0.48~0.67」取中上段，
# 既保证对底面对比度，又给 64 条线留出足够色相区分度。
MODES = {
    "light": {
        "surface": "#fcfcfb",
        "ink": "#0b0b0b",
        "ink2": "#52514e",
        "muted": "#898781",
        "grid": "#e1e0d9",
        "axis": "#c3c2b7",
        "ring": "#c3c2b7",
        "alpha": 0.85,
        "wheel_L": 0.62,
        "wheel_C": 0.14,
    },
    "dark": {
        "surface": "#1a1a19",
        "ink": "#ffffff",
        "ink2": "#c3c2b7",
        "muted": "#898781",
        "grid": "#2c2c2a",
        "axis": "#383835",
        "ring": "#4a4a46",
        "alpha": 0.90,
        "wheel_L": 0.65,
        "wheel_C": 0.13,
    },
}


def read_tracks(path: Path):
    """读 5 列轨迹，返回 {行人 id: (帧数组, x 米数组, y 米数组)}，组内按帧号排序。

    列序是 `行人ID 帧号 x y RUN_ID`（见模块文档坑 1），第一列才是行人号。
    第 5 列（RUN_ID）不读。
    """
    ids, frames, xs, ys = [], [], [], []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            fields = line.split()
            if len(fields) < 4:  # 空行 / 被截断的行
                continue
            ids.append(int(float(fields[0])))
            frames.append(int(float(fields[1])))
            xs.append(float(fields[2]))
            ys.append(float(fields[3]))

    ids = np.asarray(ids)
    frames = np.asarray(frames)
    xs = np.asarray(xs, dtype=float) / CM_PER_M
    ys = np.asarray(ys, dtype=float) / CM_PER_M

    tracks = {}
    for pid in np.unique(ids):
        mask = ids == pid
        order = np.argsort(frames[mask])
        tracks[int(pid)] = (frames[mask][order], xs[mask][order], ys[mask][order])
    return tracks


def _oklab_to_linear_srgb(lightness: float, a: float, b: float):
    """OKLab -> 线性 sRGB。转换系数取自 Björn Ottosson 的原始定义。"""
    l_ = lightness + 0.3963377774 * a + 0.2158037573 * b
    m_ = lightness - 0.1055613458 * a - 0.0638541728 * b
    s_ = lightness - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_**3, m_**3, s_**3
    return (
        4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
    )


def _encode(channel: float) -> float:
    """线性 sRGB -> 伽马编码分量。"""
    return 1.055 * channel ** (1 / 2.4) - 0.055 if channel > 0.0031308 else 12.92 * channel


def hue_color(lightness: float, chroma: float, hue_deg: float) -> str:
    """给一个 OKLCH 色相角，返回 sRGB 十六进制色。

    高彩度的黄、青等色相会超出 sRGB 色域，直接截断会偏色。这里二分把彩度压到
    刚好入界 —— 保住亮度（亮度才是对比度的决定因素），只牺牲一点鲜艳度。
    """
    lo, hi = 0.0, chroma
    for _ in range(30):
        mid = 0.5 * (lo + hi)
        rgb = _oklab_to_linear_srgb(lightness, mid * np.cos(np.radians(hue_deg)), mid * np.sin(np.radians(hue_deg)))
        if all(-1e-4 <= c <= 1 + 1e-4 for c in rgb):
            lo = mid
        else:
            hi = mid
    rgb = _oklab_to_linear_srgb(lightness, lo * np.cos(np.radians(hue_deg)), lo * np.sin(np.radians(hue_deg)))
    return "#" + "".join(f"{int(round(min(max(_encode(c), 0.0), 1.0) * 255)):02x}" for c in rgb)


def azimuth_wheel(palette: dict, steps: int = 361):
    """生成 0~360° 的色相环：返回 (角度数组, 颜色列表)。

    色相角直接等于方位角，所以这个环同时是「颜色 -> 出发方位角」的图例。
    """
    angles = np.linspace(0.0, 360.0, steps)
    colors = [hue_color(palette["wheel_L"], palette["wheel_C"], a) for a in angles]
    return angles, colors


def build_segments(tracks: dict):
    """把轨迹整理成 LineCollection 要的折线列表，返回 (折线列表, 每条折线对应的行人 id)。

    每个行人一条折线，用 LineCollection 一次画完，比拼 64 次 plot 快得多。
    帧号断档处把轨迹切开，免得连出一条数据里并不存在的「瞬移」直线。
    """
    segments, owners = [], []
    for pid, (frames, xs, ys) in tracks.items():
        points = np.column_stack([xs, ys])
        cuts = np.flatnonzero(np.diff(frames) > 1.5) + 1  # 帧步长恒为 1，>1.5 即断档
        for run in np.split(points, cuts):
            if len(run) >= 2:
                segments.append(run)
                owners.append(pid)
    return segments, owners


def render(mode: str, out_path: Path, dpi: int, labels: bool) -> None:
    palette = MODES[mode]
    angles, wheel = azimuth_wheel(palette)
    cmap = LinearSegmentedColormap.from_list("azimuth_" + mode, wheel)

    tracks = read_tracks(DATA_PATH)

    # 每个行人的颜色 = 出发方位角，转成 0~1 交给色环。方位角在实验里就是均匀排布的，
    # 所以圆环上的起点会排成一道连续彩虹。
    start_angle = {}
    for pid, (frames, xs, ys) in tracks.items():
        start_angle[pid] = float(np.degrees(np.arctan2(ys[0], xs[0])) % 360.0)
    color_of = {}
    for pid, ang in start_angle.items():
        color_of[pid] = wheel[int(round(ang / 360.0 * (len(wheel) - 1)))]

    all_frames = np.concatenate([f for f, _, _ in tracks.values()])
    first, last = int(all_frames.min()), int(all_frames.max())
    duration = (last - first) / FPS

    # 所有点到圆心的最大距离，定画布范围。外侧再留出写编号的位置。
    r_max = max(float(np.hypot(xs, ys).max()) for _, xs, ys in tracks.values())
    half = r_max + LABEL_OFFSET_M + 0.35

    fig_w = PLOT_SIDE + MARGIN["left"] + MARGIN["right"]
    fig_h = PLOT_SIDE + MARGIN["bottom"] + MARGIN["top"]
    fig = plt.figure(figsize=(fig_w, fig_h))
    fig.patch.set_facecolor(palette["surface"])

    ax = fig.add_axes(
        [
            MARGIN["left"] / fig_w,
            MARGIN["bottom"] / fig_h,
            PLOT_SIDE / fig_w,
            PLOT_SIDE / fig_h,
        ]
    )
    ax.set_facecolor(palette["surface"])
    ax.set_aspect("equal", adjustable="box")  # 等比例尺，圆必须画成圆
    ax.set_xlim(-half, half)
    ax.set_ylim(-half, half)

    # 参考圆：实验场地就是这条 10 m 的环，画出来才知道轨迹贴不贴边
    ring = plt.Circle(
        (0.0, 0.0), RING_RADIUS_M, fill=False, linestyle=(0, (5, 4)),
        linewidth=1.0, edgecolor=palette["ring"], zorder=1,
    )
    ax.add_patch(ring)

    segments, owners = build_segments(tracks)
    ax.add_collection(
        LineCollection(
            segments,
            colors=[color_of[pid] for pid in owners],
            linewidths=1.5,
            alpha=palette["alpha"],
            capstyle="round",
            zorder=3,
        )
    )

    # 起点（空心）与终点（实心）。空心点的填充色用底色，等于给每个起点套了一圈
    # 底色描边 —— 起点密密麻麻排在环上时，这一圈是让它们互相不粘在一起的关键。
    sx = [tracks[p][1][0] for p in tracks]
    sy = [tracks[p][2][0] for p in tracks]
    ex = [tracks[p][1][-1] for p in tracks]
    ey = [tracks[p][2][-1] for p in tracks]
    ax.scatter(ex, ey, s=26, c=[color_of[p] for p in tracks], edgecolors=palette["surface"],
               linewidths=1.2, zorder=5)
    ax.scatter(sx, sy, s=52, facecolors=palette["surface"], edgecolors=[color_of[p] for p in tracks],
               linewidths=1.8, zorder=6)

    if labels:
        for pid in tracks:
            x0, y0 = tracks[pid][1][0], tracks[pid][2][0]
            cos_a, sin_a = np.cos(np.radians(start_angle[pid])), np.sin(np.radians(start_angle[pid]))
            ax.text(
                x0 + cos_a * LABEL_OFFSET_M,
                y0 + sin_a * LABEL_OFFSET_M,
                str(pid),
                color=palette["muted"],
                fontsize=7.5,
                ha="left" if cos_a > 0.15 else ("right" if cos_a < -0.15 else "center"),
                va="bottom" if sin_a > 0.15 else ("top" if sin_a < -0.15 else "center"),
                zorder=7,
            )

    # 坐标轴只留左、下两条，网格压在最底层
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

    ax.set_title("circle-10m-64-1", color=palette["ink"], fontsize=22, fontweight="bold", loc="left", pad=30)
    # 副标题用「偏移点」定位，不用 axes 分数坐标，免得跟着绘图区尺寸漂
    ax.annotate(
        f"{len(tracks)} 人 · {last - first + 1} 帧 · {FPS:.0f} fps · 约 {duration:.1f} s · "
        f"{RING_RADIUS_M:.0f} m 圆环正对径穿越",
        xy=(0.0, 1.0),
        xycoords="axes fraction",
        xytext=(0, 8),
        textcoords="offset points",
        ha="left",
        va="bottom",
        color=palette["ink2"],
        fontsize=12,
    )

    # 两个图例项：起点空心 / 终点实心。用无名灰点做示意，不占某个行人的颜色。
    ax.legend(
        handles=[
            Line2D([], [], marker="o", linestyle="none", markersize=8, markerfacecolor="none",
                   markeredgecolor=palette["ink2"], markeredgewidth=1.6, label="起点（号码标在环外）"),
            Line2D([], [], marker="o", linestyle="none", markersize=6,
                   markerfacecolor=palette["ink2"], markeredgecolor="none", label="终点（正对径点）"),
        ],
        loc="upper left",
        frameon=False,
        labelcolor=palette["ink2"],
        fontsize=11,
        handletextpad=0.8,
        borderaxespad=0.2,
    )

    # 色相环图例。64 条线没法逐条列图例，用一条连续色条交代「颜色 = 出发方位角」，
    # 剩下的身份识别交给环上的编号。
    cax = fig.add_axes(
        [
            MARGIN["left"] / fig_w,
            (MARGIN["bottom"] - COLORBAR_DROP) / fig_h,
            PLOT_SIDE / fig_w,
            COLORBAR_HEIGHT / fig_h,
        ]
    )
    cbar = fig.colorbar(ScalarMappable(norm=Normalize(0, 360), cmap=cmap), cax=cax, orientation="horizontal")
    cbar.set_ticks([0, 90, 180, 270, 360])
    cbar.set_ticklabels(["0°", "90°", "180°", "270°", "360°"])
    cbar.set_label("线色 = 出发方位角（0° = +x 方向，逆时针增）", color=palette["ink2"], fontsize=11, labelpad=8)
    cbar.ax.tick_params(colors=palette["muted"], labelsize=10, length=3, width=0.8)
    cbar.outline.set_visible(False)

    fig.savefig(out_path, dpi=dpi, facecolor=palette["surface"])
    plt.close(fig)
    print(f"  [{mode}] {len(tracks)} 人  {last - first + 1} 帧  {duration:.1f} s  -> {out_path.name}")


def main() -> None:
    # 输出里有中文。Windows 下 Python 默认按本地代码页（简中为 cp936）写管道，
    # 而终端通常按 UTF-8 解读，会显示成乱码，所以这里显式改成 UTF-8。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="绘制 circle-10m-64-1 的轨迹图")
    parser.add_argument("--dpi", type=int, default=200, help="输出分辨率，默认 200")
    parser.add_argument(
        "--mode",
        choices=("light", "dark", "all"),
        default="light",
        help="配色模式，默认 light（只出亮色一版；dark 需显式指定）",
    )
    parser.add_argument("--no-labels", action="store_true", help="不写行人编号（64 个编号太挤时可以关掉）")
    args = parser.parse_args()

    matplotlib.rcParams.update(
        {
            "font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
            "font.family": "sans-serif",
            "axes.unicode_minus": False,
        }
    )

    out_dir = WEEK02_DIR / "results" / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)

    modes = ("light", "dark") if args.mode == "all" else (args.mode,)
    for mode in modes:
        render(mode, out_dir / f"circle_{mode}.png", args.dpi, labels=not args.no_labels)


if __name__ == "__main__":
    main()
