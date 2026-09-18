# week01：ETH / UCY 五场景轨迹可视化

把 ETH/UCY 基准里在范围内的 5 个场景各画一张轨迹图。

数据集本身（格式、场景清单、坑）见[仓库根 README](../README.md#数据集说明)。

## 运行

```bash
.venv/Scripts/python.exe week01/plot_trajectories.py                    # 默认出明/暗两套
.venv/Scripts/python.exe week01/plot_trajectories.py --mode light --dpi 150
```

参数：`--dpi`（默认 200）、`--mode light|dark|all`（默认 all）。

## 产出

[`results/figures/`](results/figures/) 下 **5 个场景 × 明/暗两套 = 10 张 PNG**，
每个场景单独一张大图，命名 `{场景名}_{模式}.png`。

## 图怎么读

每条行人一个细线轨迹。**线段颜色 = 该场景内的归一化时间**，取单一蓝色顺序色阶：
浅色 = 刚出场，深色 = 快离场。所以颜色渐变本身就是人流方向。底部色条标注了
「0 = 该场景首帧，1 = 末帧」。

示例 —— `students03` 能看出广场上的对角走廊和几条汇入/散出的人流；`seq_hotel`
能看出右侧 x∈[0,4] 的两条竖直行走带，以及左侧零星游走的轨迹。

## 目录

```
week01/
├── README.md              本文件
├── plot_trajectories.py   绘图脚本（数据路径读 datasets/，产物写 results/）
└── results/figures/       10 张 PNG
```
