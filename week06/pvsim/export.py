import csv
import json
from pathlib import Path


def save_result(result, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    with (directory / "trajectory.csv").open("w", newline="", encoding="utf-8-sig") as f:
        fields = ["time_s", "id", "x_m", "y_m", "speed_m_s", "vy_m_s", "mode", "done"]
        writer = csv.writer(f)
        writer.writerow(fields)
        for frame in result["trace"]:
            for a in frame["agents"]:
                writer.writerow([frame["time"], a["id"], a["x"], a["y"], a["speed"], a["vy"], a["mode"], a["done"]])


def save_replay(results, path):
    template = (Path(__file__).parent / "replay.html").read_text(encoding="utf-8")
    # The replay is self-contained: no server, CDN or network needed.
    compact = []
    for label, result in results:
        compact.append({"label": label, "scenario": result["scenario"], "metrics": result["metrics"],
                        "feasibility": result["feasibility"], "trace": result["trace"], "policy": result.get("policy", {})})
    payload = json.dumps(compact, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(template.replace("__SIMULATION_DATA__", payload), encoding="utf-8")
