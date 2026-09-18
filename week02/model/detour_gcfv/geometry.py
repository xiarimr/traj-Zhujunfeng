"""椭圆几何、间隙距离与路线几何 —— 被 gcfv.py 和 route.py 共用。

这个文件是「广义」那一步的落点：行人不是圆，而是**沿运动方向拉长的椭圆**，
两人之间的相互作用距离不是圆心距，而是**椭圆边界到边界的间隙**。

长半轴 a 沿当前运动方向（论文 §4 的结论：τ_a 与 T 在稳态分析里作用相同，
作者直接把 τ_a 丢掉、取 a 为常数）；短半轴 b 随速度变化，走得越快肩越窄。
"""

from __future__ import annotations

import numpy as np


def ellipse_radius(direction: np.ndarray, heading: np.ndarray, a: float, b: np.ndarray) -> np.ndarray:
    """方向 `direction` 上椭圆边界的极径。

    把 direction 投影到以 heading 为长轴的椭圆自身坐标系，取该方向的极径：

        r(û) = 1 / sqrt( cos²θ / a² + sin²θ / b² )

    参数支持广播：direction 可以是 (…,2)，heading 是 (…,2)，b 是 (…,)。

    `direction` 必须是单位向量（调用方保证）；a、b 是半轴长度（不是直径）。

    退化方向（零向量，比如两点重合）没有几何意义，这时返回短半轴 b 这个保守的体宽 ——
    不返回 inf：inf 会在下游的 `gap = 距离 − 半径` 里变成 −inf，再进 exp 就溢出成 NaN，
    而 NaN 会一路污染到路线代价，让 `argmin` 静默失效。
    """
    cos_t = np.sum(direction * heading, axis=-1)
    sin_t = direction[..., 0] * heading[..., 1] - direction[..., 1] * heading[..., 0]
    # 阈值取 1e-6（对应方向长度 1e-3）而不是更小的值：两点几乎重合时方向是数值垃圾，
    # 极小的方向长度会让极径炸到 1e5 量级，把 gap 污染成一个荒唐的大负数
    degenerate = (cos_t * cos_t + sin_t * sin_t) < 1e-6
    # 先把分母夹住再除：np.where 两个分支都会算，直接用 where 兜底仍会触发 1/0 警告
    denom = np.sqrt(cos_t * cos_t / (a * a) + sin_t * sin_t / (b * b))
    return np.where(degenerate, b, 1.0 / np.maximum(denom, 1e-12))


def gap_matrix(pos: np.ndarray, heading: np.ndarray, a: float, b: np.ndarray) -> np.ndarray:
    """所有人两两之间的边界间隙，返回 (N, N)，对角线为 +inf。

    d_ij = ‖p_j − p_i‖ − r_i(û_ij) − r_j(û_ji)，沿两心连线量到各自的椭圆边界。
    分离时 d > 0，重叠时 d < 0。
    """
    delta = pos[None, :, :] - pos[:, None, :]          # (N,N,2)，delta[i,j] = p_j − p_i
    dist = np.linalg.norm(delta, axis=-1)              # (N,N)
    # 对角线（自己和自己）距离为 0，会给出零向量方向；先塞个无意义但非零的值，
    # 底下反正会被 fill_diagonal 覆盖成 +inf
    np.fill_diagonal(dist, 1.0)
    unit = delta / np.maximum(dist, 1e-9)[..., None]   # û_ij

    r_i = ellipse_radius(unit, heading[:, None, :], a, b[:, None])   # i 朝 j 看
    r_j = ellipse_radius(-unit, heading[None, :, :], a, b[None, :])  # j 朝 i 看

    gap = dist - r_i - r_j
    np.fill_diagonal(gap, np.inf)                      # 自己和自己不成邻居
    return gap


def speed_to_shoulder(speed: np.ndarray, b_min: float, b_max: float, beta: float, gamma: float) -> np.ndarray:
    """短半轴随速度变化：b = b_min + (b_max − b_min) / (1 + exp(β(V − γ)))。

    走起来肩变窄（b → b_min），慢下来/站住时肩变宽（b → b_max）—— 站着的人占地更大，
    这在本场景里很重要：实测末帧 64 人全部静止站立，他们是别人的障碍。
    """
    return b_min + (b_max - b_min) / (1.0 + np.exp(beta * (speed - gamma)))


def circle_wall(pos: np.ndarray, heading: np.ndarray, a: float, b: np.ndarray, radius: float):
    """半径 `radius` 的圆形边界，返回 (d_iw, cos α_v)。

    论文的墙是一段段直线，需要"离人最近的墙点" C；对圆来说有解析解 ——
    C 就是圆心到人的射线与圆的交点，不用折线近似。

        C_i     = R · p_i / ‖p_i‖
        e_iv    = (p_i − C_i) / ‖p_i − C_i‖      从墙指向人
        α_v     = ∠(e_i, −e_iv)                  cos α_v > 0 表示人朝墙走
        d_iw    = ‖p_i − C_i‖ − r_i(û_iw)        û_iw 从人指向墙

    返回值 cos α_v 可能 ≤0（人背对墙），调用方在算 dw = d/cos α 时要按下限保护。
    """
    radius_now = np.linalg.norm(pos, axis=-1, keepdims=True)
    unit_out = pos / np.maximum(radius_now, 1e-9)      # 圆心 -> 人
    closest = radius * unit_out                        # C_i
    to_wall = closest - pos                            # 人 -> 墙
    dist = np.linalg.norm(to_wall, axis=-1)
    unit_to_wall = to_wall / np.maximum(dist, 1e-9)[..., None]

    d_iw = dist - ellipse_radius(unit_to_wall, heading, a, b)
    cos_alpha = np.sum(heading * (-unit_to_wall), axis=-1)   # ∠(e_i, −e_iv)
    return d_iw, cos_alpha


def point_at_arclength(start: np.ndarray, waypoint: np.ndarray, goal: np.ndarray, s: np.ndarray) -> np.ndarray:
    """沿折线 start→waypoint→goal 走弧长 s 处的点（s 可以是数组，逐元素算）。

    用于路线选择时沿候选路径取样，估计"我走到这里会被谁挡住"。
    """
    s = np.atleast_1d(np.asarray(s, dtype=float))
    seg1 = waypoint - start
    len1 = float(np.linalg.norm(seg1))
    seg2 = goal - waypoint
    len2 = float(np.linalg.norm(seg2))

    unit1 = seg1 / len1 if len1 > 1e-12 else np.zeros(2)
    unit2 = seg2 / len2 if len2 > 1e-12 else np.zeros(2)

    on_first = s <= len1
    out = np.where(on_first[:, None], start + unit1 * s[:, None],
                   waypoint + unit2 * np.clip(s - len1, 0.0, len2)[:, None])
    return out


def route_length(start: np.ndarray, waypoint: np.ndarray, goal: np.ndarray) -> float:
    """折线 start→waypoint→goal 的长度。"""
    return float(np.linalg.norm(waypoint - start) + np.linalg.norm(goal - waypoint))


def lateral_waypoint(start: np.ndarray, goal: np.ndarray, delta: float, side: float) -> np.ndarray:
    """把 start→goal 弦的中点沿法向偏移，得到绕行航路点。

    `side` 取 +1 或 −1 决定往哪边绕。直线路径恰好穿过圆心，所以左右绕行
    等价于「从圆心两侧绕开」，偏移量 δ 就是绕行幅度。
    """
    chord = goal - start
    length = float(np.linalg.norm(chord))
    if length < 1e-9:
        return goal.copy()
    unit = chord / length
    normal = np.array([-unit[1], unit[0]])          # 左法向
    return start + 0.5 * chord + side * delta * normal
