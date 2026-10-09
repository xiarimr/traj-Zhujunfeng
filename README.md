# 行人轨迹数据集与建模实验

以行人轨迹研究为起点的数据集与逐周实验，week04 扩展到车辆轨迹的流量—密度分析。

行人数据包括 **ETH / UCY** 五场景基准（行人轨迹预测最常用的公开数据），
以及**北京交通大学 Circle Antipode（圆环正对径穿越）实验**（64 人从半径 10 m 的圆环出发、
同时走向各自的正对径点）。
week04 使用 **NGSIM I-80 车辆轨迹**（2005-04-13 16:00–16:15），SI 单位输入与来源说明保存在 `week04/data/`。

---

## 仓库逻辑

目录约定如下，week04 的数据与辅助归档位置单独说明：

1. **输入数据保持只读。** 行人原始数据放在 `datasets/`，week04 的车辆输入放在 `week04/data/`；
   不在输入目录里改数据、不把中间结果混进去。
2. **每周一个 `weekNN/` 目录，主要包含三块**：

   ```
   weekNN/
   ├── README.md    这一周做了什么、怎么跑、结论是什么
   ├── <代码>       当周的可执行代码（目录名按内容定，如 model/）
   └── results/     当周的产物：图、轨迹、指标 JSON
   ```

   代码读取对应输入，主要产物写入当周 `results/`，跨周不互相依赖。
   week04 另有 `data/` 保存输入、`archive/` 保存辅助检查结果和历史分析。
3. **每周的 README 是那一周的主文档。** 数据集格式的梳理属于做它的那一周（见 week01），
   本文件只讲仓库整体与每周工作的索引。

## 目录结构

```
pedestrian_dataset/
├── datasets/                      原始数据，只读
│   ├── ETH/                       seq_eth、seq_hotel（自带 README）
│   ├── UCY/                       zara01、zara02、students03（自带 README）
│   └── circle-10m-64-1.txt        Circle Antipode 实验（64 人 × 425 帧）
├── week01/                        ETH/UCY 数据格式梳理 + 五场景轨迹可视化
├── week02/                        Circle Antipode：轨迹图 + Detour-aware GCFV 微观模型
├── week03/                        TrajNet++：无交互、网格分辨率与池化规则对比
├── week04/                        NGSIM I-80：流量—密度基本图、时间窗口与计算方法对比
├── pyproject.toml / uv.lock       uv 环境定义
└── .python-version
```

## 环境

用 [uv](https://docs.astral.sh/uv/) 管理，Python 3.9（见 `.python-version`）。
week01 / week02 依赖：`matplotlib`、`numpy`；week03 的 TrajNet++ 实验依赖与运行说明见
[week03/README.md](week03/README.md) 和 [requirements-classroom.txt](week03/model/requirements-classroom.txt)。
week04 依赖 `numpy`、`pandas`、`matplotlib`，运行说明见 [week04/README.md](week04/README.md)。

```bash
uv sync --no-install-project
```

**`--no-install-project` 不能省。** `pyproject.toml` 里声明了 `[project.scripts]` 和
`uv_build` 构建后端，但仓库里没有 `src/datasets/__init__.py`，直接 `uv sync` 会在
「构建本项目」这一步失败。带上这个参数就只装依赖、跳过构建本项目。

---

## 每周工作

### week01 —— ETH/UCY 数据格式梳理 + 五场景轨迹可视化

- **做了什么**：把五个在范围内的场景的数据摸清楚（用哪个文件、什么格式、坑在哪），
  并为每个场景画一张轨迹图。
- **关键结论**：处理只需要 `obsmat.txt`（8 列、米、世界坐标）；五个场景帧步长 6 或 10 不一致，
  但有效采样率都是 0.4 s；速度列要用出厂值，自己差分因约定不同会有 7%~30% 的相对误差。
- **产物**：[week01/results/figures/](week01/results/figures/) 下 5 场景 × 明/暗 = 10 张 PNG。
- **入口**：`week01/plot_trajectories.py` ｜ 完整说明（含数据集格式）：[week01/README.md](week01/README.md)

### week02 —— Circle Antipode 的 Detour-aware GCFV 模型

- **做了什么**：为圆环正对径穿越场景建立可解释的微观行人模型。三层结构 —— 路线/绕行决策
  （秒级）+ 期望方向 + GCFV 局部运动（0.04 s 级），绕行代价里的冲突延误 `ΔT` 用 GCFV
  自己的速度子模型估计，使决策层与运动层同源；配一个不做绕行决策的 baseline 做对照。
- **关键结论**：到达时间、速度分布、终点位置都与实验对得上，绕行决策层确实起作用
  （绕行人数 12 vs baseline 7）；但**绕行程度远低于实验**（12 人 vs 42 人），
  根因是局部避让太短程（仿真里人均最小间隙 −0.35 m，实验只有 −0.07 m）。
  参数标定留到后续周。
- **产物**：[week02/results/](week02/results/) 下 5 张图 + 2 份轨迹 CSV + `metrics.json`。
- **入口**：`week02/model/detour_gcfv/run.py` ｜ 完整说明（模型思路、代码逻辑、参考文献）：
  [week02/README.md](week02/README.md)

### week03 —— TrajNet++ 邻域与池化实验

- **做了什么**：在圆形对穿课堂数据上，以 TrajNet++ social LSTM 为参照，对比无交互
  vanilla LSTM、观察范围不变的 `8×8` 细网格，以及同格邻居特征求和池化。
  四个模型使用相同数据划分、8 帧历史、12 帧预测和随机种子，均训练 10 轮。
- **关键结论**：无交互模型在四个 LSTM 中表现最好，测试集 ADE/FDE 为 **0.5498 / 1.1583**，
  相比 social baseline 分别下降约 **25.7% / 19.0%**；细网格与求和池化均未改善测试结果。
  四个 LSTM 都弱于匀速外推；结论仅适用于当前小样本与训练配置，不能推广为邻居信息无用。
  指标采用换算后的坐标单位，尚未确认可标为米。
- **产物**：[week03/results/](week03/results/) 下 4 个最终模型、配置与 val/test 指标 JSON、
  `summary.csv`，以及单模型轨迹图和综合对比图。
- **入口**：`week03/model/run_classroom.py`、`week03/model/run_classroom_sum_pooling.py` ｜
  完整说明（实验设计、评价口径、结果与限制）：[week03/README.md](week03/README.md)

### week04 —— NGSIM I-80 车辆轨迹流量—密度分析

- **做了什么**：固定 I-80 东向车道 1 的 200–300 m 路段，完成轨迹范围筛选与质量检查，
  按 Edie 时空区域定义计算密度和流量，比较 **5、10、20、30、60 秒**五种聚合窗口；
  同时对照逐帧路段平均法与断面计数估计法，并分析不同车道、路段的基本图差异。
- **关键结论**：主范围各窗口总体呈正相关，短窗口保留更多波动，长窗口使点云范围收窄。
  逐帧法与 Edie 接近；断面法在短窗口下受过车计数量化影响更明显，与 Edie 的流量平均绝对差
  从 5 秒窗口约 **243 veh/h** 降至 60 秒窗口约 **23 veh/h**。这些是方法差异，不能视作真值误差；
  断面无过车也不等于路段无车。车道 2、4 在观测时段呈负相关并伴随低速，不违反 `q=kv`，
  但拥堵、排队波与换道等解释尚未完成因果验证。
- **产物**：[week04/results/](week04/results/) 下 4 张对比图、360 条 Edie 窗口结果、
  1,080 条三方法窗口记录、筛选轨迹、范围配置与质量检查说明；辅助结果及历史分析见
  [week04/archive/](week04/archive/)。
- **入口**：`week04/code/run_analysis.py`；在仓库根目录运行
  `python week04/code/run_analysis.py --t 5 10 20 30 60` 可重建主结果。完整说明：
  [week04/README.md](week04/README.md)。

---

## 数据集在哪

| 数据集 | 位置 | 格式说明 |
|---|---|---|
| ETH（2 场景） | [datasets/ETH/](datasets/ETH/) | [week01/README.md](week01/README.md#一数据集说明) |
| UCY（3 场景） | [datasets/UCY/](datasets/UCY/) | 同上 |
| Circle Antipode | [datasets/circle-10m-64-1.txt](datasets/circle-10m-64-1.txt) | [week02/README.md](week02/README.md#三参考文献与开源实现) |
| NGSIM I-80（车辆轨迹） | [week04/data/](week04/data/) | [使用说明](week04/data/使用说明.txt) · [来源与校验元数据](week04/data/source_and_checks.json) |

各数据集的原始出处、署名与许可见对应目录的 README 或来源说明。
