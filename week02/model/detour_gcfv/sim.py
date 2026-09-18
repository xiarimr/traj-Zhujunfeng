"""仿真循环 —— 把三个模块按设计文档 §16 的流程图串起来。

    读实验数据 → 初始化 → [路线决策 → 期望方向 → 邻居搜索 → GCFV → 边界 → 位置更新] × 425

时间尺度是两层（设计文档 §11）：**局部运动每步更新（0.04 s），路线决策每 1 s 才做一次**。
这不是偷懒：行人的绕行意图不会每 40 ms 变一次，把它和局部避让放在同一频率会来回抖动。

积分是显式欧拉 + **并行更新**：所有人同时用 t 时刻的邻居状态算 t+1，不做串行化 ——
串行会让先算的人在"这一瞬间"躲开还没动的人，凭空产生优势。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import gcfv as gcfv_module
from .data import DT, Experiment, desired_speeds, goals, initial_state
from .gcfv import GCFVParams
from .route import RouteParams, decide_all, desired_direction


@dataclass
class SimConfig:
    steps: int | None = None          # None = 自动取「实验帧数 − 1」，见 run()
    dt: float = DT                    # 0.04 s = 实验的 25 fps，不需要重采样
    use_detour: bool = True           # False = Baseline 1（Module A 恒为 straight）
    gcfv: GCFVParams = field(default_factory=GCFVParams)
    route: RouteParams = field(default_factory=RouteParams)
    seed: int = 20260918
    alpha_jitter: float = 0.1         # 个体差异：路径长度偏好 α_i 的抖动幅度
    beta_jitter: float = 0.1          # 个体差异：冲突敏感度 β_i 的抖动幅度
    v0_scale: float = 1.0             # v⁰ 的整体缩放逃生口，默认不缩放
    arrival_radius: float = 0.3       # 距目标小于此距离即视为到达，米


@dataclass
class SimResult:
    positions: np.ndarray      # (N, T, 2) 米，与 Experiment.positions 同形状同顺序
    v0: np.ndarray             # (N,) 逐人期望速度
    arrival: np.ndarray        # (N,) 到达时刻（秒），未到达为 nan
    routes: np.ndarray         # (N,) 最后一次决策的路线名
    label: str = "model"


def _initial_heading(pos, goal, vel):
    """朝向初值 = 速度方向；首步速度为零（追踪异常）时退化为指向目标的方向。"""
    speed = np.linalg.norm(vel, axis=-1, keepdims=True)
    fallback = goal - pos
    fallback = fallback / np.maximum(np.linalg.norm(fallback, axis=-1, keepdims=True), 1e-9)
    moving = speed[:, 0] > 1e-9
    return np.where(moving[:, None], vel / np.maximum(speed, 1e-9), fallback)


def run(exp: Experiment, config: SimConfig | None = None) -> SimResult:
    """跑一次仿真，返回逐帧轨迹。"""
    config = config or SimConfig()
    rng = np.random.default_rng(config.seed)

    # 实验有 T 帧 = T−1 个时间间隔，所以步数取 T−1，仿真的 T 个采样点才与实验逐帧对齐
    n_steps = config.steps if config.steps is not None else exp.n_frames - 1

    pos0, vel0 = initial_state(exp)
    goal = goals(pos0)
    v0 = desired_speeds(exp, config.v0_scale)
    heading = _initial_heading(pos0, goal, vel0)
    speed = np.linalg.norm(vel0, axis=-1)

    # 个体差异：α（路径长度偏好）、β（冲突敏感度）在 1.0 附近抖动，固定种子可复现
    alpha = 1.0 + rng.uniform(-config.alpha_jitter, config.alpha_jitter, pos0.shape[0])
    beta = 1.0 + rng.uniform(-config.beta_jitter, config.beta_jitter, pos0.shape[0])

    n_ped = pos0.shape[0]
    pos = pos0.copy()
    active = np.ones(n_ped, dtype=bool)
    arrival = np.full(n_ped, np.nan)
    routes = np.full(n_ped, "straight", dtype=object)

    traj = np.empty((n_ped, n_steps + 1, 2))
    traj[:, 0, :] = pos

    decision_every = max(1, int(round(config.route.decision_interval / config.dt)))

    for step in range(n_steps):
        # Module A：低频路线决策。baseline 走这里的分支，恒为 straight
        if config.use_detour and step % decision_every == 0:
            routes = decide_all(pos, heading, speed, v0, goal, routes, alpha, beta,
                                config.route, config.gcfv, config.arrival_radius)
        # Module B：期望方向每步都重算（走到哪指向哪），但路线本身不变
        desired = desired_direction(pos, goal, routes, config.route.delta, config.route)

        pos, heading, speed = gcfv_module.step(
            pos, heading, speed, desired, v0, config.gcfv, config.dt, active, rng
        )

        # 到达判定：一进阈值就停下，之后不再移动，但仍作为障碍影响别人
        newly = active & (np.linalg.norm(pos - goal, axis=-1) < config.arrival_radius)
        if newly.any():
            arrival[newly] = (step + 1) * config.dt
            active = active & ~newly

        traj[:, step + 1, :] = pos

    label = "detour-aware" if config.use_detour else "baseline1 (no detour)"
    return SimResult(positions=traj, v0=v0, arrival=arrival, routes=routes, label=label)
