"""命令行入口：跑主模型 / baseline1，落轨迹 CSV 与指标 JSON。

    python week02/model/detour_gcfv/run.py                 # 两个模型都跑
    python week02/model/detour_gcfv/run.py --model main    # 只跑主模型
    python week02/model/detour_gcfv/run.py --v0-scale 1.4  # 把 v⁰ 整体缩到文献水平

产物落在 week02/results/out/。输出的轨迹 CSV **刻意沿用实验文件的格式**
（`行人ID 帧号 x y`，厘米，空格分隔，无表头），两个文件可以直接互换使用
（比如丢给 week02/model/plot_circle.py 那套画法）。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

# 本仓库的习惯是 `python weekNN/xxx.py` 直接跑脚本，那样子目录不是一个包，相对导入会失败。
# 把 week02 挂进 sys.path 后按绝对名导入，直接跑和 `python -m detour_gcfv.run` 都能工作。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from detour_gcfv.data import CM_PER_M, load_experiment  # noqa: E402
from detour_gcfv.metrics import compare_summaries, evaluate  # noqa: E402
from detour_gcfv.paths import OUT_DIR  # noqa: E402
from detour_gcfv.sim import SimConfig, run  # noqa: E402


def save_trajectories(path: Path, frames: np.ndarray, positions: np.ndarray) -> None:
    """按实验文件的格式写轨迹：`行人ID 帧号 x y`，厘米。"""
    lines = []
    for i in range(positions.shape[0]):
        for k, frame in enumerate(frames):
            x, y = positions[i, k] * CM_PER_M
            lines.append(f"{i + 1} {int(frame)} {x:.3f} {y:.3f}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Detour-aware GCFV 仿真")
    parser.add_argument("--model", choices=("main", "baseline1", "both"), default="both")
    parser.add_argument("--steps", type=int, default=None,
                        help="仿真步数，默认 = 实验帧数 − 1（正好覆盖同一段时间）")
    parser.add_argument("--v0-scale", type=float, default=1.0, help="v⁰ 整体缩放系数")
    parser.add_argument("--seed", type=int, default=20260918)
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args()

    exp = load_experiment()
    args.out.mkdir(parents=True, exist_ok=True)

    wanted = ("main", "baseline1") if args.model == "both" else (args.model,)
    results = {}
    for name in wanted:
        config = SimConfig(steps=args.steps, use_detour=(name == "main"),
                           v0_scale=args.v0_scale, seed=args.seed)
        started = time.perf_counter()
        results[name] = run(exp, config)
        elapsed = time.perf_counter() - started
        n_steps = results[name].positions.shape[1] - 1
        print(f"[{name}] {results[name].label}：{n_steps} 步耗时 {elapsed:.1f} s")

    for name, result in results.items():
        path = args.out / f"trajectories_{name}.csv"
        save_trajectories(path, exp.frames, result.positions)
        print(f"  轨迹 -> {path.name}")

    # 两组模型都与实验同口径比较，所以参照轨迹一律是实验
    exp_metrics = evaluate(exp.positions, exp, label="实验")
    sim_metrics = {
        name: evaluate(result.positions, exp, label=result.label)
        for name, result in results.items()
    }

    print()
    print(compare_summaries(exp_metrics, *sim_metrics.values()))

    payload = {"experiment": exp_metrics.summary(),
               "models": {name: m.summary() for name, m in sim_metrics.items()}}
    if "main" in results:
        routes = results["main"].routes
        payload["route_choice"] = {
            str(name): int((routes == name).sum()) for name in ("straight", "left", "right")
        }
    (args.out / "metrics.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n指标 -> {(args.out / 'metrics.json').name}")


if __name__ == "__main__":
    main()
