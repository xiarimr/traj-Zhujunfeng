"""Paired-seed sensitivity runs; uncompleted times are censored (None), not zero."""
from dataclasses import replace
from collections import defaultdict, Counter
from pathlib import Path
import csv
import json
import math
import statistics
from .domain import Settings
from .scenarios import corridor
from .simulation import simulate


def designs():
    for width in (5, 4.5, 4, 3.5, 3.2, 3, 2.9, 2.8, 2.7, 2.6, 2.4):
        yield "width", width, {"width": width}, {}
    for width in (3.4, 3.2, 3, 2.9, 2.8, 2.7, 2.6, 2.4):
        yield "bottleneck", width, {"width": width, "bottleneck": True}, {}
    for value in (1.5, 3, 4.5, 6):
        yield "vehicle_speed", value, {"vehicle_speed": value}, {}
    for value in (.15, .3, .7, 1.0):
        yield "pedestrian_lateral_speed", value, {"lateral_speed": value}, {}
    for value in (0, .1, .2, .3, .4):
        yield "lateral_clearance", value, {"width": 2.8}, {"lateral_clearance": value}
    for value in (12, 20, 28, 34):
        yield "initial_gap", value, {"initial_gap": value}, {}
    for value in (.45, .6, .75, .9):
        yield "pedestrian_width", value, {"width": 3.0, "pedestrian_width": value}, {}
    for value in (1.6, 1.8, 2.0, 2.2):
        yield "vehicle_width", value, {"width": 3.0, "vehicle_width": value}, {}
    for value in (1, 2, 3, 5):
        yield "pedestrian_count", value, {"pedestrians": value}, {}
    for value in (.1, .05, .025):
        yield "dt", value, {"width": 2.9}, {"dt": value}
    for value in (.1, 1, 10):
        yield "mass_scale", value, {}, {}
        # This is a negative-control parameter: mass only changes metadata.
    yield "alignment", "edge_fixed", {"width": 2.9}, {}
    yield "alignment", "center_fixed", {"width": 2.9, "centered_vehicle": True}, {}
    yield "alignment", "center_mobile", {"width": 2.9, "centered_vehicle": True, "vehicle_lateral_speed": .2}, {}
    for width in (2.7, 2.8, 2.9, 3.2, 4.0):
        for speed in (1.5, 3, 4.5):
            yield "width_x_speed", f"{width}:{speed}", {"width": width, "vehicle_speed": speed}, {}


def mean(values):
    values = [x for x in values if x is not None]
    return statistics.mean(values) if values else None


def wilson(k, n):
    z = 1.95996398454
    center = (k / n + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(k / n * (1 - k / n) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, center - half), min(1.0, center + half)


def write_csv(path, rows):
    if not rows:
        return
    with Path(path).open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run_sweep(directory, seeds=5):
    if seeds < 1:
        raise ValueError("seeds must be positive")
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    with (out / "runs.jsonl").open("w", encoding="utf-8") as log:
        for axis, value, params, options in designs():
            if axis == "mass_scale":
                params = dict(params, mass_scale=value)
            for seed in range(seeds):
                config = dict(width=3.2, seed=seed)
                config.update(params)
                scenario = corridor(settings=replace(Settings(), **options), **config)
                result = simulate(scenario, record=False)
                m = result["metrics"]
                row = {"axis": axis, "value": value, "seed": seed, "width_m": scenario.road.min_width(),
                       "vehicle_desired_speed_base_m_s": config.get("vehicle_speed", 3.0),
                       "status": m["status"], "completed": int(m["status"] == "completed"),
                       "completion_time_s": m["completion_time_s"], "observation_time_s": m["observation_time_s"],
                       "pedestrians_passed": m["pedestrians_passed"], "vehicles_passed": m["vehicles_passed"],
                       "collision_pairs": m["collision_pairs"], "boundary_violations": m["boundary_violations"],
                       "min_pair_gap_m": m["min_pair_gap_m"], "min_wall_gap_m": m["min_wall_gap_m"],
                       "total_agent_waiting_s": m["total_agent_waiting_s"],
                       "mean_path_length_m": mean([a["path_length_m"] for a in m["agents"]]),
                       "peak_decel_m_s2": max(a["peak_decel_m_s2"] for a in m["agents"]),
                       "speed_ceiling_unreachable_agent_steps": m["speed_ceiling_unreachable_agent_steps"]}
                rows.append(row)
                log.write(json.dumps({"design": {"axis": axis, "value": value}, "result": result}, ensure_ascii=False) + "\n")
            print(f"{axis}={value}: {seeds} runs", flush=True)
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["axis"], row["value"])].append(row)
    summary = []
    for (axis, value), trials in grouped.items():
        successful = [x["completion_time_s"] for x in trials if x["completed"]]
        lo, hi = wilson(len(successful), len(trials))
        summary.append({"axis": axis, "value": value, "runs": len(trials),
                        "success_rate": len(successful) / len(trials),
                        "wilson_95_low": lo, "wilson_95_high": hi,
                        "completion_mean_s": mean(successful),
                        "completion_sd_s": statistics.stdev(successful) if len(successful) > 1 else None,
                        "completion_p95_s": sorted(successful)[math.ceil(.95 * len(successful)) - 1] if successful else None,
                        "observation_mean_s": mean([x["observation_time_s"] for x in trials]),
                        "min_pair_gap_m": min(x["min_pair_gap_m"] for x in trials),
                        "collision_run_count": sum(x["collision_pairs"] > 0 for x in trials),
                        "wall_violation_run_count": sum(x["boundary_violations"] > 0 for x in trials),
                        "mean_total_agent_waiting_s": mean([x["total_agent_waiting_s"] for x in trials]),
                        "status_counts": json.dumps(dict(Counter(x["status"] for x in trials)), ensure_ascii=False)})
    write_csv(out / "runs.csv", rows)
    write_csv(out / "summary.csv", summary)
    (out / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return rows, summary


def make_plots(rows, summary, directory):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "savefig.facecolor": "white", "figure.facecolor": "white"})
    widths = sorted([r for r in summary if r["axis"] == "width"], key=lambda r: r["value"])
    x = [r["value"] for r in widths]
    fig, axes = plt.subplots(2, 2, figsize=(12, 8.4), constrained_layout=True)
    a = axes[0, 0]
    rate = [r["success_rate"] for r in widths]
    a.errorbar(x, rate, yerr=[[max(0, r["success_rate"]-r["wilson_95_low"]) for r in widths],
                            [max(0, r["wilson_95_high"]-r["success_rate"]) for r in widths]], fmt="o-", capsize=3, color="#197b92")
    a.set(title="A  Completion probability (95% Wilson intervals)", xlabel="Road width (m)", ylabel="Fraction of runs completed", ylim=(-.05, 1.1))
    a = axes[0, 1]
    completed = [r for r in widths if r["completion_mean_s"] is not None]
    a.errorbar([r["value"] for r in completed], [r["completion_mean_s"] for r in completed],
               yerr=[r["completion_sd_s"] or 0 for r in completed], fmt="o-", capsize=3, color="#197b92")
    a.set(title="B  Completion time among completed runs (mean +/- SD)", xlabel="Road width (m)", ylabel="Time until all trailing edges exit (s)")
    a = axes[1, 0]
    a.plot(x, [r["min_pair_gap_m"] for r in widths], "o-", color="#c46e24")
    a.axhline(.2, color="#667c8b", lw=1, ls=":", label="Lateral clearance = 0.2 m")
    a.set(title="C  Minimum physical pair gap across runs", xlabel="Road width (m)", ylabel="Gap (m)")
    a.legend(frameon=False, fontsize=8, loc="upper left")
    for a in (axes[0, 0], axes[0, 1], axes[1, 0]):
        a.axvspan(2.4, 2.8, color="#bc4157", alpha=.07)
        a.axvline(2.8, color="#667c8b", lw=1, ls="--")
        a.set_xlim(2.32, 5.08)
        a.grid(axis="y", alpha=.15)
    matrix = [r for r in summary if r["axis"] == "width_x_speed"]
    ws, vs = (2.7, 2.8, 2.9, 3.2, 4.0), (1.5, 3, 4.5)
    z = np.full((len(vs), len(ws)), np.nan)
    for r in matrix:
        w, v = map(float, str(r["value"]).split(":"))
        if r["completion_mean_s"] is not None:
            z[vs.index(v), ws.index(w)] = r["completion_mean_s"]
    a = axes[1, 1]
    cmap = plt.get_cmap("YlGnBu").copy()
    cmap.set_bad("#eef1f4")
    image = a.imshow(z, aspect="auto", cmap=cmap)
    a.set_xticks(range(len(ws)), [str(w) for w in ws])
    a.set_yticks(range(len(vs)), [str(v) for v in vs])
    a.set(title="D  Width x initial/desired vehicle speed", xlabel="Road width (m)", ylabel="Vehicle nominal speed (m/s)")
    for iy in range(len(vs)):
        for ix in range(len(ws)):
            val = z[iy, ix]
            a.text(ix, iy, "wait" if np.isnan(val) else f"{val:.1f}", ha="center", va="center",
                   color="#3b4f5b" if np.isnan(val) or val < np.nanmedian(z) else "white", fontsize=9)
    fig.colorbar(image, ax=a, label="Mean completion time (s)", fraction=.045)
    fig.suptitle("Unified pedestrian-vehicle model | 3 pedestrians, 2 vehicles", fontsize=15)
    out = Path(directory)
    fig.savefig(out / "sensitivity.png", dpi=180)
    fig.savefig(out / "sensitivity.svg")
    plt.close(fig)
