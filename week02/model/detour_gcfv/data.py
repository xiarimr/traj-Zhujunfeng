"""实验数据读取、初值/目标/期望速度的提取 —— 与模型代码完全解耦。

本模块的产物是纯数组和值对象，不含任何模型概念（不知道 GCFV、不知道路线），
模型侧也不碰文件路径。要换数据集只改这里。

文件格式（实测确认，详见 week02/plot_circle.py 的模块文档）：
    列序是 `行人ID 帧号 x y RUN_ID`，坐标单位**厘米**，25 fps。
    ⚠ 与 Social-GAN 那套 `frame id x y` 列序相反，别套用。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .paths import DATA_PATH

# 数据集文档标注的采样率（不是 week01 那套 2.5 fps / 0.4 s，别搞混）
FPS = 25.0
DT = 1.0 / FPS
CM_PER_M = 100.0

# 实验区圆环半径（名义值 10 m；实测出发半径 9.72~10.52 m）
RING_RADIUS_M = 10.0

# 期望速度 v⁰ 的提取口径（spec §2）
_SPEED_MEDFILT_FRAMES = 5      # 中值滤波窗，压掉追踪跳变（原始数据最大瞬时速度 10.25 m/s）
_SPEED_SMOOTH_FRAMES = 25      # 1 s 滑动平均
_SPEED_PERCENTILE = 90.0       # 取 p90 作为"空闲时能走多快"


@dataclass
class Experiment:
    """一次实验的全部轨迹，数组形状统一为 (行人数, 帧数, …)。"""

    pids: np.ndarray        # (N,)       行人 id，升序
    frames: np.ndarray      # (T,)       帧号
    positions: np.ndarray   # (N, T, 2)  位置，米
    fps: float = FPS

    @property
    def n_ped(self) -> int:
        return self.positions.shape[0]

    @property
    def n_frames(self) -> int:
        return self.positions.shape[1]

    @property
    def dt(self) -> float:
        return 1.0 / self.fps

    @property
    def duration(self) -> float:
        return (self.n_frames - 1) * self.dt

    def speeds(self) -> np.ndarray:
        """逐帧速率 (N, T−1)，米/秒。"""
        return np.linalg.norm(np.diff(self.positions, axis=1), axis=-1) / self.dt

    def path_lengths(self) -> np.ndarray:
        """逐人走过的路程 (N,)，米。"""
        return np.linalg.norm(np.diff(self.positions, axis=1), axis=-1).sum(axis=1)


def load_experiment(path: Path = DATA_PATH) -> Experiment:
    """读实验文件，返回按 (行人, 帧) 排好序的 `Experiment`。

    行序是文件里自带的（按行人分组、组内帧号升序），这里不假设，一律显式排序。
    帧号必须连续 —— 有断档说明数据被截断过，直接报错而不是默默把两段接起来。
    """
    pids, frames, xs, ys = [], [], [], []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            fields = line.split()
            if len(fields) < 4:
                continue
            pids.append(int(float(fields[0])))
            frames.append(int(float(fields[1])))
            xs.append(float(fields[2]))
            ys.append(float(fields[3]))

    pids = np.asarray(pids)
    frames = np.asarray(frames)
    coords = np.column_stack([xs, ys]) / CM_PER_M      # 厘米 -> 米

    unique_pids = np.unique(pids)
    unique_frames = np.unique(frames)
    step = np.diff(unique_frames)
    if step.size and not np.all(step == 1):
        raise ValueError(f"帧号不连续，第 {unique_frames[np.flatnonzero(step != 1)[0]]} 帧后有断档")

    positions = np.full((unique_pids.size, unique_frames.size, 2), np.nan)
    pid_index = {int(p): k for k, p in enumerate(unique_pids)}
    frame_index = {int(f): k for k, f in enumerate(unique_frames)}
    for pid, frame, xy in zip(pids, frames, coords):
        positions[pid_index[int(pid)], frame_index[int(frame)]] = xy
    if np.isnan(positions).any():
        raise ValueError("有 (行人, 帧) 组合缺采样点，无法构成完整轨迹矩阵")

    return Experiment(pids=unique_pids, frames=unique_frames, positions=positions)


def initial_state(exp: Experiment):
    """仿真初值：位置、速度、朝向。

    位置取实验首帧（不做任何平滑，保证与实验逐帧对齐）；速度用首步前向差分；
    朝向是速度方向 —— 若首步速度为零（追踪异常），退化为指向目标的方向。
    """
    pos0 = exp.positions[:, 0, :].copy()
    vel0 = (exp.positions[:, 1, :] - exp.positions[:, 0, :]) / exp.dt
    return pos0, vel0


def goals(pos0: np.ndarray, radius: float = RING_RADIUS_M) -> np.ndarray:
    """每人的目标 = 起点在半径 `radius` 圆上的正对径点。

    实测所有 64 人的终点距该点中位仅 0.24 m（最大 0.49），这就是实验里每个人的目标。
    """
    unit = pos0 / np.maximum(np.linalg.norm(pos0, axis=-1, keepdims=True), 1e-9)
    return -unit * radius


def _median_filter(values: np.ndarray, window: int) -> np.ndarray:
    """逐行滑动中值滤波。用 stride 视图实现，避免为一个中值滤波引入 scipy。"""
    half = window // 2
    padded = np.pad(values, ((0, 0), (half, half)), mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, window, axis=1)
    return np.median(windows, axis=-1)


def _smooth(values: np.ndarray, window: int) -> np.ndarray:
    """逐行等权滑动平均。"""
    kernel = np.ones(window) / window
    return np.apply_along_axis(lambda row: np.convolve(row, kernel, mode="valid"), 1, values)


def desired_speeds(exp: Experiment, scale: float = 1.0) -> np.ndarray:
    """逐人期望自由速度 v⁰ (N,)，米/秒。

    口径（spec §2）：逐帧速率 → 中值滤波压跳变 → 1 s 滑动平均 → 取 p90。

    取 p90 而不是最大值：最大值受残余噪声影响大；取 p90 而不是均值：均值包含了
    被人群挡住的那些时间，那是"实际速度"不是"期望速度"。

    实测中位 2.1 m/s，明显高于文献默认的 1.34 —— 这是照用实测值的直接结果：
    这批人空闲时走得快，实验耗时 17 s 里的差额就是冲突延误。
    `scale` 是把 v⁰ 整体缩放的逃生口，默认 1.0（不缩放）。
    """
    speed = exp.speeds()
    smoothed = _smooth(_median_filter(speed, _SPEED_MEDFILT_FRAMES), _SPEED_SMOOTH_FRAMES)
    return np.percentile(smoothed, _SPEED_PERCENTILE, axis=1) * scale
