# 行人轨迹数据集与建模实验

行人轨迹预测最常用的 **ETH / UCY** 五场景基准，加上一套 **Circle Antipode**（圆环正对径穿越）
实验数据，以及基于这些数据的每周处理工作。

## 目录结构

```
pedestrian_dataset/
├── datasets/                      原始数据，只读
│   ├── ETH/                       seq_eth、seq_hotel（自带 README）
│   ├── UCY/                       zara01、zara02、students03（自带 README）
│   └── circle-10m-64-1.txt        Circle Antipode 实验（64 人 × 425 帧）
├── week01/                        ETH/UCY 五场景轨迹可视化
│   ├── README.md
│   ├── plot_trajectories.py
│   └── results/figures/           10 张 PNG
├── week02/                        Circle Antipode：轨迹图 + Detour-aware GCFV 模型
│   ├── README.md
│   ├── Detour_aware_GCFV.md       模型设计文档
│   ├── design-detour-gcfv.md      实现 spec
│   ├── model/                     代码
│   └── results/                   图 + 轨迹 CSV + 指标 JSON
├── pyproject.toml / uv.lock       uv 环境定义
└── .python-version
```

每周的目录都按 **README + 代码 + results** 三块组织；产物一律落在本周的 `results/` 下，
原始数据一律只放在 `datasets/` 下，代码只读不写。

## 环境

用 [uv](https://docs.astral.sh/uv/) 管理，Python 3.9（见 `.python-version`）。
依赖：`matplotlib`、`numpy`。

```bash
uv sync --no-install-project
```

**`--no-install-project` 不能省。** `pyproject.toml` 里声明了 `[project.scripts]` 和
`uv_build` 构建后端，但仓库里没有 `src/datasets/__init__.py`，直接 `uv sync` 会在
「构建本项目」这一步失败。带上这个参数就只装依赖、跳过构建本项目。

## 每周工作

| 周次 | 内容 | 入口 |
|---|---|---|
| [week01](week01/) | ETH/UCY 五场景轨迹可视化（5 场景 × 明/暗 = 10 张图） | `.venv/Scripts/python.exe week01/plot_trajectories.py` |
| [week02](week02/) | Circle Antipode 轨迹图 + Detour-aware GCFV 微观行人模型与实验对照 | `.venv/Scripts/python.exe week02/model/detour_gcfv/run.py` |

各周的具体用法、产出、结论见各自的 README。

---

# 数据集说明

## 最小用法（先看这个）

**ETH/UCY 的所有数据处理只走 `obsmat.txt`。** 五个场景都自带这个文件，格式一致，单位米：

```
帧号  行人ID  pos_x  pos_z  pos_y  v_x  v_z  v_y
```

读进来 → 按 ID 分组 → 组内按帧号排序 → 取 `(帧号, x, y)`，就够了
（**`pos_y` 是下标 4**；`pos_z`、`v_z` 恒为 0，不用管）。

**不需要**碰 `annotation.vsp`、`H.txt`，也不需要任何 4 列格式 —— 那些是别的分支，
本仓库范围内用不到。下面各节按需查就行。

## 一、在范围内的场景

只处理以下 **5 个**场景；其余子目录（`students01`、`uni_examples`、`arxiepiskopi`、`zara03`）一律不动。
其中 `zara03` 不在标准评测集里，且只有 4 列格式，已移出范围（文件保留，不删）。

| 场景 | 路径 | 帧步长 | 起始帧 | 记录数 | 行人数 | 时长 | x 范围 (m) | y 范围 (m) |
|------|------|-------|--------|--------|--------|------|-----------|-----------|
| `seq_eth` | `datasets/ETH/seq_eth/obsmat.txt` | **6** | 780 | 8908 | 360 | 774 s | [-7.45, 13.87] | [-3.27, 13.29] |
| `seq_hotel` | `datasets/ETH/seq_hotel/obsmat.txt` | 10 | 1 | 6544 | 390 | 723 s | [-3.29, 4.38] | [-10.25, 4.32] |
| `zara01` | `datasets/UCY/zara01/obsmat.txt` | 10 | 1 | 5024 | 148 | 361 s | [-7.35, 6.36] | [4.98, 20.73] |
| `zara02` | `datasets/UCY/zara02/obsmat.txt` | 10 | 7 | 9537 | 204 | 421 s | [-8.36, 6.43] | [-10.66, 5.25] |
| `students03` | `datasets/UCY/students03/obsmat.txt` | 10 | 1 | 21846 | 428 | 216 s | [-8.10, 9.51] | [-8.22, 9.52] |

五个场景**各在自己的世界坐标系里**，坐标系互不相通，不要跨场景合并坐标。

## 二、文件格式

### `obsmat.txt` —— 世界坐标，8 列（唯一要用的格式）

- **行序不统一，别依赖文件顺序**：`seq_eth`、`seq_hotel`、`students03` 按 `(帧, ID)` 排；
  `zara01`、`zara02` 按 `(ID, 帧)` 排。要按行人分组处理，自己按 ID 分组再排帧号。

### `circle-10m-64-1.txt` —— Circle Antipode 实验（5 列）

北京交通大学的圆环正对径穿越实验：64 名行人均匀站在半径 10 m 的圆环上，
同时出发走向自己正对面的位置。

```
行人ID  帧号  x  y  RUN_ID
```

- **列序与 Social-GAN 那套 `frame id x y` 相反**（第一列才是行人 ID）；
- **单位是厘米**（圆环半径约 1000 = 10 m），与 ETH/UCY 的米**不同**；
- **25 fps**（Δt = 0.04 s），也不是 ETH/UCY 的 0.4 s；
- 末帧 64 人全部静止（都已走到正对径点停下）。

详细的坑与统计见 [week02/README.md](week02/README.md#数据说明)。

### 其余文件（本仓库范围内都用不到）

- `datasets/UCY/zara03/crowds_zara03.txt`、`datasets/UCY/students03/students003.txt`：4 列格式 `帧 id x y`。
  其中 `students003.txt` 是**对齐已发表基准 `univ` 数值时**才需要换用的文件，
  它和 `students03/obsmat.txt` **不是同一套世界坐标**（见坑 4）。
- `annotation.vsp`（仅 UCY）：样条控制点，像素坐标。`H.txt` / `H-old.txt` / `H-cam.txt`：单应矩阵（见坑 3）。
- `groups.txt`（成组行人 ID）、`destinations.txt`（假定目的地）、`info.txt`（序列信息，含标注帧率 2.5 fps）、
  `map.xml` / `static.txt`（场景静态结构）、`reference.png` / `video.avi`（参考帧与视频）。

## 三、几个坑

ETH/UCY 的以下两条在 2026-09-11 实测确认过。

### 1. 帧步长不统一

帧步长（见 §一 表）五个场景不一致，所以 `seq_eth` 的帧号与其他序列不在同一时间单位上。
但**有效采样率都是 0.4 s** —— 两个 `info.txt` 都写明标注为 2.5 fps，
即相邻两采样点相隔 0.4 s，与帧步长是 6 还是 10 无关。换算一律走「帧差 ÷ 步长 × 0.4 s」，
不能拿帧差当时间，也不能按每帧 0.4 s 算。

**做法**：步长和起始帧都从数据本身读（对 `frame` 列求差分取众数），不要写死常量。

### 2. 速度列可以直接用

第 6、8 列就是位置列的有限差分，但各场景约定不同（`zara01`/`zara02` 后向、
`students03` 前向、两个 ETH 场景中心）。**别自己差分 —— 约定猜错就是 7%~30% 的相对误差，
直接用出厂列即可**，它每一行都有值（首样本前向、末样本后向）。

只有两种情况要自己重算：① 做过重采样／插值；② 多场景混在一起训练、且在意速度特征的
亚秒相位（三种约定的差分中心差半个到一个采样，最坏 0.4 s）。

### 3. 同名的 H 矩阵文件其实不是同一个变换

同一个场景下有多份 H 文件，内容确实不同。以 `zara01` 为例（2026-09-18 实测）：

- `H.txt` 末行 ≈ `(0, 0, 1)`，近似仿射；
- `H-cam.txt` 末行 `(-7.3e-08, -6.8e-07, 1.0005)`，含相机的透视项。

**两者不可互换**。不过本仓库范围内的处理都用不到它们 —— 只用 `obsmat.txt` 里现成的世界坐标。

### 4. `students003.txt` 与 `students03/obsmat.txt` 不是同一套坐标

两文件的点集无一重合、范围也不同，是两份独立标注，不是换原点。对齐 `univ` 基准数值时
才用前者，其余一律用 `obsmat.txt`。

---

数据集原始文件的署名与许可见 [datasets/ETH/README.md](datasets/ETH/README.md)
与 [datasets/UCY/README.md](datasets/UCY/README.md)。
