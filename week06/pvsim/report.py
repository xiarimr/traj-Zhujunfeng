"""Build human-readable reports from saved outputs (no simulation reruns)."""
import argparse
import csv
import html
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


NAMES = {"reciprocal": "统一规则", "social_force": "社会力基线", "sfm_guided": "社会力+完整修正", "sfm_guided_ungated": "社会力+部分修正"}
STATUS = {"completed": "全部通过", "sustained": "完整观察期", "collision": "碰撞", "boundary_violation": "越界",
          "waiting_clearance": "安全间距不足等待", "waiting_alignment": "固定位置阻塞", "waiting_geometry": "几何宽度不足",
          "deadlock_policy": "策略僵持", "timeout": "超时未完成"}
AXES = {"width":"道路宽度 / m", "bottleneck":"缩窄宽度 / m", "vehicle_speed":"车辆期望/初始速度 / m/s",
        "pedestrian_lateral_speed":"行人横向上限 / m/s", "lateral_clearance":"侧向间距 / m", "initial_gap":"初始相向中心距 / m",
        "pedestrian_width":"行人宽度 / m", "vehicle_width":"车辆宽度 / m", "pedestrian_count":"行人数",
        "dt":"步长 / s", "mass_scale":"质量倍率", "alignment":"位置与横向能力", "width_x_speed":"宽度×车速 / m:m/s"}


def number(value, precision=2):
    return "—" if value is None else f"{value:.{precision}f}"


def table(headers, rows):
    return "\n".join(["| " + " | ".join(map(str,headers)) + " |", "| " + " | ".join(["---"]*len(headers)) + " |"] +
                     ["| " + " | ".join(str(v).replace("|","/") for v in row) + " |" for row in rows])


def status_counts(text):
    return "、".join(f"{STATUS.get(k,k)} {v}" for k,v in json.loads(text).items())


def inline(text):
    text = html.escape(text)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    text = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'!\[([^]]*)\]\(([^)]+)\)', r'<img alt="\1" src="\2">', text)
    text = re.sub(r'\[([^]]*)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)
    return text


def render_markdown(markdown):
    out, in_code, in_table, in_list = [], False, False, False
    for line in markdown.splitlines():
        if line.startswith("```"):
            if in_table: out.append("</tbody></table></div>"); in_table=False
            if in_list: out.append("</ul>"); in_list=False
            out.append("</code></pre>" if in_code else "<pre><code>")
            in_code = not in_code
            continue
        if in_code:
            out.append(html.escape(line)+"\n")
            continue
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if all(re.fullmatch(r'[:\- ]+',c) for c in cells): continue
            if not in_table:
                out.append('<div class="scroll"><table><thead><tr>'+''.join('<th>'+inline(c)+'</th>' for c in cells)+'</tr></thead><tbody>')
                in_table=True
            else:
                out.append('<tr>'+''.join('<td>'+inline(c)+'</td>' for c in cells)+'</tr>')
            continue
        if in_table: out.append("</tbody></table></div>"); in_table=False
        if line.startswith("- "):
            if not in_list: out.append("<ul>"); in_list=True
            out.append('<li>'+inline(line[2:])+'</li>'); continue
        if in_list: out.append("</ul>"); in_list=False
        if not line.strip(): continue
        match = re.match(r'^(#{1,4}) (.*)',line)
        if match:
            n=len(match[1]);out.append(f'<h{n}>{inline(match[2])}</h{n}>')
        else:
            out.append('<p>'+inline(line)+'</p>')
    if in_table: out.append("</tbody></table></div>")
    if in_list: out.append("</ul>")
    return ''.join(out)


def html_document(title, body):
    return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>'+html.escape(title)+'''</title><style>
body{font:15px/1.8 "Segoe UI","Microsoft YaHei",sans-serif;background:#f4f7f9;color:#203442;margin:0}main{max-width:1120px;margin:auto;padding:40px 28px 80px;background:white}h1{font-size:30px;border-bottom:3px solid #197b92;padding-bottom:16px}h2{font-size:23px;margin-top:42px;color:#196b80}h3{font-size:18px;margin-top:28px}a{color:#176e8c}code{background:#eef3f6;padding:2px 5px;border-radius:3px;font-size:13px}pre{background:#eef3f6;padding:18px;overflow:auto;line-height:1.6}pre code{padding:0}table{border-collapse:collapse;width:100%;font-size:13px;line-height:1.65;margin:16px 0}td,th{padding:9px 11px;text-align:left;border-bottom:1px solid #dfe8ec}th{background:#edf4f7;color:#21495c;font-weight:600;white-space:nowrap}tr:nth-child(even){background:#f8fafb}.scroll{overflow-x:auto}img{width:100%;height:auto;display:block;margin:20px 0}p{margin:12px 0}li{margin:7px 0}@media(max-width:640px){main{padding:22px 14px}h1{font-size:25px}body{font-size:14px}}@media print{main{padding:0;max-width:none}body{background:white}h2,h3{break-after:avoid}tr,img{break-inside:avoid}a{color:inherit}}
</style><main>'''+body+'</main></html>'


def build_report(root):
    root=Path(root)
    docs=root/"docs"
    docs.mkdir(parents=True, exist_ok=True)
    read=lambda p:json.loads((root/p).read_text(encoding="utf-8"))
    sens=read("results/experiments/summary.json")
    bench=read("results/benchmark/summary.json")
    fail=read("results/failures/comparison.json")
    sfm=read("results/sfm_parameters/sfm_parameters.json")
    radial=read("results/circle_crossing/summary.json")
    demos=list((root/"results/demo").glob("*/result.json"))
    total=sum(r["runs"] for r in sens)+sum(r["runs"] for r in bench)+len(fail)+len(sfm)+len(demos)+sum(r["runs"] for r in radial)
    bywidth={r["value"]:r for r in sens if r["axis"]=="width"}
    main_count=Counter()
    for r in sens: main_count.update(json.loads(r["status_counts"]))
    lines=["# 人车交互模型与实验报告", "生成日期：2026-10-23。所有数值来自本目录保存的仿真输出；配置与原始结果可逐项复现。",
           "## 1. 交付内容与主要发现",
           f"本包整理了 {total} 次已保存仿真：统一规则灵敏度 {sum(r['runs'] for r in sens)} 次、三模型配对对照 {sum(r['runs'] for r in bench)} 次、社会力参数探索 {len(sfm)} 次、失败与修正 {len(fail)} 次、基础场景演示 {len(demos)} 次、向心穿越 {sum(r['runs'] for r in radial)} 次。演示和对照可能重复相同配置，不能将总数解释为相互独立样本。",
           "- 人和车共享运动方程及交互实现，区别只体现在尺寸和运动能力参数；质量不直接分配避让责任。",
           "- 默认车宽1.8 m、人宽0.6 m，几何下限为2.4 m；加入双方间距0.2 m和两侧各0.1 m后，安全断面下限为2.8 m。",
           f"- 默认3人2车、5个种子：5.0 m道路平均完成 {bywidth[5]['completion_mean_s']:.2f} s，3.2 m为 {bywidth[3.2]['completion_mean_s']:.2f} s，2.8 m为 {bywidth[2.8]['completion_mean_s']:.2f} s；2.6 m全部等待。",
           "- 2.9 m道路即使总宽够，车辆固定居中仍会挡住通道；允许车辆以0.2 m/s上限小幅靠边后通过。",
           "- 纯社会力基线在部分宽路能完成，但在窄路、多方向汇聚中出现碰撞/越界/僵持；逐步修正对照保留了未成功的中间方案。",
           "- 圆环实验为人车交替排布、向中心穿越到对径点；默认4人4车形成僵持，单人单车规则模型可完成。",
           "[模型方程与假设](MODEL.md) · [规则与指标定义](RULES.md) · [参数表](PARAMETERS.md) · [运行方法](../README.md)",
           "[基础场景动画](../results/demo/replay.html) · [直路三模型动画](../results/benchmark/replay.html) · [向心动态主页](../index.html) · [失败修正动画](../results/failures/replay.html)",
           "## 2. 基础设置与实验口径",
           "直路长60 m，默认3人2车，车辆沿+s、行人沿−s。所有主体初始同一横向路径，车辆根据最窄宽度预先靠边。向心实验默认半径12 m、4人4车，观察120 s。步长0.05 s，每个正式配置种子0–4；随机性仅为速度基值的±8%扰动。",
           "三模型使用同一初始状态和约束，不按类型调用不同积分器。纯SFM参数A=8 m/s²、B=1.5 m，软墙幅值3 m/s²、范围0.2 m。它是同包络适配的工程基线，未做实测标定；有限参数探索结果全部公开。",
           "通过时间只对已完成直路运行求均值。失败、等待和超时用—表示，不补零。向心实验以对径目标到达数和全部完成率评价，不使用周期通量。",
           "## 3. 道路宽度与数值灵敏度",
           table(["宽度/m","完成次数","平均完成/s","SD/s","95% Wilson完成率区间","最小间距/m","结果"],
                 [(r['value'],f"{round(r['success_rate']*r['runs'])}/{r['runs']}",number(r['completion_mean_s']),number(r['completion_sd_s']),
                   f"[{r['wilson_95_low']:.2f}, {r['wilson_95_high']:.2f}]",number(r['min_pair_gap_m'],3),status_counts(r['status_counts'])) for r in sens if r['axis']=='width']),
           "![宽度与车速灵敏度](../results/experiments/sensitivity.png)",
           "临界宽度附近变慢，部分来源于显式的窄路慢行系数；它是模型假设的作用，并非脱离假设发现的经验规律。安全下限以下的最小间距约0.6 m，是双方停在纵向间隔处，并不是已经实现横向通过。",
           "统一规则全部灵敏度运行分类："+"；".join(f"{STATUS.get(k,k)} {v}次" for k,v in main_count.items())+"。",
           table(["步长/s","平均完成/s","SD/s","完成率"],[(r['value'],number(r['completion_mean_s']),number(r['completion_sd_s']),f"{r['success_rate']:.0%}") for r in sens if r['axis']=='dt']),
           "[所有单因素、交互和圆环灵敏度表](SENSITIVITY.md) 包含尺寸、初始距离、人数、速度、横向能力、间距、质量负对照、步长、宽度×车速、向心初始半径与主体对数的结果。",
           "## 4. 统一规则与社会力模型对照",
           table(["直路宽度/m","策略","完成率","满足裕度的完成率","条件平均完成/s","碰撞运行","越界运行","结果"],
                 [(r['value'],NAMES[r['policy']],f"{r['success_rate']:.0%}",f"{r['safe_success_rate']:.0%}",number(r['completion_mean_s']),r['collision_runs'],r['boundary_violation_runs'],status_counts(r['status_counts'])) for r in bench if r['group']=='straight']),
           "![模型对照结果](../results/benchmark/model_comparison.png)",
           "这组比较支持的是具体实现、参数与初态下的差异。纯SFM软排斥不自动提供可行路线或硬安全边界，规则模型主动加入了选边、前瞻、慢行和制动约束，不能据此宣称所有社会力模型都较差。完成时间对失败样本不定义，不能只比较成功样本时间而忽略失败率。",
           "## 5. 圆环向心穿越",
           "人车交替均布于圆周，同时向中心移动，目标为各自对径点。详见[向心模型、适配与120次结果](CIRCLE.md)，[动态主页](../index.html)。",
           table(["配置","策略","全部到达率","条件完成/s","平均到达数","碰撞运行","结果"],
                 [(r['case'],NAMES[r['policy']],f"{r['completion_rate']:.0%}",number(r['completion_mean_s']),number(r['mean_arrived'],1),r['collision_runs'],status_counts(r['status_counts'])) for r in radial]),
           "默认4人4车在现有局部规则下僵持；允许车辆0.2 m/s侧移仍未解除。规则与修正版在单人单车中均5/5完成；纯SFM在2人2车中均碰撞。不同朝向投影矩形较保守，等待不能证明真实场景无路可走。",
           "## 6. 失败案例、原因与修正对照",
           table(["案例","策略","终局","完成/s","互过次数","碰撞对数","越界主体数"],
                 [(r['label'],NAMES[r['policy']],STATUS[r['status']],number(r['completion_time_s']),r['pair_passages'],r['collision_pairs'],r['boundary_violations']) for r in fail]),
           "- 空间不足：2.6 m无法同时保留所设安全裕度。改为2.8 m后通过；没有通过压缩实体或取消碰撞检查来伪造修正。",
           "- 固定车道阻塞：2.9 m车居中时单侧空间不够；只开放车辆小幅侧移能力后通过。",
           "- 制动距离不足：初始中心距5 m、车速12 m/s时发生碰撞；保持位置及其他条件，只将初始/期望车速降为1.5 m/s后通过。它说明控制器无法补救任意危险初态。",
           "- 社会力作用过短：A=4、B=0.8的5 m场景发生碰撞；A=8、B=1.5在该宽路配置通过。但增加排斥范围并不能解决所有窄路问题。",
           "- 软边界不足：相同SFM参数在3.2 m发生越界。加入明确横向目标和制动后虽避免此失败，保留已分离主体的排斥仍可造成后续僵持。",
           "- 中间修正失败：sfm_guided_ungated互过3次后僵持；在已经横向分离的相向主体间解除SFM排斥，完整修正版完成6次互过并全部退出。向心实验另列为多方向汇聚对照。",
           "这些解释对应保存的案例，不应泛化为所有新场景的充分因果证明。断面诊断是必要条件分析，几何上能放下不意味着局部策略一定可达。",
           "## 7. 社会力参数探索",
           "探索场景为3.2 m、1人1车、种子100–102。默认A=8、B=1.5参考了探索结果；未使用实测数据，也未声称对所有路宽、密度和软墙参数完成调优。",
           "[参数探索原始表](../results/sfm_parameters/sfm_parameters.csv)",
           "## 8. 验证与复现",
           "自动测试覆盖类型/质量不变性、同步顺序不变性、加减速限制、几何临界值、固定车道对照、缩窄路、连续步内穿越碰撞、固定朝向矩形交叉接触、整体旋转不变性、向心终点停车、SFM失败和混合模型修正。完整输出见 [验证日志](../results/validation.txt)。",
           "核心仿真仅依赖Python标准库。统计图可导出PNG和SVG，回放不依赖网络。每次运行的JSON记录完整参数、初态和指标；CSV提供统计及轨迹。",
           "```powershell", "python -m unittest discover -s tests -v", "python -m pvsim all --seeds 5 --plots --out results", "python -m pvsim.report --root .", "```",
           "## 9. 仍需验证的内容",
           "- 使用实际人车轨迹标定期望速度、反应/感知延迟、距离感知、个体差异和软墙参数。",
           "- 真正车辆转向与刚体弯道：当前小幅侧移是受限二维速度模型，向心主体保持初始朝向，尚无自行车模型或转向角约束。",
           "- 局部等待与全局可达性：当前只检测全体停滞；可加入等待图、退让、交替放行、避车港和全局路径规划。",
           "- 更多重复与不确定性来源：每配置5次仅覆盖有限的速度扰动；Wilson区间很宽，不能把5/5等同真实世界可靠率100%。",
           "- 初始速度扫描同时改变期望速度，初始距离扫描也改变剩余路程。原始表保留这些设计，不能把完成时间差全部归因于碰撞规避效率。",
           "## 10. 参考资料",
           "- [Helbing & Molnár：Social Force Model for Pedestrian Dynamics](https://arxiv.org/abs/cond-mat/9805244)",
           "- [Yang et al.：人车多状态社会力交互框架](https://arxiv.org/abs/2005.07769)",
           "- [ORCA：互惠避碰相关路线；本代码并未实现ORCA](https://gamma.cs.unc.edu/ORCA/)"]
    (docs/"REPORT.md").write_text("\n\n".join(lines),encoding="utf-8")
    appendix=["# 完整灵敏度结果", "每个正式配置5个配对种子；完成时间只统计已完成运行。—表示未定义。"]
    for axis in AXES:
        group=[r for r in sens if r['axis']==axis]
        appendix += ["## "+AXES[axis], table(["取值","完成率","完成时间均值/s","SD/s","等待总和均值/主体·秒","最小间距/m","结果"],
                    [(r['value'],f"{r['success_rate']:.0%}",number(r['completion_mean_s']),number(r['completion_sd_s']),number(r['mean_total_agent_waiting_s']),number(r['min_pair_gap_m'],3),status_counts(r['status_counts'])) for r in group])]
    for group,title in [('bottleneck','三模型缩窄道路')]:
        appendix += ["## "+title,table(["取值","策略","完整完成/观察率","条件完成/s","平均互过次数","固定时域有效速度/m·s⁻¹","结果"],
                  [(r['value'],NAMES[r['policy']],f"{r['success_rate']:.0%}",number(r['completion_mean_s']),number(r['mean_pair_passages']),number(r['mean_effective_speed_m_s']),status_counts(r['status_counts'])) for r in bench if r['group']==group])]
    appendix += ["## 向心穿越灵敏度", "[全部120次向心对照](CIRCLE.md)"]
    groups=defaultdict(list)
    for r in sfm:groups[(r['A_m_s2'],r['B_m'])].append(r)
    appendix += ["## 社会力A×B参数探索",table(["A/m·s⁻²","B/m","完成/3","满足安全裕度/3","终局"],
                [(A,B,sum(r['status']=='completed' for r in rs),sum(r['safe'] for r in rs),"、".join(f"{STATUS[k]} {v}" for k,v in Counter(r['status'] for r in rs).items())) for (A,B),rs in groups.items()])]
    (docs/"SENSITIVITY.md").write_text("\n\n".join(appendix),encoding="utf-8")
    # A copy/paste-friendly parameter table, directly derived from the documented tables.
    with (root/"parameters.csv").open("w",newline="",encoding="utf-8-sig") as f:
        writer=csv.writer(f);writer.writerow(["section","parameter","value_1","value_2_or_description","description"])
        section=""
        for line in (docs/"PARAMETERS.md").read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):section=line[3:]
            if line.startswith("|") and "---" not in line:
                cells=[x.strip() for x in line.strip().strip("|").split("|")]
                writer.writerow([section]+cells+[""]*(4-len(cells)))
    print(f"Report generated from {total} saved runs")


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--root",type=Path,default=Path('.'))
    build_report(parser.parse_args().root)


if __name__=='__main__':main()
