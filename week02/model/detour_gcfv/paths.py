"""week02 的路径常量 —— 全部集中在这里，目录调整时只改这一个文件。

    week02/
        README.md                说明
        model/                   代码
        results/                 产物（图 + 轨迹 CSV + 指标）
        Detour_aware_GCFV.md     模型设计文档
        design-detour-gcfv.md    实现 spec
"""

from __future__ import annotations

from pathlib import Path

MODEL_DIR = Path(__file__).resolve().parent.parent      # week02/model
WEEK02_DIR = MODEL_DIR.parent                            # week02
REPO_ROOT = WEEK02_DIR.parent                            # 仓库根

# 原始数据统一放在仓库根的 datasets/ 下（ETH / UCY / circle 实验数据都在那里）
DATA_PATH = REPO_ROOT / "datasets" / "circle-10m-64-1.txt"

RESULTS_DIR = WEEK02_DIR / "results"
FIGURES_DIR = RESULTS_DIR / "figures"                    # 所有出图
OUT_DIR = RESULTS_DIR / "out"                            # 轨迹 CSV 与指标 JSON
