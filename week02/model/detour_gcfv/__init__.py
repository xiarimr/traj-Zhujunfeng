"""Detour-aware GCFV 模型：圆环正对径穿越实验的微观行人仿真。

模块划分（设计文档 §10）：
    data      实验数据读取、初值 / 目标 / 逐人 v⁰
    geometry  椭圆几何、间隙距离、路线几何
    gcfv      Module C：GCFV 局部运动（主模型与 baseline 共用）
    route     Module A/B：路线选择与期望方向
    sim       仿真循环
    metrics   §13 的评估指标
    run       命令行入口
    compare   对比出图
"""

from .data import Experiment, load_experiment
from .gcfv import GCFVParams
from .route import RouteParams
from .sim import SimConfig, SimResult, run

__all__ = [
    "Experiment",
    "load_experiment",
    "GCFVParams",
    "RouteParams",
    "SimConfig",
    "SimResult",
    "run",
]
