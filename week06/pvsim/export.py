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
                        "feasibility": result.get("feasibility", {}), "trace": result["trace"], "policy": result.get("policy", {})})
    payload = json.dumps(compact, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(template.replace("__SIMULATION_DATA__", payload), encoding="utf-8")


def save_homepage(replay_path, root):
    """The homepage itself contains the circle replay; no server is required."""
    page = Path(replay_path).read_text(encoding="utf-8")
    navigation = ('<nav style="display:flex;gap:18px;flex-wrap:wrap;margin-bottom:20px">'
                  '<strong>圆环向心穿越</strong><a href="docs/index.html">文档导航</a>'
                  '<a href="README.html">模型与规则</a><a href="docs/REPORT.html">实验报告</a>'
                  '<a href="docs/CIRCLE.html">向心实验结果</a>'
                  '<a href="results/demo/replay.html">直路与缩窄</a>'
                  '<a href="results/benchmark/replay.html">直路模型对比</a>'
                  '<a href="results/failures/replay.html">失败与修正</a></nav>')
    page = page.replace('<body><main>', '<body><main>'+navigation, 1)
    page = page.replace('<title>窄路人车交互 · 仿真回放</title>', '<title>人车交互实验主页 · 圆环向心穿越</title>')
    (Path(root)/'index.html').write_text(page, encoding='utf-8')
