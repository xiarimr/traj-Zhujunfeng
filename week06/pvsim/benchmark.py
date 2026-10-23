from collections import defaultdict, Counter
from dataclasses import replace
from pathlib import Path
import json
import statistics
from .scenarios import corridor
from .simulation import simulate
from .social_force import make_policy, SocialForceParameters, SocialForcePolicy
from .domain import Settings
from .export import save_result, save_replay
from .experiments import mean, write_csv, wilson


POLICIES = ("reciprocal", "social_force", "sfm_guided")


def benchmark_designs():
    for w in (5, 4, 3.2, 2.9, 2.8, 2.6):
        yield "straight", w, corridor, {"width": w}
    for w in (3.2, 2.6):
        yield "bottleneck", w, corridor, {"width": w, "bottleneck": True}


def benchmark(directory, seeds=5, plots=False):
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    replay = []
    with (out / "runs.jsonl").open("w", encoding="utf-8") as log:
        for group, value, factory, params in benchmark_designs():
            for seed in range(seeds):
                scene = factory(seed=seed, settings=Settings(record_every=10), **params)
                for policy in POLICIES:
                    record = seed == 0 and group == "straight" and value in (5, 3.2, 2.8, 2.6)
                    result = simulate(scene, make_policy(policy), record=record)
                    m = result["metrics"]
                    row = {"group": group, "value": value, "seed": seed, "policy": policy,
                           "status": m["status"], "full_observation_success": m["status"] in ("completed", "sustained"),
                           "safety_margins_satisfied": m["safety_margins_satisfied"],
                           "completion_time_s": m["completion_time_s"], "observation_time_s": m["observation_time_s"],
                           "min_pair_gap_m": m["min_pair_gap_m"], "min_wall_gap_m": m["min_wall_gap_m"],
                           "collision_pairs": m["collision_pairs"], "boundary_violations": m["boundary_violations"],
                           "pair_passages": m["pair_passages"], "total_agent_waiting_s": m["total_agent_waiting_s"],
                           "effective_speed_planned_horizon_m_s": m["effective_speed_planned_horizon_m_s"],
                           "pair_passages_per_min_planned": m["pair_passages_per_min_planned"]}
                    rows.append(row)
                    if record:
                        slug = f"{group}_{value}_{policy}"
                        save_result(result, out / "trajectories" / slug)
                        label = f"直路 {value} m · {policy}"
                        replay.append((label, result))
                    log.write(json.dumps({"design": {"group": group, "value": value}, "result": dict(result, trace=[])}, ensure_ascii=False) + "\n")
            print(f"benchmark {group}={value}: {seeds} paired seeds x 3 policies", flush=True)
    groups = defaultdict(list)
    for row in rows:
        groups[(row["group"], row["value"], row["policy"])].append(row)
    summary = []
    for (group, value, policy), trials in groups.items():
        times = [r["completion_time_s"] for r in trials if r["completion_time_s"] is not None]
        successes = sum(r["full_observation_success"] for r in trials)
        lo, hi = wilson(successes, len(trials))
        summary.append({"group": group, "value": value, "policy": policy, "runs": len(trials),
                        "success_rate": successes / len(trials), "wilson_95_low": lo, "wilson_95_high": hi,
                        "safe_success_rate": sum(r["full_observation_success"] and r["safety_margins_satisfied"] for r in trials) / len(trials),
                        "completion_mean_s": mean(times), "completion_sd_s": statistics.stdev(times) if len(times)>1 else None,
                        "collision_runs": sum(r["collision_pairs"] > 0 for r in trials),
                        "boundary_violation_runs": sum(r["boundary_violations"] > 0 for r in trials),
                        "min_pair_gap_m": min(r["min_pair_gap_m"] for r in trials),
                        "min_wall_gap_m": min(r["min_wall_gap_m"] for r in trials),
                        "mean_pair_passages": mean([r["pair_passages"] for r in trials]),
                        "mean_effective_speed_m_s": mean([r["effective_speed_planned_horizon_m_s"] for r in trials]),
                        "mean_passages_per_min": mean([r["pair_passages_per_min_planned"] for r in trials]),
                        "status_counts": json.dumps(dict(Counter(r["status"] for r in trials)))})
    write_csv(out / "runs.csv", rows)
    write_csv(out / "summary.csv", summary)
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    save_replay(replay, out / "replay.html")
    if plots:
        benchmark_plots(summary, out)
    return rows, summary


def sfm_parameter_sweep(directory):
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for A in (2, 4, 8, 16):
        for B in (.4, .8, 1.5, 2.5):
            for seed in (100, 101, 102):
                result = simulate(corridor(width=3.2, pedestrians=1, vehicles=1, seed=seed),
                                  SocialForcePolicy(SocialForceParameters(A=A, B=B)), record=False)
                m = result["metrics"]
                rows.append({"A_m_s2": A, "B_m": B, "seed": seed, "status": m["status"],
                             "completion_time_s": m["completion_time_s"], "min_pair_gap_m": m["min_pair_gap_m"],
                             "min_wall_gap_m": m["min_wall_gap_m"], "safe": m["safety_margins_satisfied"]})
    write_csv(out / "sfm_parameters.csv", rows)
    (out / "sfm_parameters.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    return rows


def failures(directory):
    out = Path(directory)
    cases = [
        ("width_wait", "空间不足：2.6 m 等待", corridor(width=2.6), "reciprocal", None),
        ("width_repair", "扩大宽度：2.8 m 通过", corridor(width=2.8), "reciprocal", None),
        ("fixed_center", "车居中：2.9 m 阻塞", corridor(width=2.9, centered_vehicle=True), "reciprocal", None),
        ("move_vehicle", "允许车侧移：2.9 m 通过", corridor(width=2.9, centered_vehicle=True, vehicle_lateral_speed=.2), "reciprocal", None),
        ("excess_speed", "制动距离不足：初速 12 m/s", corridor(width=3.2, initial_gap=5, vehicle_speed=12, pedestrians=1, vehicles=1, speed_jitter=0), "reciprocal", None),
        ("speed_repair", "只降低初始/期望车速：1.5 m/s", corridor(width=3.2, initial_gap=5, vehicle_speed=1.5, pedestrians=1, vehicles=1, speed_jitter=0), "reciprocal", None),
        ("sfm_short", "SFM：短作用距离导致风险", corridor(width=5), "social_force", SocialForceParameters(A=4, B=.8)),
        ("sfm_tuned_wide", "SFM：扩大作用范围，5 m 通过", corridor(width=5), "social_force", None),
        ("sfm_narrow", "SFM：3.2 m 窄路软边界不足", corridor(width=3.2), "social_force", None),
        ("sfm_partial", "部分修正：选边与制动，仍可能僵持", corridor(width=3.2), "sfm_guided_ungated", None),
        ("sfm_full", "完整修正：解除已消除的冲突力", corridor(width=3.2), "sfm_guided", None),
    ]
    replay, rows = [], []
    for slug, label, scene, policy, params in cases:
        result = simulate(scene, make_policy(policy, params))
        save_result(result, out / slug)
        replay.append((label, result))
        rows.append({"case": slug, "label": label, "policy": policy, **{k: result["metrics"][k] for k in
                    ("status", "completion_time_s", "collision_pairs", "boundary_violations", "pair_passages",
                     "min_pair_gap_m", "min_wall_gap_m", "total_agent_waiting_s", "safety_margins_satisfied")}})
    write_csv(out / "comparison.csv", rows)
    (out / "comparison.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    save_replay(replay, out / "replay.html")
    return rows


def benchmark_plots(summary, out):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    colors = {"reciprocal": "#197b92", "social_force": "#c46e24", "sfm_guided": "#8066ad"}
    names = {"reciprocal": "Shared rules", "social_force": "SFM baseline", "sfm_guided": "SFM + rules + release"}
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.4), constrained_layout=True)
    for policy in POLICIES:
        straight = sorted([r for r in summary if r["group"] == "straight" and r["policy"] == policy], key=lambda r:r["value"])
        kw = dict(color=colors[policy], marker="o", label=names[policy])
        axes[0].plot([r["value"] for r in straight], [r["success_rate"] for r in straight], **kw)
        valid = [r for r in straight if r["completion_mean_s"] is not None]
        axes[1].plot([r["value"] for r in valid], [r["completion_mean_s"] for r in valid], **kw)
    axes[0].set(title="A  Straight-road completion", ylabel="Completed fraction", ylim=(-.05,1.08))
    axes[1].set(title="B  Conditional completion time", ylabel="Mean time among completed runs (s)")
    for a in axes.flat:
        a.set_xlabel("Road width (m)")
        a.grid(axis="y", alpha=.2)
        a.axvline(2.8, ls="--", lw=1, color="#667c8b")
        a.spines['top'].set_visible(False)
        a.spines['right'].set_visible(False)
    axes[0].legend(frameon=False, fontsize=8, loc="lower right")
    fig.suptitle("Matched initial states and limits | Uncalibrated social-force baseline", fontsize=14)
    fig.savefig(Path(out) / "model_comparison.png", dpi=180)
    fig.savefig(Path(out) / "model_comparison.svg")
    plt.close(fig)
