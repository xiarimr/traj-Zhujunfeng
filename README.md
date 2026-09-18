# 行人轨迹数据集与建模实验

行人轨迹研究用的原始数据集，以及基于这些数据逐周推进的工作。

数据分两套：**ETH / UCY** 五场景基准（行人轨迹预测最常用的公开数据），
以及**北京交通大学 Circle Antipode（圆环正对径穿越）实验**（64 人从半径 10 m 的圆环出发、
同时走向各自的正对径点）。

---

## 仓库逻辑

三条约定，后面每周都按它走：

1. **原始数据只放在 `datasets/`，只读。** 不在原目录里改数据、不把中间结果混进去；
   读取路径一律从代码里指向 `datasets/`。
2. **每周一个 `weekNN/` 目录，内部固定三块**：

   ```
   weekNN/
   ├── README.md    这一周做了什么、怎么跑、结论是什么
   ├── <代码>       当周的可执行代码（目录名按内容定，如 model/）
   └── results/     当周的产物：图、轨迹、指标 JSON
   ```

   代码只读 `datasets/`、只写自己 `results/`，跨周不互相依赖。
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
├── pyproject.toml / uv.lock       uv 环境定义
└── .python-version
```

## 环境

用 [uv](https://docs.astral.sh/uv/) 管理，Python 3.9（见 `.python-version`）。
依赖：`matplotlib`、`numpy`。

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

---

## 数据集在哪

| 数据集 | 位置 | 格式说明 |
|---|---|---|
| ETH（2 场景） | [datasets/ETH/](datasets/ETH/) | [week01/README.md](week01/README.md#一数据集说明) |
| UCY（3 场景） | [datasets/UCY/](datasets/UCY/) | 同上 |
| Circle Antipode | [datasets/circle-10m-64-1.txt](datasets/circle-10m-64-1.txt) | [week02/README.md](week02/README.md#三参考文献与开源实现) |

各数据集的原始出处、署名与许可见数据集目录下自带的 README。
