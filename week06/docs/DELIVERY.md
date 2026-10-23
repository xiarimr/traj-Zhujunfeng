# 文件与结果索引

从[README 首页](../README.md)阅读模型与规则，或打开[基础场景](../results/demo/replay.html)、[直路三模型](../results/benchmark/replay.html)、[失败修正](../results/failures/replay.html)的交互回放。

| 内容 | 入口 |
|---|---|
| 主要结果、圆环和失败修正分析 | [实验报告](REPORT.md) |
| 方程与假设 | [模型](MODEL.md) |
| 更新、终止与指标 | [规则](RULES.md) |
| 参数及取值范围 | [参数表](PARAMETERS.md) · [CSV](../parameters.csv) |
| 完整参数扫描 | [灵敏度结果](SENSITIVITY.md) |
| 668次单次指标与源码 | [综合记录](week06_人车交互模型与实验.md) |
| 360次统一规则 / 120次三模型对照 | [规则数据](../results/experiments/runs.csv) · [模型对照](../results/benchmark/runs.csv) |
| 48次社会力参数探索 / 11次失败修正 | [参数探索](../results/sfm_parameters/sfm_parameters.csv) · [失败修正](../results/failures/comparison.csv) |
| 28项测试日志 | [验证记录](../results/validation.txt) |
| 文件大小与校验值 | [清单](../MANIFEST.json) |

根目录的 index.html 是向心动态主页，README 是模型说明入口；其他 Markdown 收纳在 docs。[网页文档导航](index.html)将模型、规则、参数、实验和综合记录连接起来，每份 Markdown 都有同名 HTML，各页面提供章节目录与回放入口。交互回放及其模板、原始数据、图片和代码保留。源码在 pvsim，场景配置在 configs，测试在 tests。

修改 Markdown 后，在根目录执行 `python -m pip install -r requirements-docs.txt`（首次安装），再执行 `python -m pvsim.render_docs --root .` 更新 HTML；该命令不重新运行实验。

668次包括9个基础演示，可能重复正式实验配置，总运行次数不等于独立样本数。新增120次向心穿越，旧沿环结果已删除；参数尚未实测标定。

[向心动态主页](../index.html) · [向心实验说明及120次结果](CIRCLE.md)
