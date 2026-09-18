"""Module C：GCFV 局部运动 —— 速度子模型 + 方向子模型 + 圆形边界。

回答的是设计文档 §8 那个问题：「在不发生不合理碰撞的情况下，我现在应该以什么速度和方向移动？」

模型：Xu, Chraibi, Tordeux, Zhang, *Generalized collision-free velocity model for pedestrian
dynamics*, Physica A 535, 122521 (2019)。

## 符号约定（关键，写错方向就会反）

论文里 `e_ij` 是**从 j 指向 i** 的单位向量（不是 i 指向 j）。判据是墙那句明确写的
"e_i,v is the unit vector from C_v towards X_i" —— 墙和行人用同一套约定。只有按这个约定：

* 方向式里 `+R·e_ij` 才是**排斥**（把我推离 j），而不是吸引；
* `e_i·e_ij < 0` 才是「j 在我前方」（j 在前方时，j→i 的向量与我朝向相反）；
* 速度式里 `J_i` 选出的才是「挡在我前面的人」，而不是我身后的人。

本文件的变量名一律带 `from_` / `to_` 前缀防止搞混。

## 与论文的两处偏差

1. **影响函数取 `exp(−d/D)`，不取论文印的 `exp(d/D)`**。详见 spec `design-detour-gcfv.md` §9：
   椭圆版印刷式的加号会让影响随距离增长，把排斥变成吸引，判为笔误。
2. **圆形墙用解析解**（圆心到人的射线与圆的交点）代替论文的折线段；论文的「两顶点都在
   视域内」判据对圆墙没有顶点，改用「最近点落在视域内」。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .geometry import circle_wall, gap_matrix, speed_to_shoulder


@dataclass
class GCFVParams:
    """论文默认值，除 `boundary_radius`（本场景 10 m）与 `cos_alpha_floor`（数值保护）外均可照抄。"""

    a: float = 0.18              # 椭圆长半轴（沿运动方向），米
    T: float = 1.06              # 速度-间隙系数，秒：V = d/T
    k: float = 3.0               # 邻居方向影响强度
    D: float = 0.1               # 邻居方向影响长度，米
    k_w: float = 6.0             # 墙方向影响强度
    D_w: float = 0.05            # 墙方向影响长度，米
    b_min: float = 0.15          # 短半轴下限（快走时）
    b_max: float = 0.25          # 短半轴上限（站住时）
    beta: float = 50.0           # 短半轴 sigmoid 陡度
    gamma: float = 0.1           # 短半轴 sigmoid 速度偏移
    tau: float = 0.3             # 方向松弛时间，秒
    # 圆形边界半径。**不是 10 m**：实验在开阔场地进行，10 m 圆环是行走路线（人站在环上，
    # 起点半径 9.72~10.52 m），把墙设在 10 m 会把人贴着环冻住，墙项 d/T 还会限制环上的正常行走。
    # 取 12 m = 实测最大半径 10.52 m + 余量，让它只兜底、不干扰圆环附近的行为。
    boundary_radius: float = 12.0
    cos_alpha_floor: float = 0.1     # cos α_v 下限，避免贴墙平行走时除零


def neighbourhoods(pos, heading, desired, params, b):
    """算出方向用的视域和速度用的运动带，返回 (area, band, from_j_unit, gap)。

    `from_j_unit[i,j]` 是从 j 指向 i 的单位向量（见模块文档的符号约定）。
    `gap[i,j]` 是 i、j 之间的椭圆边界间隙（对称，对角线 +inf）。
    """
    n = pos.shape[0]
    delta = pos[:, None, :] - pos[None, :, :]              # p_i − p_j
    dist = np.linalg.norm(delta, axis=-1)
    from_j_unit = delta / np.maximum(dist, 1e-9)[..., None]  # j -> i

    gap = gap_matrix(pos, heading, params.a, b)
    off_diagonal = ~np.eye(n, dtype=bool)

    # 视域：当前朝向的前半平面 ∪ 期望方向的前半平面
    head_proj = np.sum(heading[:, None, :] * from_j_unit, axis=-1)
    want_proj = np.sum(desired[:, None, :] * from_j_unit, axis=-1)
    area = ((head_proj < 0) | (want_proj < 0)) & off_diagonal

    # 运动带：前方、且横向偏离不超过 b_min（论文椭圆版的灰带宽度 2 b_min）
    perp = np.stack([-heading[:, 1], heading[:, 0]], axis=-1)          # e_i^⊥
    lateral = np.abs(np.sum(perp[:, None, :] * from_j_unit, axis=-1))
    band = (head_proj <= 0) & (lateral <= params.b_min) & off_diagonal

    return area, band, from_j_unit, gap


def speed_submodel(gap, band, wall_gap, wall_cos, v0, params):
    """速度子模型：V = min{ v⁰, max(0, d/T), max(0, dw/T) }。

    d 是运动带内最小间隙 —— 间隙越小走得越慢，间隙为负（重叠）直接停住，
    所以这个模型是**一阶无碰撞**的：速度天然不会把人推进重叠区。
    """
    d_min = np.min(np.where(band, gap, np.inf), axis=1)
    speed = np.minimum(v0, np.maximum(0.0, d_min / params.T))

    # 墙只在「朝墙走」时限制速度；背对墙时 dw 无意义（cos α_v ≤ 0），置为无限
    toward_wall = wall_cos > 0
    dw = np.where(toward_wall, wall_gap / np.maximum(wall_cos, params.cos_alpha_floor), np.inf)
    speed = np.minimum(speed, np.maximum(0.0, dw / params.T))
    return np.clip(speed, 0.0, v0)


def direction_submodel(pos, heading, desired, params, b, area, gap, from_j_unit, wall_gap, wall_cos, rng):
    """方向子模型（一阶）：先算最优方向 E_i，再按 de/dt = (E − e)/τ 松弛。

    E_i = u( e⁰_i + Σ R(d_ij) e^N_ij + Σ R_w(d_iw) e^N_iw )

    影响方向 e^N 不是指向邻居，而是**垂直于期望方向**、按障碍落在哪一侧选取：
    障碍在左就往右让，反之亦然（正面相遇 C=0 时随机取一侧，即侧身让行）。
    """
    perp0 = np.stack([-desired[:, 1], desired[:, 0]], axis=-1)     # e⁰_i 逆时针转 90°（左）

    # 行人项：C_j = e_ij · e⁰⊥ 定左右
    side_score = np.sum(from_j_unit * perp0[:, None, :], axis=-1)
    side = np.where(side_score > 0, 1.0, -1.0)
    ties = area & (np.abs(side_score) < 1e-9)
    if ties.any():
        side = np.where(ties, rng.choice(np.array([-1.0, 1.0]), size=side.shape), side)

    # exp(−d/D)：d 为负（重叠）时指数为正。两侧都截到 ±50，保证权值有限且不溢出
    weight = params.k * np.exp(np.clip(-gap / params.D, -50.0, 50.0))
    influence = weight[..., None] * side[..., None] * perp0[:, None, :]
    total = np.sum(np.where(area[..., None], influence, 0.0), axis=1)

    # 墙项：视域判据 = 最近点落在视域内（朝墙走，或期望方向朝墙）
    cosine_with_want = _wall_toward_desired(pos, desired, params)
    wall_visible = (wall_cos > 0) | (cosine_with_want > 0)

    from_wall = _from_wall_unit(pos)                                  # 墙 -> 人
    wall_side_score = np.sum(from_wall * perp0, axis=-1)
    wall_side = np.where(wall_side_score > 0, 1.0, -1.0)
    wall_weight = params.k_w * np.exp(np.clip(-wall_gap / params.D_w, -50.0, 50.0))
    wall_term = (wall_weight * wall_side)[:, None] * perp0
    total = total + np.where(wall_visible[:, None], wall_term, 0.0)

    optimal = desired + total
    norm = np.linalg.norm(optimal, axis=-1, keepdims=True)
    # 极端对称时 E 可能退化为零向量，退回期望方向
    optimal = np.where(norm > 1e-9, optimal / np.maximum(norm, 1e-9), desired)
    return optimal


def _from_wall_unit(pos):
    """从圆形边界最近点指向人的单位向量（若人恰在圆心则退化为 +x）。"""
    radius = np.linalg.norm(pos, axis=-1, keepdims=True)
    fallback = np.array([1.0, 0.0])
    return np.where(radius > 1e-9, pos / np.maximum(radius, 1e-9), fallback)


def _wall_toward_desired(pos, desired, params):
    """期望方向朝墙的程度 cos α_v⁰ = e⁰_i · û_iw。"""
    from_wall = _from_wall_unit(pos)
    to_wall = -from_wall                      # 人 -> 墙
    return np.sum(desired * to_wall, axis=-1)


def step(pos, heading, speed, desired, v0, params: GCFVParams, dt: float, active: np.ndarray, rng):
    """推进一个时间步，返回 (新位置, 新朝向, 新速度)。

    `active` 为 False 的行人（已到达）位置冻结、朝向不更新，但**仍然作为别人的邻居参与计算**
    —— 实测末帧 64 人全部静止站立，站着的人本身就是障碍物。
    """
    b = speed_to_shoulder(speed, params.b_min, params.b_max, params.beta, params.gamma)
    area, band, from_j_unit, gap = neighbourhoods(pos, heading, desired, params, b)
    wall_gap, wall_cos = circle_wall(pos, heading, params.a, b, params.boundary_radius)

    new_speed = speed_submodel(gap, band, wall_gap, wall_cos, v0, params)
    optimal = direction_submodel(
        pos, heading, desired, params, b, area, gap, from_j_unit, wall_gap, wall_cos, rng
    )
    new_heading = heading + (dt / params.tau) * (optimal - heading)
    norm = np.linalg.norm(new_heading, axis=-1, keepdims=True)
    new_heading = new_heading / np.maximum(norm, 1e-9)

    # 已到达的人：速度归零、朝向冻结（不参与自己的更新，但上面已算进别人的邻居里）
    new_speed = np.where(active, new_speed, 0.0)
    new_heading = np.where(active[:, None], new_heading, heading)

    new_pos = pos + (new_speed * dt)[:, None] * new_heading

    # 边界投影：墙项之外再兜一道，保证不会明显穿出实验区
    radius_now = np.linalg.norm(new_pos, axis=-1, keepdims=True)
    outside = (radius_now[:, 0] > params.boundary_radius)
    if outside.any():
        scale = np.where(
            outside[:, None],
            params.boundary_radius / np.maximum(radius_now, 1e-9),
            1.0,
        )
        new_pos = new_pos * scale

    return new_pos, new_heading, new_speed
