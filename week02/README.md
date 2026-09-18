# week02：Circle Antipode 实验的 Detour-aware GCFV 模型

在圆环正对径穿越场景下，建立一个**可解释的微观行人模型**：64 名行人同时从半径 10 m 的圆环
出发、走向各自的正对径点，模型要能自己产生「一部分人直穿圆心、一部分人提前绕开」这两种行为。

- 模型设计意图：[`Detour_aware_GCFV.md`](Detour_aware_GCFV.md)
- 实现 spec（数学结构、接口、参数、评估口径、与论文的偏差）：[`design-detour-gcfv.md`](design-detour-gcfv.md)

---

# 一、模型思路

## 1.1 要复现的现象

实验数据里有两组人同时存在，这是模型的验收标准：

- **直穿**：22 人全程距圆心最近距离 < 1 m（最近的只有 0.04 m）；
- **绕行**：42 人 ≥ 1 m，最远的绕到 8.68 m 外。

不是「平均轨迹像就行」—— 一个只会走直线的模型也能把平均路径长度做得差不多，
但它解释不了为什么有人绕、有人不绕。

## 1.2 为什么不能只用一个局部运动模型

传统 Social Force 或单纯的局部避让模型有个共同问题：**行人一直指向目标，绕行只在冲突
已经很明显之后才发生**。放到本场景里就是：所有人都朝圆心走，等挤到一起才互相推，结果是
所有人硬挤过圆心。

要产生「提前绕开」，必须在局部运动**之前**加一层显式的路线决策，而且这层决策要能预判
「我走这条线会遇到多少麻烦」。

## 1.3 三层结构

```
Module A  路线/绕行决策     每 1.0 s 决策一次
    C_i(R) = α_i · L_i(R)/v⁰_i + β_i · ΔT_i(R),   R ∈ {直行, 左绕, 右绕}
        ↓
Module B  期望方向          每一步重算（走到哪指向哪），但路线不变
    R*=直行 → e⁰ 指向目标；R*=绕行 → e⁰ 指向绕行航路点
        ↓
Module C  GCFV 局部运动     每 0.04 s 更新
    速度子模型 + 一阶方向子模型 + 椭圆间隙距离 + 圆形边界
```

**分层的关键在于两个时间尺度不同**：局部避让是 0.04 s 级的反应，绕行意图是秒级的计划。
把两者放在同一频率会让路线每个时间步都翻来覆去地抖动。Module B 每步都算，但它只是把
已经定好的路线翻译成当前朝向 —— 决策和执行的解耦就在这里。

### 局部运动用的是 GCFV（广义无碰撞速度模型）

行人不是圆，而是**沿运动方向拉长的椭圆**；两人之间的作用距离不是圆心距，而是
**椭圆边界到边界的间隙**。速度子模型

```
V = min{ v⁰, max(0, d/T), max(0, dw/T) }        d = 前方运动带内的最小间隙
```

天然是一阶无碰撞的：间隙越小速度越低，间隙为负就停住，不可能主动走进重叠区。
方向子模型则是一阶松弛 `de/dt = (E − e)/τ`，其中 `E` 由期望方向、邻居影响和墙影响合成。

### 绕行航路点怎么定

直线路径恰好穿过圆心，所以「绕行」在本场景里有明确的几何含义：把起点→目标弦的**中点向
法向偏移 δ = 2 m**，得到左右两个航路点。δ 也就是「绕多远」，是有行为含义的量。

## 1.4 核心：ΔT 怎么估（本项目的关键设计）

路线代价里的 `ΔT` 是「走这条路预计会因冲突而多花多少时间」。它的估法是：

> **沿候选路线前进，每个预测时刻用邻人的预测位置算出最小间隙 d(t)，
> 直接套 GCFV 自己的速度子模型得到 V(t)，再积分「慢掉的那部分」。**

```
ΔT = Σ_t ( 1 − V(t)/v⁰ ) · Δt_pred,     V(t) = min{ v⁰, max(0, d(t)/T) }
```

这样做的意义是**路线层与运动层同源**：决策所依据的延误，就是局部运动模型真会产生的延误，
不会出现「路线层以为这条很快、运动层根本走不动」的自相矛盾。除预测窗口外不引入新参数。

实现时这里有两个坑，都是跑起来才发现的，值得单独记：

1. **邻人外推不能用当前速度。** 实测起步时人员速度中位只有 0.35 m/s，按当前速度外推等于
   预测「所有人站着不动」，圆心附近永远估不出拥堵，ΔT 恒为 0，**主模型直接退化成 baseline**。
   必须按「各自朝自己的目标、以 v⁰ 行进」外推；已经站住的人除外。
2. **预测窗口不能取固定值。** 三条路线只在弦中点附近才分岔，而中点距起点约 10 m、
   以 v⁰ 走要 4 s 以上。窗口短于走到中点的时间，就根本看不到圆心拥堵，三条路线的 ΔT
   几乎相等，路线选择退化成「比谁短」。现在的做法是取该路线的自由通行时间 `L/v⁰`。

## 1.5 个体差异与参数

- **期望速度 v⁰_i**：逐人从实验数据提取（逐帧速率 → 中值滤波压跳变 → 1 s 滑动平均 → 取 p90），
  中位 **2.1 m/s**。这**明显高于文献默认的 1.34 m/s** —— 是照用实测值的结果：这批人空闲时
  走得快（自由穿越约 9.5 s），而实验实际用了 17 s，差额就是冲突延误。
- **路径长度偏好 α_i、冲突敏感度 β_i**：1.0 ± 0.1 的固定种子抖动。设计上这两者应当由数据
  标定，本轮只留了接口（见 §1.6）。
- 其余物理参数（椭圆长短轴、影响强度与长度、松弛时间等）用论文默认值。

## 1.6 本轮不做的事

**参数标定没做。** 论文的 `D`（邻居影响长度 0.1 m）和 `T`（速度-间隙系数 1.06 s）是从
**走廊实验**标出来的，在开阔场地的密集对穿场景下很可能偏小 —— 已知的差距与下一步建议见 §四。

也不做：深度学习、GNN、纯黑盒拟合。这个任务要的是行为可解释性、微观交互和路线选择的
因果解释，不是一个更低的 RMSE。

## 1.7 与论文的一处必要偏差

论文椭圆版把邻居影响印成 `R(d) = k·exp(d/D)`，而 `d` 是**分离时为正**的边界间隙 ——
加号会让影响**随距离增长**，与圆形版的 `exp((ℓ−s)/D)` 单调性相反，等于把「排斥」变成「吸引」。

判为印刷笔误，实现取 **`R(d) = k·exp(−d/D)`**。三条证据：

1. 论文自己称 R 为 "repulsive function"，排斥必然随距离衰减；
2. 开源实现 JuPedSim 里同一个模型的参数就叫 `strength_neighbor_repulsion` /
   `range_neighbor_repulsion` —— 强度配一个作用**范围**，同样是衰减语义；
3. 同一批作者在后续工作（*Prolonged Clogs in Bottleneck Simulations*，Physica A 573:125934）
   中复述该模型时写作 `exp(−s/D)`。

---

# 二、代码逻辑

## 2.1 模块划分

```
week02/model/detour_gcfv/
├── paths.py       全部路径常量（数据在 datasets/，产物在 results/）
├── data.py        实验数据读取、初值、目标点、逐人 v⁰        ← 与模型解耦：产物是纯数组
├── geometry.py    椭圆几何、间隙距离、路线几何                ← 被 gcfv / route 共用
├── gcfv.py        Module C：GCFV 局部运动                    ← 主模型与 baseline 共用
├── route.py       Module A/B：路线决策与期望方向
├── sim.py         仿真循环
├── metrics.py     评估指标
├── run.py         命令行入口：跑仿真、落 CSV 与指标
└── compare.py     命令行入口：出对比图
```

模块边界刻意按**可替换**划：换掉 Module A 不用碰 `gcfv.py`，换掉局部运动不用碰 `route.py`，
数据读取与模型完全解耦（`data.py` 不知道 GCFV 的存在，模型侧也不碰文件路径）。

## 2.2 一次仿真的数据流

```
load_experiment()            读 datasets/circle-10m-64-1.txt → (64, 425, 2) 的米制轨迹
initial_state()              位置取实验首帧；速度取首步前向差分
goals()                      目标 = 起点在 10 m 圆上的正对径点
desired_speeds()             逐人 v⁰（中值滤波 → 1 s 平滑 → p90）
      ↓
for step in 424:             Δt = 0.04 s（= 实验的 25 fps，不重采样）
    if step % 25 == 0:       ← 每 1.0 s
        Module A  decide_all()       三条候选路线算代价，argmin（带 5% 滞回防抖）
    Module B      desired_direction() 路线 → 当前期望方向
    Module C      gcfv.step()         邻居搜索 → 速度子模型 → 方向子模型 → 位置更新
    边界投影      越界的人压回 12 m 圆内
    到达判定      距目标 < 0.3 m 即停住，之后仍作为别人的障碍
      ↓
SimResult(positions, v0, arrival, routes)
```

**积分是显式欧拉 + 并行更新**：所有人同时用 t 时刻的邻居状态算 t+1，不串行化 ——
串行会让先算的人在"这一瞬间"躲开还没动的人，凭空产生优势。

## 2.3 关键函数速查

| 文件 | 函数 | 干什么 |
|---|---|---|
| `data.py` | `load_experiment` / `initial_state` / `goals` / `desired_speeds` | 数据 → 初值、目标、v⁰ |
| `geometry.py` | `ellipse_radius` | 某方向上椭圆边界的极径 |
| | `gap_matrix` | 所有人两两的**边界间隙**矩阵（不是圆心距） |
| | `circle_wall` | 圆形边界解析求最近点、间隙、`cos α_v` |
| | `lateral_waypoint` / `route_length` / `point_at_arclength` | 路线几何 |
| `gcfv.py` | `neighbourhoods` | 方向用的**视域** + 速度用的**运动带** |
| | `speed_submodel` / `direction_submodel` | 两个子模型 |
| | `step` | 一整套局部运动更新（主模型与 baseline 共用） |
| `route.py` | `candidate_waypoints` | 直行 / 左绕 / 右绕三个航路点 |
| | `prediction_velocities` | 邻人外推速度（朝目标、以 v⁰；站住的人为 0） |
| | `predicted_delay` | **ΔT 估计**，用 GCFV 自己的速度子模型 |
| | `decide_all` | 三条路线定价 + 滞回切换 |
| | `desired_direction` | Module B |
| `sim.py` | `run` | 仿真主循环 |
| `metrics.py` | `evaluate` | RMSE / ADE / FDE / d_center / 旅行时间 / 路径长 |
| | `speed_band_groups` | 按 v⁰ 分快/中/慢三组（§13.6 要求不能只看平均值） |

主模型与 baseline 的差别**只有一个布尔开关**（`SimConfig.use_detour`）：关掉时 Module A
恒返回 straight，其余代码路径完全相同，所以两者的对比是干净的。

## 2.4 想改哪个模块

| 想改什么 | 动哪 | 注意 |
|---|---|---|
| 绕行幅度 / 决策频率 | `RouteParams.delta` / `decision_interval` | |
| 换一种 ΔT 估法 | `route.predicted_delay` | 保持输入输出签名即可 |
| 换局部运动模型 | `gcfv.step` | 需要 `(pos, heading, speed, desired, v0, params, dt, active, rng)` → `(pos, heading, speed)` |
| 加新场景 | `data.py` + `paths.py` | 模型侧不需要改 |
| 加新指标 | `metrics.evaluate` | 同步 `Metrics.summary()` 才会进 JSON |

---

# 三、参考文献与开源实现

## 局部运动模型（GCFV）

1. **Xu, Q., Chraibi, M., Tordeux, A., Zhang, J. (2019).**
   *Generalized collision-free velocity model for pedestrian dynamics.*
   Physica A **535**, 122521. [arXiv:1908.10304](https://arxiv.org/abs/1908.10304)
   —— 本项目 Module C 的直接来源：椭圆间隙距离、一阶方向子模型、墙项、全部默认参数。

2. **Tordeux, A., Chraibi, M., Seyfried, A. (2016).**
   *Collision-free speed model for pedestrian dynamics.*
   [arXiv:1512.05597](https://arxiv.org/abs/1512.05597)
   —— 上一代模型（圆形版）。理解「一阶无碰撞」这个性质从哪里来要读它。

3. **Xu, Q., Chraibi, M., Seyfried, A. (2021).**
   *Prolonged Clogs in Bottleneck Simulations for Pedestrian Dynamics.*
   Physica A **573**, 125934. [arXiv:2105.03954](https://arxiv.org/abs/2105.03954)
   —— 同一模型的后续工作，也是 §1.7 中影响函数符号的旁证之一。

## 开源实现

- **[JuPedSim](https://github.com/PedestrianDynamics/jupedsim)**（Python 接口 `pip install jupedsim`，
  LGPL-3.0-or-later，于利希研究中心开发）—— GCFV 系列模型的参考实现，其中的
  `jupedsim.models.CollisionFreeSpeedModel` / `V2` / `V3` 就是这一族模型。
  - 值得注意：**它的默认参数与论文并不相同**（例如邻居排斥强度 8.0、范围 0.1 m；
    几何排斥 5.0、范围 0.02 m），说明这套参数本身是需要按场景标定的。
  - **V3 与本项目的结构相近**：把转向与速度选择解耦，方向按「朝最相关前方邻居的
    反侧旋转」确定，速度用最优速度关系从间距算出，并对航向做一阶松弛。
  - 本项目没有直接调用它，理由是设计文档要求「模型核心不依赖大型仿真软件」、
    且需要把 Module A 插在局部运动之前 —— 自行实现更容易控制接口与可解释性。
    **做参数标定时值得拿它做交叉验证。**

## 实验数据与场景

- **Xu, Q. 等.** *Investigation of pedestrian dynamics in circle antipode experiments:
  Analysis and model evaluation with macroscopic indexes.*
  [arXiv:1808.01443](https://arxiv.org/abs/1808.01443)
  —— 实验设计与宏观指标分析。实验在 5 m 与 10 m 两种半径的圆上做，人数取
  8/16/32/64，每种条件重复四次；本仓库的数据对应其中的 **10 m / 64 人**条件。
- **[rickyspy/Behavior-Model-Data](https://github.com/rickyspy/Behavior-Model-Data)**
  —— 该实验的公开数据与复现模型。

**本仓库数据文件的格式**（2026-09-18 实测确认）：

| 项 | 值 |
|---|---|
| 规模 | 64 人 × 425 帧（第 37–461 帧） |
| 列序 | `行人ID 帧号 x y RUN_ID`，空格分隔 —— **与 Social-GAN 那套 `frame id x y` 相反** |
| 单位 | **厘米**（圆环半径约 1000 = 10 m），与 ETH/UCY 的米不同 |
| 采样率 | **25 fps**（Δt = 0.04 s），也不是 ETH/UCY 的 0.4 s |
| 末态 | 64 人全部静止（都走到了正对径点停下） |

列序读反了每步中位位移会从 5.4 cm 变成 6.6 m（约 165 m/s）—— 看速度就能判断读没读错。
单位读错则会把 10 m 的场子画成 1 km。这两条已分别写进 `data.py` 与 `plot_circle.py` 的注释。

> **数据出处待确认。** 仓库里没有记录 `datasets/circle-10m-64-1.txt` 的来历。文件名
> `circle-10m-64-1`、5 列构成（行人ID/帧号/x/y/RUN_ID）与上述项目的 10m-64p 条件吻合，
> 实测路径长 21–33 m 也落在该论文报告的 20–33 m 内；但**本文件的坐标单位是厘米**
> （圆环半径约 1000），而该项目文档标注为米，且 RUN_ID 取值（160/170/180）含义不明。
> 所以只当作场景背景引用，不作为确证。
>
> 另：该论文报告 10 m 实验中**行人偏好从右侧绕行**。本模型目前没有编码这个偏好
> （`C_j = 0` 时随机取一侧，α/β 左右对称），这可能是绕行比例偏低的另一个原因。

---

# 四、运行与结果

## 运行

```bash
# 环境（首次）
uv sync --no-install-project      # 必须带这个参数，原因见根 README

# 仿真：主模型 + baseline1，约 2 秒
.venv/Scripts/python.exe week02/model/detour_gcfv/run.py
# 出图
.venv/Scripts/python.exe week02/model/detour_gcfv/compare.py
# 实验数据本身的轨迹图（另一件事）
.venv/Scripts/python.exe week02/model/plot_circle.py
```

产物：`results/out/` 下轨迹 CSV（格式与实验文件一致，可互换）与 `metrics.json`，
`results/figures/` 下三张对比图。

## 结果

| 指标 | 实验 | 主模型 | baseline1 |
|---|---|---|---|
| 到达用时均值 (s) | 12.07 | 12.37 | 12.65 |
| 末帧位置误差 FDE (m) | — | 0.40 | 0.47 |
| 全程均速中位 (m/s) | 1.37 | 1.22 | 1.23 |
| **d_center 中位 (m)** | **1.62** | **0.46** | 0.56 |
| **绕行（d_center ≥ 1 m）人数** | **42** | **12** | 7 |

**做到**：到达时间、速度分布、终点位置都对得上；主模型绕行人数是 baseline 的近两倍，
绕行决策层确实在起作用。

**没做到**：绕行**程度**远少于实验（12 人 vs 42 人）。轨迹图上很直观 —— 实验是一团散开的
曲线，仿真是几乎笔直穿过圆心的放射线。用同一套椭圆几何量下来，仿真里人与人贴得比实验近得多
（人均最小间隙中位 −0.35 m vs 实验 −0.07 m），**局部避让太短程，人贴身才躲**。

已排除：把速度子模型的搜索带从常数 `b_min` 换成各人当前短半轴 `b_i`，反而更差（RMSE 2.81→3.02）。

**下一步**建议先做 `D`（邻居影响长度）的敏感性粗扫，再考虑 `T`；如果绕行的**左右分布**
明显不对称，则说明该补上 §三 提到的右侧偏好项。
