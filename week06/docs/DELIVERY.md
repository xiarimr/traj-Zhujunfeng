# 文件与结果索引

从[README 首页](../README.md)阅读模型与规则，或打开[基础场景](../results/demo/replay.html)、[三模型与圆环](../results/benchmark/replay.html)、[失败修正](../results/failures/replay.html)的交互回放。

| 内容 | 入口 |
|---|---|
| 主要结果、圆环和失败修正分析 | [实验报告](REPORT.md) |
| 方程与假设 | [模型](MODEL.md) |
| 更新、终止与指标 | [规则](RULES.md) |
| 参数及取值范围 | [参数表](PARAMETERS.md) · [CSV](../parameters.csv) |
| 完整参数扫描 | [灵敏度结果](SENSITIVITY.md) |
| 700次单次指标与源码 | [综合记录](week06_人车交互模型与实验.md) |
| 360次统一规则 / 270次三模型对照 | [规则数据](../results/experiments/runs.csv) · [模型对照](../results/benchmark/runs.csv) |
| 48次社会力参数探索 / 13次失败修正 | [参数探索](../results/sfm_parameters/sfm_parameters.csv) · [失败修正](../results/failures/comparison.csv) |
| 20项原项目测试日志 | [验证记录](../results/validation.txt) |
| 文件大小与校验值 | [清单](../MANIFEST.json) |

根目录只保留 README，其他 Markdown 收纳在 docs。静态报告 HTML 已删除，交互回放及其模板、原始数据、图片和代码保留。源码在 pvsim，场景配置在 configs，测试在 tests。

700次包括9个基础演示，可能重复正式实验配置，总运行次数不等于独立样本数。圆环使用周期展开坐标，参数尚未实测标定。
