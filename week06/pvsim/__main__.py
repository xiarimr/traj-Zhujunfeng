import argparse
from pathlib import Path
from .scenarios import corridor, load_scenario
from .simulation import simulate
from .export import save_result, save_replay
from .experiments import run_sweep, make_plots
from .social_force import make_policy
from .benchmark import benchmark, sfm_parameter_sweep, failures
from .radial_experiments import run_radial


def demos(out):
    definitions = [
        ("wide", "5.0 m · 3 人 / 2 车", dict(width=5)),
        ("threshold", "2.8 m · 安全宽度临界值", dict(width=2.8)),
        ("clearance_wait", "2.6 m · 几何可放下 / 安全间距不足", dict(width=2.6)),
        ("physical_limit", "2.4 m · 几何下限 / 等待", dict(width=2.4)),
        ("bottleneck_pass", "5 → 3.2 → 5 m · 缩窄道路通过", dict(width=3.2, bottleneck=True)),
        ("bottleneck_wait", "5 → 2.6 → 5 m · 缩窄道路等待", dict(width=2.6, bottleneck=True)),
        ("center_fixed", "2.9 m · 车辆居中且不侧移", dict(width=2.9, centered_vehicle=True)),
        ("center_mobile", "2.9 m · 允许车辆小幅靠边", dict(width=2.9, centered_vehicle=True, vehicle_lateral_speed=.2)),
        ("late_conflict", "3.2 m · 近距离相遇 / 先停再绕", dict(width=3.2, initial_gap=12, lateral_speed=.15)),
    ]
    results = []
    for slug, label, params in definitions:
        result = simulate(corridor(**params))
        save_result(result, out / slug)
        results.append((label, result))
        print(f"{slug}: {result['metrics']['status']}", flush=True)
    save_replay(results, out / "replay.html")
    return results


def main():
    parser = argparse.ArgumentParser(description="Unified pedestrian-vehicle interaction simulator")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("run", "demo", "sweep", "benchmark", "failures", "sfm-sweep", "circle", "all"):
        p = sub.add_parser(command)
        p.add_argument("--out", type=Path, default=Path("results"))
        if command == "run":
            p.add_argument("--config", type=Path, default=Path("configs/default.json"))
            p.add_argument("--policy", choices=("reciprocal", "social_force", "sfm_guided", "sfm_guided_ungated"), default="reciprocal")
        if command in ("sweep", "benchmark", "circle", "all"):
            p.add_argument("--seeds", type=int, default=5)
            p.add_argument("--plots", action="store_true", help="Requires matplotlib and numpy")
    args = parser.parse_args()
    if args.command == "run":
        result = simulate(load_scenario(args.config), make_policy(args.policy))
        save_result(result, args.out)
        save_replay([(result["scenario"]["name"], result)], args.out / "replay.html")
        print(result["metrics"])
    if args.command in ("demo", "all"):
        demos(args.out / "demo" if args.command == "all" else args.out)
    if args.command in ("sweep", "all"):
        directory = args.out / "experiments" if args.command == "all" else args.out
        rows, summary = run_sweep(directory, args.seeds)
        if args.plots:
            make_plots(rows, summary, directory)
        print(f"Saved {len(rows)} runs to {directory}")
    if args.command in ("benchmark", "all"):
        directory = args.out / "benchmark" if args.command == "all" else args.out
        benchmark(directory, args.seeds, args.plots)
    if args.command in ("sfm-sweep", "all"):
        sfm_parameter_sweep(args.out / "sfm_parameters" if args.command == "all" else args.out)
    if args.command in ("failures", "all"):
        failures(args.out / "failures" if args.command == "all" else args.out)
    if args.command in ("circle", "all"):
        run_radial(args.out / "circle_crossing" if args.command == "all" else args.out, args.seeds)


if __name__ == "__main__":
    main()
