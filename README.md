# 交通流与轨迹建模：每周实验

本仓库汇集六周的交通流与轨迹研究工作，涵盖数据可视化、微观行人建模、轨迹预测、
流量—密度分析、车辆跟驰仿真和窄路人车交互。各周工作按同一层级组织，详细方法、参数、结果和复现步骤见对应周的 README。

## 工作索引

| 周次 | 主题 | 主要内容 | 详细说明 |
|---|---|---|---|
| week01 | ETH/UCY 数据与可视化 | 数据格式、采样与速度字段核对，五场景轨迹绘制 | [week01/README.md](week01/README.md) |
| week02 | 微观行人模型 | Circle Antipode 场景的绕行决策与 GCFV 运动模型 | [week02/README.md](week02/README.md) |
| week03 | 神经网络轨迹预测 | TrajNet++ 无交互、网格分辨率与池化规则对比 | [week03/README.md](week03/README.md) |
| week04 | 流量—密度基本图 | NGSIM 轨迹的时间窗口、测量方法与车道对比 | [week04/README.md](week04/README.md) |
| week05 | 车辆跟驰模型 | OVM、FVDM、IDM 的车队、人工双车与实测双车实验 | [week05/README.md](week05/README.md) |
| week06 | 窄路与向心人车交互 | 直路、缩窄道路和圆周向心穿越的策略对照与灵敏度分析 | [week06/README.md](week06/README.md) |

## 每周工作

### week01 · ETH/UCY 数据与轨迹可视化

- **实验内容**：梳理 ETH/UCY 五个场景的文件格式、坐标单位、采样间隔和速度字段，绘制轨迹图。
- **主要发现**：五场景帧编号步长不同，但有效采样间隔均为 0.4 s；原始速度列与位置差分的约定不同，使用时需要区分。
- **结果与文档**：[轨迹图](week01/results/figures/)包含五场景明、暗两套共 10 张 PNG；数据说明与运行方法见 [本周 README](week01/README.md)。

### week02 · Circle Antipode 微观行人模型

- **实验内容**：建立路线与绕行决策、期望方向和 GCFV 局部运动三层模型，与不做绕行决策的 baseline 及实测轨迹比较。
- **主要发现**：绕行决策增加了绕行人数，但仍明显低于实验（模型 12 人、baseline 7 人、实验 42 人）；局部避让与行人间隙仍需改进。
- **结果与文档**：[仿真结果](week02/results/)包含轨迹图、两份轨迹 CSV 和指标 JSON；模型设计与运行方法见 [本周 README](week02/README.md)。

### week03 · TrajNet++ 邻域与池化实验

- **实验内容**：固定数据划分、8 帧历史、12 帧预测和 10 轮训练，对比 social baseline、无交互模型、细网格与同格求和池化。
- **主要发现**：无交互模型的测试 ADE/FDE 比 social baseline 低约 25.7% / 19.0%，但四个 LSTM 均弱于匀速外推；结论限于当前小样本与训练配置。
- **结果与文档**：[预测结果](week03/results/)包含四个最终模型、指标、汇总表与轨迹对比图；评价口径和运行方法见 [本周 README](week03/README.md)。

### week04 · NGSIM 流量—密度基本图

- **实验内容**：固定 I-80 东向车道 1 的 200–300 m 路段，比较五种时间窗口，以及 Edie、逐帧路段平均、断面计数三种方法，并对照其他车道。
- **主要发现**：短窗口保留更多波动，长窗口收窄点云范围；逐帧法与 Edie 接近，断面法短窗差异较大。部分车道呈负相关并伴随低速，原因尚需进一步验证。
- **结果与文档**：[基本图结果](week04/results/)包含四张对比图、窗口数据、筛选轨迹和质量检查；计算口径与运行方法见 [本周 README](week04/README.md)。

### week05 · OVM、FVDM 与 IDM 跟驰模型

- **实验内容**：比较三种模型的环道车队、四种人工双车场景与三组 NGSIM 实测车辆对，同时评价轨迹误差、净间距、仿真完成情况并复核积分步长。
- **主要发现**：微小扰动可形成走停波；IDM 在所选实测案例共同有效时段内误差最低，但部分场景提前触发负速度。拟合误差与物理合理性需分别评价，不能据此给出普遍模型排名。
- **结果与文档**：[车队](week05/platoon_experiments/results/)、[人工双车](week05/two_vehicle_experiments/artificial/results/)和[实测双车](week05/two_vehicle_experiments/ngsim/results/)分别保存图表、指标与报告；详见 [实验结论](week05/实验结论.md) 和 [本周 README](week05/README.md)。

### week06 · 窄路与向心人车交互模型

- **实验内容**：以统一运动方程和能力参数描述人车，比较直路、局部缩窄道路及圆周向心穿越中的统一规则、社会力基线和修正策略；向心场景从圆周出发到达对径点，开展多方向交互与失败对照。
- **主要发现**：所设直路安全断面下限为 2.8 m，位置与侧移能力也影响通行；向心场景中，默认 4 人 4 车的三种策略均僵持，单人单车的规则模型与修正版可完成。模型未经实测标定，主体朝向固定，尚不包含真实车辆转向。
- **结果与文档**：[仿真结果](week06/results/)保存 668 次运行（含 120 次向心实验及重复配置，非独立样本）；[动态主页](week06/index.html)提供离线回放，[文档导航](week06/docs/index.html)汇集[实验报告](week06/docs/REPORT.md)、[向心实验](week06/docs/CIRCLE.md)与[灵敏度分析](week06/docs/SENSITIVITY.md)，运行方法见 [本周 README](week06/README.md)。

## 目录与数据

```text
pedestrian_dataset/
├── week01/                 数据梳理与可视化
├── week02/                 微观行人模型
├── week03/                 神经网络轨迹预测
├── week04/                 流量—密度基本图
├── week05/                 车辆跟驰模型
├── week06/                 窄路与向心人车交互模型
├── datasets/               ETH、UCY、Circle Antipode 数据
├── pyproject.toml          基础 Python 依赖
├── uv.lock                 基础依赖锁定文件
└── .python-version         Python 版本配置
```

各周 README 是对应实验的主文档；代码和产物位于当周目录，具体结构按实验组织。
结果通常保存在 `results/`，历史分析与辅助材料保存在相应归档目录。输入数据保持只读，
复用其他周的数据时在周文档中说明。

| 数据 | 保存位置 | 说明 |
|---|---|---|
| ETH / UCY | [ETH](datasets/ETH/) · [UCY](datasets/UCY/) | 五场景数据格式见 [week01](week01/README.md) |
| Circle Antipode | [圆环对穿数据](datasets/circle-10m-64-1.txt) | 实验与模型说明见 [week02](week02/README.md) |
| circle_classroom | 入口与划分见 [week03](week03/README.md) | TrajNet++ 课堂实验数据 |
| NGSIM I-80 | [week04/data/](week04/data/) | [来源说明](week04/data/使用说明.txt)；week05 实测双车实验只读复用 |
| 人车交互仿真场景 | [week06/configs/](week06/configs/) · [直路场景](week06/pvsim/scenarios.py) · [向心场景](week06/pvsim/radial.py) | 人工配置与种子生成，不依赖实测轨迹；参数见 [参数表](week06/docs/PARAMETERS.md) |

week05 的 NPZ/NPY 时间序列在本地生成，已加入 Git 忽略规则。数据来源、单位、
质量限制与使用条件以对应数据说明和周文档为准。

## 环境与复现

不同实验需要的依赖不同，按目标周的说明安装和运行。

| 周次 | 依赖与运行说明 |
|---|---|
| week01 | `numpy`、`matplotlib`；见 [运行说明](week01/README.md) |
| week02 | `numpy`、`matplotlib`；见 [运行说明](week02/README.md) |
| week03 | [requirements-classroom.txt](week03/model/requirements-classroom.txt) 与 [运行说明](week03/README.md) |
| week04 | `numpy`、`pandas`、`matplotlib`；见 [运行说明](week04/README.md) |
| week05 | [requirements.txt](week05/requirements.txt) 与 [运行说明](week05/README.md) |
| week06 | Python ≥ 3.9，核心仿真仅用标准库；[绘图依赖](week06/requirements-plot.txt)、[文档渲染依赖](week06/requirements-docs.txt)按需安装，命令见 [运行说明](week06/README.md) |

仓库根目录的基础环境使用 uv 管理，Python 版本见 `.python-version`。安装基础依赖：

```bash
uv sync --no-install-project
```

该命令跳过本项目的包构建，仅安装根目录声明的依赖；其他周所需依赖需按各自说明补充。
运行前先确认周文档指定的工作目录：脚本路径可按需加上 `weekNN/` 前缀；
week06 的 `python -m pvsim ...` 命令需先进入 `week06/` 目录执行。
