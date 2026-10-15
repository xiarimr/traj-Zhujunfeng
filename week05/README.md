# 跟驰模型仿真实验

本仓库包含两块实验：**车队仿真**和**双车实验**。双车实验中的人工前车轨迹与 NGSIM 实测轨迹地位平等，分别运行、分别保存结果。

三个模型的特点、人工场景表现及与真实轨迹的比较见 [实验结论](实验结论.md)。

```text
week05/
├── README.md
├── requirements.txt
├── 论文/                            三篇参考论文
├── platoon_experiments/              一、车队仿真
│   ├── run_experiments.py            OVM、FVDM、IDM 环道车队
│   ├── README.md
│   └── results/                     图、统计摘要；data/ 为本地数组
└── two_vehicle_experiments/          二、双车实验
    ├── README.md
    ├── common.py                    三模型、积分、指标与公共绘图
    ├── artificial/                  人工设定前车速度
    │   ├── run_experiments.py
    │   ├── README.md
    │   ├── results/                 四场景的图、报告、指标
    │   └── archive/early_idm/        早期IDM双车实验及复现脚本
    └── ngsim/                       NGSIM实测前车轨迹
        ├── run_experiments.py
        ├── README.md
        └── results/                 三组车辆对的图、报告、指标
```

## 安装与运行

在仓库根目录运行：

```powershell
python -m pip install -r requirements.txt

# 一、三个模型的车队仿真
python platoon_experiments/run_experiments.py

# 二、双车实验：人工设定前车速度
python two_vehicle_experiments/artificial/run_experiments.py

# 二、双车实验：NGSIM 实测轨迹
python two_vehicle_experiments/ngsim/run_experiments.py
```

各脚本也可以从其他工作目录启动，默认结果路径均相对于脚本定位。`--output` 可以指定其他结果目录，`--dt` 调整积分步长。车队脚本另支持 `--model ovm`、`--model fvdm`、`--model idm` 单独运行。

NGSIM 默认读取仓库外的 `../week04/data/NGSIM_I80_20050413_1600-1615_SI.csv`，不复制或修改源数据；可用 `--source` 指定同结构文件。车队和人工双车实验不需要这份数据。

## 实验说明与结果

|实验|场景与参数|指标报告|
|---|---|---|
|车队仿真|[场景和参数](platoon_experiments/README.md)|[统计摘要](platoon_experiments/results/summary_all.json)|
|双车：人工前车轨迹|[场景和指标](two_vehicle_experiments/artificial/README.md)|[指标报告](two_vehicle_experiments/artificial/results/结果说明.md)|
|双车：NGSIM实测轨迹|[数据与方法](two_vehicle_experiments/ngsim/README.md)|[指标报告](two_vehicle_experiments/ngsim/results/实验报告.md)|

### 车队仿真

OVM 不稳定场景：小扰动逐渐放大并形成走停波。

![OVM车队：扰动放大](platoon_experiments/results/ovm_unstable.png)

OVM 稳定对照：增大间距后，扰动衰减。

![OVM车队：稳定对照](platoon_experiments/results/ovm_stable_control.png)

FVDM 与 IDM 环道车队：

![FVDM车队仿真](platoon_experiments/results/fvdm.png)

![IDM车队仿真](platoon_experiments/results/idm.png)

### 双车实验：人工前车轨迹

匀速、减速恢复、停车起步、短间距急刹四个场景；各场景轨迹见人工实验说明。

![人工双车实验对比](two_vehicle_experiments/artificial/results/comparison.png)

### 双车实验：NGSIM 实测轨迹

三组实测车辆对的位置误差、速度误差、最小净间距及失败情况；与人工实验并列。

![NGSIM双车实验对比](two_vehicle_experiments/ngsim/results/ngsim_comparison.png)

## 文件与版本管理

**直接阅读本页图片和各实验的 Markdown 报告即可。** 代码、PNG 图片、JSON统计摘要和论文保留在Git中。NPZ/NPY时间序列、Python缓存、论文提取材料和历史重复验证输出已加入 `.gitignore`，本地文件保留，不随仓库上传。

克隆仓库后不会自带NPZ文件；运行相应实验脚本即可在 `results/data/` 重新生成。已有PNG和报告可直接查看，不依赖NPZ。NGSIM重新运行还需要准备前述原始CSV文件。

双车图中的 **× 表示触发失败停止前的最后有效点**，不一定是碰撞位置。原始公式产生的碰撞、负速度或数值异常均记录在指标中，未静默裁剪。人工场景没有实测后车真值，真实轨迹误差为N/A；NGSIM场景计算相对实测后车的误差。

车队中的OVM采用无量纲论文设置，双车OVM采用有量纲的最优速度函数，不能将其数值直接混比。参数与复现范围详见各实验说明。
