# week02：Circle Antipode 实验的轨迹可视化与微观行人建模

本周两项工作：

1. **把实验数据画出来** —— `circle-10m-64-1.txt` 的轨迹图（先看清楚数据长什么样）；
2. **建 Detour-aware GCFV 微观模型** —— 模拟这 64 个人的正对径穿越，并用实验轨迹评估。

---

## 目录结构

```
week02/
├── README.md                  本文件
├── Detour_aware_GCFV.md       模型设计文档（要建什么、为什么、边界在哪）
├── design-detour-gcfv.md      实现 spec（数学结构、接口、参数、评估口径、与论文的偏差）
├── model/                     代码
│   ├── plot_circle.py             任务一：实验数据轨迹图
│   └── detour_gcfv/               任务二：Detour-aware GCFV 模型
│       ├── paths.py               全部路径常量（目录调整只改这里）
│       ├── data.py                实验数据读取、初值/目标/逐人 v⁰
│       ├── geometry.py            椭圆几何、间隙距离、路线几何
│       ├── gcfv.py                Module C：GCFV 局部运动（主模型与 baseline 共用）
│       ├── route.py               Module A/B：路线选择与期望方向
│       ├── sim.py                 仿真循环
│       ├── metrics.py             评估指标
│       ├── run.py                 命令行入口：跑仿真、落 CSV 与指标
│       └── compare.py             命令行入口：出对比图
└── results/                   产物
    ├── figures/                   所有图
    └── out/                       轨迹 CSV（仿真）与指标 JSON
```

---

## 数据说明

实验文件在**仓库根目录**：`circle-10m-64-1.txt`（不在本周目录里，路径见 `model/detour_gcfv/paths.py`）。

这是北京交通大学做的 **Circle Antipode（圆环正对径穿越）**实验：64 名行人均匀站在半径 10 m
的圆环上，同时出发走向自己正对面的位置。

| 项 | 值 |
|---|---|
| 规模 | 64 人 × 425 帧（第 37–461 帧） |
| 采样率 | 25 fps，全程 17.0 s |
| 列序 | `行人ID 帧号 x y RUN_ID`，空格分隔 |
| 单位 | **厘米**（圆环半径约 1000 = 10 m） |

三个坑，踩过才知道：

1. **列序与 Social-GAN 系列的 `frame id x y` 相反**。正着读每步中位位移 5.4 cm（约 1.35 m/s），
   反着读 6.6 m（约 165 m/s）—— 看速度就知道哪个对。
2. **单位是厘米不是米**，直接当米用会把 10 m 的场子画成 1 km。
3. **不是 week01 那套 2.5 fps**（ETH/UCY 是 0.4 s 一采样）。这里 25 fps，Δt = 0.04 s。

另外：末帧 64 人**全部静止**（都走到了正对径点停下），且每人终点距起点正对径点中位仅 0.24 m ——
这两点直接决定了仿真要设「到达即停」规则、要按各自的正对径点设目标。

---

## 快速开始

```bash
# 0. 环境（首次）
uv sync --no-install-project      # 见下方「环境」一节，不能省 --no-install-project

# 1. 实验数据轨迹图 -> results/figures/circle_light.png
.venv/Scripts/python.exe week02/model/plot_circle.py

# 2. 跑仿真（主模型 + baseline1），约 2 秒 -> results/out/
.venv/Scripts/python.exe week02/model/detour_gcfv/run.py

# 3. 出对比图 -> results/figures/
.venv/Scripts/python.exe week02/model/detour_gcfv/compare.py
```

常用参数：

```bash
plot_circle.py --no-labels          # 不写 64 个行人编号
plot_circle.py --mode dark          # 出深色版（默认只出亮色版）
run.py --model main                 # 只跑主模型
run.py --v0-scale 1.4               # 把期望速度整体缩到文献水平
```

---

## 模型

三层结构（详见 [design-detour-gcfv.md](design-detour-gcfv.md)）：

```
Module A 路线/绕行决策    C_i(R) = α·L(R)/v⁰ + β·ΔT(R)，R ∈ {直行, 左绕, 右绕}
        ↓
Module B 期望方向         路线 → 当前期望方向
        ↓
Module C GCFV 局部运动    椭圆间隙距离 + 速度子模型 + 一阶方向子模型 + 圆形边界
```

- **局部运动**用的是 Xu–Chraibi–Tordeux–Zhang (2019) 的广义无碰撞速度模型
  （[*Generalized collision-free velocity model for pedestrian dynamics*](https://arxiv.org/abs/1908.10304)）。
- **路线决策**是本项目新增的：**ΔT 用 GCFV 自己的速度子模型估计** —— 沿候选路线前进，
  用邻人的预测位置算出最小间隙，直接套速度子模型得到预测速度，再积分「慢掉的那部分」。
  路线层与运动层因此同源，不会出现"路线层以为很快、运动层根本走不动"。
- **个体差异**：逐人从实验数据提取期望速度 v⁰（1 s 平滑速度的 p90，中位 2.1 m/s ——
  明显高于文献默认的 1.34，因为照用实测值，这批人空闲时走得快）。
- **Baseline 1**：同一套局部运动，路线恒为直行。用来回答"绕行决策层到底有没有用"。

时间尺度是两层：局部运动每步 0.04 s 更新，路线每 1.0 s 才重新决策一次。

### 论文偏差（实现时按 spec §9，不按论文印刷式）

论文椭圆版把邻居影响印成 `R(d)=k·exp(d/D)`，而 d 是分离时为正的边界间隙 —— 加号会让影响
**随距离增长**，与圆形版的 `exp((ℓ−s)/D)` 单调性相反，等于把排斥变成吸引。判为印刷笔误，
实现取 `exp(−d/D)`。三条证据见 spec §9。

---

## 结果与已知差距

`results/out/metrics.json` 里有完整指标，图在 `results/figures/`。

| 指标 | 实验 | 主模型 | baseline1 |
|---|---|---|---|
| 到达用时均值 (s) | 12.07 | 12.37 | 12.65 |
| 末帧位置误差 FDE (m) | — | 0.40 | 0.47 |
| 全程均速中位 (m/s) | 1.37 | 1.22 | 1.23 |
| **距圆心最近距离 d_center 中位 (m)** | **1.62** | **0.46** | 0.56 |
| **绕行（d_center ≥ 1 m）人数** | **42** | **12** | 7 |

**做到**：到达时间、速度分布、终点位置都对得上；主模型的绕行人数是 baseline 的近两倍，
说明绕行决策层确实在起作用。

**没做到**：绕行**程度**远少于实验（12 人 vs 42 人）。轨迹图上很直观 —— 实验是一团散开的
曲线，仿真是几乎笔直穿过圆心的放射线。用同一套椭圆几何量下来，仿真里人与人贴得比实验近得多
（人均最小间隙中位 −0.35 m vs 实验 −0.07 m，深度重叠），**局部避让太短程，人贴身才躲**。

已排除：把速度子模型的搜索带从常数 `b_min` 换成各人当前短半轴 `b_i`，反而更差
（RMSE 2.81 → 3.02）。

**下一步**：参数标定（本轮范围外）。最该扫的是 `D`（邻居影响长度，论文 0.1 m）和
`T`（速度-间隙系数，论文 1.06 s）—— 这两个是论文从走廊实验标出来的，在开阔场地的密集
对穿场景下很可能偏小。建议先做 `D` 的敏感性粗扫，比直接上优化器省事。

---

## 环境

`uv` 管理，Python 3.9 + numpy + matplotlib。

```bash
uv sync --no-install-project
```

**必须带 `--no-install-project`**：`pyproject.toml` 声明了 `[project.scripts]` 和
`uv_build` 构建后端，但仓库里没有 `src/datasets/__init__.py`，直接 `uv sync` 会在
「构建本项目」这一步失败（与本周工作无关的既有问题）。带上这个参数就只装依赖、跳过构建。

出图默认只出**亮色版**（`plot_circle.py` 的默认 `--mode light`），深色版要显式指定。
