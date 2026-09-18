"""Module A：路线 / 绕行决策。

    C_i(R) = α_i · L_i(R) / v⁰_i  +  β_i · ΔT_i(R)
    R_i*   = argmin_R C_i(R)

候选三条：straight（直接朝目标）、left / right（从弦中点向两侧偏移 δ 绕行）。
本场景里直线路径恰好穿过圆心，所以左右绕行就是「从圆心两侧绕开」。

**ΔT 怎么估**是本模块的关键：沿候选路线以 v⁰ 前进，每个预测时刻用邻人的匀速外推位置
算出最小间隙 d(t)，再套 **GCFV 自己的速度子模型** 得到 V(t)，最后积分「慢掉的那部分」：

    ΔT = Σ_t (1 − V(t)/v⁰) · Δt_pred

这样路线层与局部运动层同源 —— 决策所依据的延误，就是局部运动模型真会产生的延误，
除了预测时长 H 之外没有额外参数，也不会出现「路线层以为很快、运动层根本走不动」的矛盾。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .geometry import ellipse_radius, point_at_arclength, lateral_waypoint, route_length, speed_to_shoulder

ROUTE_NAMES = ("straight", "left", "right")


@dataclass
class RouteParams:
    """路线决策的参数。δ 与 H 是设计文档里没有、由本项目新增的两个行为参数。"""

    delta: float = 2.0             # 绕行幅度 δ，米：左右航路点相对弦中点的横向偏移
    # ΔT 预测时长上限，秒。实际用的时长是「该路线的自由通行时间 L/v⁰」（见 predicted_delay），
    # 这个值只是兜底上限。**不能用固定的小值**：三条路线只在弦中点附近才分岔，而中点距起点
    # 约 10 m、以 v⁰ 走要 4 s 以上；预测时长若短于走到中点的时间，就根本看不到圆心拥堵，
    # 三条路线的 ΔT 全是"起步阶段人人拥挤"且几乎相等，路线选择退化成比谁短。
    horizon_cap: float = 12.0
    decision_interval: float = 1.0  # 路线决策间隔 ΔT_route，秒（局部运动每步更新，路线不）
    sample_dt: float = 0.2         # 沿候选路线的采样间隔，秒
    neighbour_radius: float = 10.0  # ΔT 的邻人半径筛，米
    hysteresis: float = 0.95       # 新路线代价要低于当前路线这个比例才切换（防抖）
    keep_straight_within: float = 1.0  # 距目标小于此距离时固定直行，米


def candidate_waypoints(pos: np.ndarray, goal: np.ndarray, delta: float) -> dict:
    """三条候选路线的航路点。straight 的航路点就是目标本身。"""
    return {
        "straight": goal.copy(),
        "left": lateral_waypoint(pos, goal, delta, +1.0),
        "right": lateral_waypoint(pos, goal, delta, -1.0),
    }


def predicted_delay(pos_i, heading_i, v0_i, waypoint, goal_i, others, params: RouteParams, gcfv) -> float:
    """沿候选路线前进，估计因冲突而多花的时间 ΔT（秒）。

    `others` 是 (M,2)/(M,2)/(M,2)/(M,) 四个数组：邻人位置、速度、朝向、短半轴
    —— 由调用方按半径筛好，且**不含行人自己**。

    邻人集合刻意用半径筛而不是视域筛：视域回答的是「我现在朝哪看」，
    而 ΔT 要回答的是「我沿这条路走下去会撞上谁」，包括我还没转向他那边的人。
    """
    if v0_i <= 1e-6 or others[0].shape[0] == 0:
        return 0.0

    other_pos, other_vel, other_heading, other_b = others
    # 预测窗口 = 走完这条路线的自由通行时间，封顶 horizon_cap
    horizon = min(route_length(pos_i, waypoint, goal_i) / v0_i, params.horizon_cap)
    times = np.arange(params.sample_dt, horizon + 1e-9, params.sample_dt)
    if times.size == 0:
        return 0.0

    # 自身：沿路线以 v⁰ 前进，椭圆形状按 v⁰ 定（估计延误时假设自己不受阻）
    walked = point_at_arclength(pos_i, waypoint, goal_i, v0_i * times)      # (K,2)
    own_b = float(speed_to_shoulder(np.array([v0_i]), gcfv.b_min, gcfv.b_max, gcfv.beta, gcfv.gamma)[0])

    # 邻人：匀速外推。只保留整段预测里可能出现交集的那些
    predicted = other_pos[None, :, :] + other_vel[None, :, :] * times[:, None, None]   # (K,M,2)

    delta = walked[:, None, :] - predicted                                  # (K,M,2)：p_i − p_j
    dist = np.linalg.norm(delta, axis=-1)
    from_j = delta / np.maximum(dist, 1e-9)[..., None]                       # j -> i 单位向量

    r_self = ellipse_radius(from_j, heading_i, gcfv.a, own_b)
    r_other = ellipse_radius(-from_j, other_heading[None, :, :], gcfv.a, other_b[None, :])
    gap = dist - r_self - r_other

    d_min = np.min(gap, axis=1)                                             # (K,)
    speed = np.minimum(v0_i, np.maximum(0.0, d_min / gcfv.T))                # GCFV 速度子模型
    return float(np.sum(1.0 - speed / v0_i) * params.sample_dt)


def prediction_velocities(pos, goal, v0, arrival_radius: float, stopped_radius: float = 0.05):
    """外推邻人未来位置用的速度：朝各自目标、以期望速度走。

    **不能用当前速度外推**。实测起步时人员速度中位只有 0.35 m/s，按当前速度外推等于
    预测"所有人都站着不动"，圆心附近根本估不出拥堵，ΔT 全为 0，直行永远最便宜 ——
    模型就退化成 baseline 了。

    已经到达的人（站住不动）例外，他们的外推速度取零：末态 64 人全部站立在环上，
    把他们预测成继续走会严重高估延误。
    """
    direction = goal - pos
    norm = np.linalg.norm(direction, axis=-1, keepdims=True)
    unit = direction / np.maximum(norm, 1e-9)
    arrived = norm[:, 0] < arrival_radius
    return np.where(arrived[:, None], 0.0, unit * v0[:, None])


def decide_all(pos, heading, speed, v0, goal, current_route, alpha, beta, params: RouteParams, gcfv,
               arrival_radius: float = 0.3):
    """给所有行人做一次路线决策，返回路线名数组。

    `current_route` 是上一次的决策结果（字符串数组或 None）。两条防抖规则在这里生效：
    ① 新路线代价要低于当前路线 `hysteresis` 倍才切换；② 距目标已很近时固定直行。
    """
    n = pos.shape[0]
    # 外推用的速度与椭圆形状都按"以期望速度朝目标走"来定，与 GCFV 的速度子模型同源
    velocity = prediction_velocities(pos, goal, v0, arrival_radius)
    speed_norm = np.linalg.norm(velocity, axis=-1, keepdims=True)
    # 站住不动的人外推速度为零，方向无意义，退回其当前朝向
    pred_heading = np.where(speed_norm > 1e-9, velocity / np.maximum(speed_norm, 1e-9), heading)
    b = speed_to_shoulder(v0, gcfv.b_min, gcfv.b_max, gcfv.beta, gcfv.gamma)
    chosen = np.empty(n, dtype=object)

    for i in range(n):
        remaining = float(np.linalg.norm(goal[i] - pos[i]))
        if remaining < params.keep_straight_within or v0[i] <= 1e-6:
            chosen[i] = "straight"
            continue

        # 邻人：半径筛，排除自己
        distance = np.linalg.norm(pos - pos[i], axis=-1)
        mask = (distance <= params.neighbour_radius)
        mask[i] = False
        others = (pos[mask], velocity[mask], pred_heading[mask], b[mask])

        waypoints = candidate_waypoints(pos[i], goal[i], params.delta)
        costs = {}
        for name, waypoint in waypoints.items():
            length = route_length(pos[i], waypoint, goal[i])
            delay = predicted_delay(pos[i], heading[i], v0[i], waypoint, goal[i], others, params, gcfv)
            costs[name] = alpha[i] * length / v0[i] + beta[i] * delay

        best = min(costs, key=costs.get)
        previous = None if current_route is None else current_route[i]
        if previous in costs and costs[best] >= params.hysteresis * costs[previous]:
            chosen[i] = previous
        else:
            chosen[i] = best

    return chosen


def desired_direction(pos, goal, routes, delta, params: RouteParams) -> np.ndarray:
    """Module B：把路线选择结果转成当前期望方向 e⁰_i。

    与 Module C 完全解耦 —— Module C 只接收 `e⁰_i`，不知道路线是怎么选出来的，
    所以 baseline 只要把这里恒设成"指向目标"就能复用整个局部运动层。
    """
    out = np.empty_like(pos)
    for i in range(pos.shape[0]):
        name = routes[i]
        if name == "straight":
            target = goal[i]
        else:
            target = lateral_waypoint(pos[i], goal[i], delta, +1.0 if name == "left" else -1.0)
        direction = target - pos[i]
        norm = float(np.linalg.norm(direction))
        out[i] = direction / norm if norm > 1e-9 else np.array([1.0, 0.0])
    return out
