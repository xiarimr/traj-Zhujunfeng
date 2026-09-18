# Circle Antipode 行人实验

## Detour-aware GCFV 微观行人模型设计与实现说明

### 1. 任务背景

目标是使用 Python 建立一个微观行人仿真模型，用于模拟已有的 Circle Antipode 行人实验数据。

实验场景具有以下特征：

* 圆形实验区域半径约为 10 m；
* 64 名行人同时参与实验；
* 行人初始位置均匀分布在圆周附近；
* 每名行人的目标位于其初始位置的圆对侧；
* 行人从初始位置同时出发；
* 实验包含逐时间步的行人位置/轨迹数据；
* 需要使用真实实验轨迹对模型进行参数标定，并最终比较模拟轨迹与实验轨迹。

本任务的目标不是建立简单的“固定速度 + 固定路径”模型，而是建立能够解释以下行为的微观模型：

1. 行人趋向自己的目标；
2. 行人之间会发生相互避让；
3. 圆心附近会形成高冲突区域；
4. 部分行人会直接穿越圆心；
5. 部分行人会提前绕开圆心；
6. 不同行人的速度、空间偏好和风险敏感程度存在个体差异；
7. 行人的路线选择应该受到“额外绕行距离”和“潜在冲突/延误”的共同影响。

---

# 2. 模型总体思路

模型采用两层决策结构：

```
长期/中期路线选择
        ↓
  直行或绕行决策
        ↓
  当前期望运动方向
        ↓
   GCFV 局部运动
        ↓
    下一时刻状态
```

模型名称暂定为：

```
Detour-aware GCFV Model
```

整体由三个模块构成：

### Module A：Route / Detour Choice

决定行人当前采用：

* Straight：直接趋向目标；
* Left Detour：左侧绕行；
* Right Detour：右侧绕行。

### Module B：Desired Direction

根据路线选择结果生成当前期望运动方向。

### Module C：GCFV Local Motion

根据：

* 期望运动方向；
* 当前速度；
* 邻居位置；
* 邻居速度；
* 行人身体尺寸；
* 安全距离；
* 相对运动关系；

计算当前时刻的碰撞规避速度，并更新位置。

---

# 3. 为什么不能直接使用传统 SFM

传统 Social Force Model 可以作为 baseline，但不应该作为最终主模型。

传统 SFM 的基本结构为：

```
Desired Force
+ Pedestrian Repulsion
+ Boundary Repulsion
```

其主要问题是：

* 行人容易一直指向自己的目标；
* 绕行通常只在冲突已经很明显以后发生；
* 难以自然表示行人提前预判中心区域拥堵并选择绕行；
* 难以同时解释“直接穿越圆心”和“主动绕行”两种行为。

因此，本项目需要在局部运动模型之前增加显式的路线/绕行决策层。

---

# 4. Module A：路线选择模型

## 4.1 候选路线

对于每个行人 i，在某一决策时刻考虑：

```
R ∈ {straight, left, right}
```

其中：

* straight：当前直接朝目标；
* left：从目标方向的一侧绕行；
* right：从目标方向的另一侧绕行。

路线选择不应完全依赖固定几何规则，而应同时考虑：

1. 路径长度；
2. 行人自身期望速度；
3. 预计冲突；
4. 预计延误；
5. 周围行人密度；
6. 个体行为参数。

---

## 4.2 核心决策思想

路线代价应具有如下结构：

```
C_i(R)
=
FreeTravelCost_i(R)
+
ConflictCost_i(R)
```

最基本形式：

```
C_i(R)
=
L_i(R) / v_i^0
+
ΔT_i(R)
```

其中：

* L_i(R)：路线 R 的预计路径长度；
* v_i^0：行人 i 的期望自由行走速度；
* ΔT_i(R)：由于行人冲突造成的预计额外时间。

最终：

```
R_i* = argmin_R C_i(R)
```

这里不要求所有行人都选择最短路径。

---

# 5. “高速行人经过圆心”的行为要求

模型必须能够表示以下现象：

如果不存在明显的行人冲突，那么：

```
straight route
```

具有最短路径。

对于圆半径 R：

```
L_straight = 2R
```

当 R = 10 m 时：

```
L_straight = 20 m
```

因此在没有拥堵和冲突的情况下，模型应该自然倾向于直接穿越圆心。

但是，在多行人同时运动时，直线路径可能经过高密度冲突区域，因此：

```
T_straight
=
L_straight / v_i^0
+
ΔT_straight
```

绕行路线：

```
T_detour
=
L_detour / v_i^0
+
ΔT_detour
```

由于：

```
L_detour > L_straight
```

因此只有当：

```
ΔT_straight - ΔT_detour
```

足够大时，绕行才具有优势。

模型应该因此产生：

* 低冲突 → 直行；
* 中等冲突 → 部分行人绕行；
* 高冲突 → 更多行人绕行。

不能简单规定：

```
high-speed pedestrian = always straight
```

而应该由：

```
speed
+ route length
+ predicted conflict
```

共同决定路线。

---

# 6. 个体差异

不能让 64 名行人完全使用相同参数。

至少允许以下参数存在个体差异：

```
v_i^0       # desired speed
τ_i         # response / relaxation time
r_i         # body radius
α_i         # route-length preference
β_i         # congestion/conflict sensitivity
```

因此可以形成：

```
fast + low detour tendency
fast + high conflict sensitivity
slow + low conflict sensitivity
slow + high conflict sensitivity
```

等不同类型。

模型的目标不是人为规定每个人属于哪一类，而是尽可能通过实验数据标定这些参数。

---

# 7. Module B：Desired Direction

路线选择后得到：

```
R_i*
```

将其转换成当前期望方向：

```
e_i^des
```

如果选择 straight：

```
e_i^des = direction_to_goal
```

如果选择 detour：

```
e_i^des = direction_to_detour_waypoint
```

因此：

```
Route Choice
      ↓
Desired Direction
      ↓
Local Motion
```

要求路线选择层与局部运动层解耦。

---

# 8. Module C：GCFV 局部运动

GCFV 模块负责解决当前时刻：

> “在不发生不合理碰撞的情况下，我现在应该以什么速度和方向移动？”

输入至少包括：

```
current position
current velocity
desired direction
neighboring pedestrians' positions
neighboring pedestrians' velocities
pedestrian radius / size
```

输出：

```
v_i(t)
```

随后更新：

```
p_i(t+Δt)
=
p_i(t)
+
v_i(t) Δt
```

模型必须保持连续二维运动。

---

# 9. 圆形场景的特殊约束

由于实验区域是圆形，需要处理圆形边界。

定义圆心：

```
c = (c_x, c_y)
```

圆半径：

```
R = 10 m
```

对于行人位置：

```
p_i = (x_i, y_i)
```

计算：

```
d_i = ||p_i - c||
```

要求：

```
d_i ≤ R_boundary
```

边界作用可以通过以下方式实现：

1. Boundary force；
2. Boundary projection；
3. Collision-free constraint；

三者选其一即可，但必须保证行人不会明显穿出实验区域。

---

# 10. 邻居选择

不要让每个行人与 63 个行人全部发生强相互作用。

应建立邻居集合：

```
N_i = {j | distance(i,j) < R_neighbor}
```

或者使用最近 K 个邻居。

建议支持：

* distance-based neighborhood；
* optional K-nearest neighborhood。

邻居选择必须考虑相对位置和相对速度，而不仅仅是欧氏距离。

---

# 11. 决策时间尺度

路线选择不需要每一个仿真时间步都重新进行。

建议采用：

```
Route decision interval = ΔT_route
```

而 GCFV 局部运动每个仿真时间步更新：

```
Δt_motion
```

满足：

```
Δt_motion << ΔT_route
```

例如：

```
motion:
    0.05 ~ 0.10 s

route decision:
    0.5 ~ 2.0 s
```

具体数值后续通过数据进行调整。

这样可以体现：

```
长期路线决策
+
高频局部避碰
```

而不是每一帧都重新规划路线。

---

# 12. 参数标定

实验轨迹应该用于标定模型参数，而不是只用于最后画图。

参数集合：

```
θ =
{
    desired speed parameters,
    relaxation parameters,
    body size parameters,
    interaction parameters,
    detour parameters
}
```

目标：

```
θ* = argmin J(θ)
```

推荐目标函数：

```
J =
    w1 J_trajectory
  + w2 J_speed
  + w3 J_travel_time
  + w4 J_path_length
  + w5 J_detour
```

其中：

### J_trajectory

比较：

```
p_i^sim(t)
```

和：

```
p_i^exp(t)
```

例如：

```
position RMSE
ADE
FDE
```

---

### J_speed

比较：

```
v_i^sim(t)
```

与：

```
v_i^exp(t)
```

---

### J_travel_time

比较每个行人的总旅行时间。

---

### J_path_length

比较：

```
L_i^sim
```

和：

```
L_i^exp
```

---

### J_detour

比较行人的：

```
closest distance to center
```

或者：

```
maximum lateral deviation
```

从而保证模型不仅“平均走得差不多”，而且能够复现：

```
direct pedestrians
+
detouring pedestrians
```

---

# 13. 必须重点观察的现象

最终验证不能只有一个 RMSE。

必须检查：

### 1. 轨迹形态

是否同时出现：

```
center-crossing
detour
```

---

### 2. 速度分布

模拟速度分布是否接近实验。

---

### 3. 旅行时间

实验与仿真的：

```
mean travel time
```

以及：

```
individual travel time distribution
```

---

### 4. 路径长度

检查：

```
simulated path length
vs.
experimental path length
```

---

### 5. 圆心通过程度

定义：

```
d_center,i
=
min_t ||p_i(t)-c||
```

用于判断：

* 谁穿过圆心；
* 谁绕开圆心。

---

### 6. 个体行为差异

不能只比较 64 人平均值。

应检查：

```
high-speed pedestrians
medium-speed pedestrians
low-speed pedestrians
```

是否产生合理的路线选择差异。

---

# 14. Baseline 模型

为了验证新增绕行决策层是否真正有效，需要至少保留一个 baseline：

## Baseline 1：Traditional SFM / GCFV without detour

即：

```
desired direction = direction to goal
```

没有显式 Route Choice。

用途：

证明加入 detour decision 后，模型是否改善。

---

## Baseline 2：Detour-aware GCFV

完整模型：

```
Route Choice
     ↓
Desired Direction
     ↓
GCFV
```

这是主模型。

---

# 15. 不建议的方案

本阶段不要直接采用：

* LSTM trajectory predictor；
* Transformer trajectory predictor；
* GNN；
* Diffusion trajectory model；
* Reinforcement Learning；
* 纯机器学习黑盒。

原因不是这些模型不能拟合轨迹，而是本任务需要：

```
behavioral interpretability
+
microscopic interaction
+
route-choice explanation
+
physical consistency
```

优先使用可解释的行为模型。

---

# 16. Python 实现原则

后续实现时：

* 使用 Python；
* NumPy 负责数值计算；
* SciPy 可用于参数优化；
* Pandas 用于实验数据读取和整理；
* Matplotlib 用于结果可视化；
* 模型核心不依赖 SUMO；
* 不要求安装大型行人仿真软件；
* 数据输入和模型代码解耦；
* 允许后续替换 Route Choice 或 GCFV 模块。

推荐代码逻辑：

```
load experiment data
        ↓
initialize pedestrians
        ↓
route decision
        ↓
desired direction
        ↓
neighbor detection
        ↓
GCFV update
        ↓
boundary handling
        ↓
position update
        ↓
repeat
        ↓
output trajectories
        ↓
calibration / evaluation
```

---

# 17. 当前阶段的实现边界

当前任务只负责：

1. 确定模型数学结构；
2. 明确各模块输入输出；
3. 明确参数；
4. 明确实验数据如何用于标定；
5. 明确验证指标。

当前阶段不要：

* 修改已有项目代码；
* 直接运行完整仿真；
* 使用深度学习；
* 添加没有明确行为意义的复杂参数；
* 为了降低轨迹 RMSE 而加入纯黑盒修正项。

---

# 18. 最终模型的核心表达

整个模型可以最终概括为：

```
Route Choice:

R_i*
=
argmin_R
[
    L_i(R) / v_i^0
    +
    ΔT_i(R)
]

↓

Desired Direction:

e_i^des = f(R_i*, goal, geometry)

↓

Local Motion:

v_i(t)
=
GCFV(
    e_i^des,
    p_i,
    v_i,
    N_i
)

↓

State Update:

p_i(t+Δt)
=
p_i(t)
+
v_i(t)Δt
```

最终输出：

```
{p_i(t), v_i(t)}   for i = 1,...,64
```

并使用真实实验轨迹进行参数标定和独立验证。

---

# 19. 设计目标

最终模型应满足以下行为一致性：

```
无明显冲突
    → 直行

中等冲突
    → 直行 + 部分绕行

高冲突
    → 更多绕行
```

同时：

```
不同行人
    → 不同速度
    → 不同决策倾向
    → 不同轨迹
```

模型应该能够在不人为指定具体轨迹的情况下，自发产生：

```
center-crossing trajectories
+
detour trajectories
```

这两个群体。

最终目标不是让模型“机械复制已有轨迹”，而是通过少量具有行为意义的参数，让模型能够合理生成与真实 Circle Antipode 实验统计特征和微观轨迹均一致的行人运动。
