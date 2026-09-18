"""评估指标 —— 设计文档 §13 要求的六类观察，不是一个 RMSE 就完事。

轨迹 RMSE 只能说明"平均走得差不多"，说明不了模型有没有自发产生直穿和绕行这两群人。
所以核心指标是 **d_center**（每人全程距圆心的最近距离）：它一次性回答"谁穿过了圆心、
谁绕开了"，而且实验数据里这个量是连续分布的（0.04~8.68 m），可以直接比。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .data import Experiment, goals
from .sim import SimResult

# 到达判定容差（米）。实验里 64 人终点的最终位置距名义目标点最远 0.49 m，
# 容差取 0.5 才能覆盖全部 64 人；仿真侧用同一个容差，保证两边同口径。
ARRIVAL_TOLERANCE = 0.5

# d_center 的分群阈值（米）：小于它算"直穿圆心"，否则算"绕行"
CENTER_CROSSING_THRESHOLD = 1.0

# 快/中/慢三档的分位
SPEED_BANDS = ((0.0, 1 / 3), (1 / 3, 2 / 3), (2 / 3, 1.0))


@dataclass
class Metrics:
    label: str
    rmse: float                       # 全体逐帧位置 RMSE，米
    ade: float                        # 平均位移误差，米
    fde: float                        # 末帧位移误差，米
    d_center: np.ndarray              # (N,) 每人距圆心最近距离
    travel_time: np.ndarray           # (N,) 到达用时，秒
    path_length: np.ndarray           # (N,) 路程
    mean_speed: np.ndarray            # (N,) 全程均速

    @property
    def center_crossing(self) -> int:
        return int((self.d_center < CENTER_CROSSING_THRESHOLD).sum())

    @property
    def detouring(self) -> int:
        return int((self.d_center >= CENTER_CROSSING_THRESHOLD).sum())

    def summary(self) -> dict:
        return {
            "label": self.label,
            "rmse_m": round(self.rmse, 3),
            "ade_m": round(self.ade, 3),
            "fde_m": round(self.fde, 3),
            "travel_time_mean_s": round(float(np.nanmean(self.travel_time)), 2),
            "travel_time_median_s": round(float(np.nanmedian(self.travel_time)), 2),
            "path_length_mean_m": round(float(self.path_length.mean()), 2),
            "mean_speed_median_mps": round(float(np.median(self.mean_speed)), 2),
            "d_center_median_m": round(float(np.median(self.d_center)), 2),
            "center_crossing_lt1m": self.center_crossing,
            "detouring_ge1m": self.detouring,
        }


def _distance_to_center(positions: np.ndarray) -> np.ndarray:
    """(N,T,2) -> (N,) 每人全程距原点的最近距离。"""
    return np.linalg.norm(positions, axis=-1).min(axis=1)


def _travel_time(positions: np.ndarray, goal: np.ndarray, dt: float) -> np.ndarray:
    """首次进入目标容差的时刻，秒；始终没进则为 nan。"""
    distance = np.linalg.norm(positions - goal[:, None, :], axis=-1)
    inside = distance < ARRIVAL_TOLERANCE
    out = np.full(positions.shape[0], np.nan)
    for i in range(positions.shape[0]):
        hit = np.flatnonzero(inside[i])
        if hit.size:
            out[i] = (hit[0] + 1) * dt
    return out


def _path_length(positions: np.ndarray) -> np.ndarray:
    return np.linalg.norm(np.diff(positions, axis=1), axis=-1).sum(axis=1)


def _mean_speed(positions: np.ndarray, dt: float) -> np.ndarray:
    return np.linalg.norm(np.diff(positions, axis=1), axis=-1).mean(axis=1) / dt


def evaluate(positions: np.ndarray, exp: Experiment, label: str,
             reference: np.ndarray | None = None) -> Metrics:
    """算一组轨迹的指标。

    `reference` 是用于算 RMSE 的对照轨迹（不传就用实验轨迹）。
    baseline 与主模型都要跟实验比，所以显式传更清楚。
    """
    target = exp.positions if reference is None else reference
    if target.shape != positions.shape:
        raise ValueError(f"轨迹形状不一致：{positions.shape} vs {target.shape}")

    error = np.linalg.norm(positions - target, axis=-1)          # (N,T)
    start = exp.positions[:, 0, :]
    goal = goals(start)
    dt = exp.dt

    return Metrics(
        label=label,
        rmse=float(np.sqrt((error ** 2).mean())),
        ade=float(error.mean()),
        fde=float(error[:, -1].mean()),
        d_center=_distance_to_center(positions),
        travel_time=_travel_time(positions, goal, dt),
        path_length=_path_length(positions),
        mean_speed=_mean_speed(positions, dt),
    )


def speed_band_groups(v0: np.ndarray) -> dict:
    """按期望速度分成快/中/慢三组，返回 {组名: 布尔掩码}。

    设计文档 §13.6 明确要求"不能只比较 64 人平均值"：要看快的人是不是更倾向直穿、
    慢的人是不是更倾向绕行。
    """
    order = np.argsort(v0)
    rank = np.empty_like(order)
    rank[order] = np.arange(v0.size)
    frac = rank / max(v0.size - 1, 1)
    names = ("慢速组", "中速组", "快速组")
    return {name: (frac >= lo) & (frac <= hi) for name, (lo, hi) in zip(names, SPEED_BANDS)}


def compare_summaries(experiment_metrics: Metrics, *others: Metrics) -> str:
    """把实验与各模型的 summary 拼成一张可读的对照表。"""
    rows = [experiment_metrics.summary()] + [m.summary() for m in others]
    keys = list(rows[0].keys())
    width = max(len(str(k)) for k in keys)
    header = "指标".ljust(width) + "".join(f"{r['label']:>26}" for r in rows)
    lines = [header, "-" * len(header)]
    for key in keys:
        if key == "label":
            continue
        lines.append(str(key).ljust(width) + "".join(f"{str(r[key]):>26}" for r in rows))
    return "\n".join(lines)
