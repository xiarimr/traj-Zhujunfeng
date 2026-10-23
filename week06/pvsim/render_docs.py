"""Render saved Markdown as an offline website, without rerunning experiments."""
import argparse
import html
import json
import os
import re
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit, urlunsplit

PAGES = [
    ("README.md", "模型与规则概览", "共同运动方程、交会逻辑与运行方法"),
    ("docs/MODEL.md", "模型方程", "统一规则、社会力模型与建模假设"),
    ("docs/RULES.md", "规则与指标", "同步更新、碰撞检查、通过与等待判定"),
    ("docs/PARAMETERS.md", "参数表", "默认值、单位和参数扫描范围"),
    ("docs/REPORT.md", "实验报告", "主要结果、模型比较与失败修正"),
    ("docs/SENSITIVITY.md", "灵敏度结果", "道路宽度、速度、尺寸、数量等参数扫描"),
    ("docs/CIRCLE.md", "圆环向心实验", "交替排布、穿过中心到对径点的实验"),
    ("docs/DELIVERY.md", "文件与数据索引", "原始数据、验证记录和交付清单"),
    ("docs/week06_人车交互模型与实验.md", "完整综合记录", "668 次运行记录、完整说明及可提取源码"),
]
REPLAYS = [
    ("index.html", "动态主页 · 向心穿越"),
    ("results/demo/replay.html", "直路与缩窄道路"),
    ("results/benchmark/replay.html", "直路三模型对比"),
    ("results/failures/replay.html", "失败案例与修正"),
]
STYLE = """
:root{color-scheme:light;--ink:#243b47;--muted:#586e7b;--line:#dce6e9}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:24px}
body{margin:0;color:var(--ink);background:#f3f6f7;font:15px/1.85 system-ui,"Microsoft YaHei",sans-serif}
a{color:#086f83;text-decoration:none}a:hover{text-decoration:underline}a:focus-visible{outline:3px solid #e8a745;outline-offset:3px}
.skip{position:absolute;top:-80px;background:white;padding:12px;z-index:5}.skip:focus{top:10px}
.top{background:#103c48;color:white;padding:20px max(24px,calc((100vw - 1440px)/2));display:flex;align-items:center;justify-content:space-between;gap:20px;flex-wrap:wrap}
.brand{font-size:19px;font-weight:700;color:white}.top nav{display:flex;gap:22px;flex-wrap:wrap}.top a{color:white}
.layout{max-width:1440px;margin:auto;display:grid;grid-template-columns:236px minmax(0,1fr);gap:28px;padding:30px 24px 80px}
.sidebar{align-self:start;position:sticky;top:20px;max-height:calc(100vh - 40px);overflow:auto;padding:6px 10px 12px 0}
.sidebar h2{font-size:12px;letter-spacing:1px;color:var(--muted);margin:20px 12px 8px}.sidebar h2:first-child{margin-top:0}
.sidebar a{display:block;padding:8px 12px;border-radius:6px;font-size:14px;color:var(--ink)}.sidebar a[aria-current=page]{background:#dceef0;color:#055f65;font-weight:700}
main{min-width:0;background:white;border:1px solid var(--line);border-radius:10px;padding:34px 42px 48px;box-shadow:0 4px 20px #17364206}
.meta{color:var(--muted);font-size:13px;display:flex;gap:14px;flex-wrap:wrap;border-bottom:1px solid var(--line);padding-bottom:15px;margin-bottom:26px}
h1{font-size:30px;line-height:1.5;margin:0 0 22px}h2{font-size:23px;line-height:1.6;margin:40px 0 16px;color:#146677}h3{font-size:18px;margin:30px 0 12px}h4{font-size:16px}p{margin:14px 0}li{margin:6px 0}
code{background:#edf3f5;border-radius:4px;padding:2px 5px;font:13px/1.65 Consolas,monospace;overflow-wrap:anywhere}pre{background:#f0f5f6;border:1px solid var(--line);border-radius:7px;padding:18px;overflow:auto;line-height:1.65}pre code{padding:0;background:none;overflow-wrap:normal}
.table-wrap{max-width:100%;overflow-x:auto;margin:20px 0;border:1px solid var(--line);border-radius:6px}table{border-collapse:collapse;width:100%;font-size:13px;line-height:1.75}th,td{text-align:left;padding:10px 12px;border-bottom:1px solid var(--line);vertical-align:top}th{background:#eaf2f4;font-weight:650;white-space:nowrap}tr:last-child td{border-bottom:0}tbody tr:nth-child(even){background:#f8fafb}
img{display:block;max-width:100%;height:auto;margin:24px auto}blockquote{border-left:4px solid #5aa1a7;padding:4px 18px;margin:20px 0;background:#f2f8f8}
.toc{background:#f6f9fa;border:1px solid var(--line);border-radius:7px;padding:14px 18px;margin:24px 0}.toc summary{cursor:pointer;font-weight:650}.toc ul{padding-left:20px;max-height:340px;overflow:auto}.toc li{margin:3px 0;font-size:14px}.toc .level-3{margin-left:16px}
.cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.card{border:1px solid var(--line);border-radius:8px;padding:20px;display:block;color:var(--ink)}.card:hover{border-color:#298892;background:#f5fafb;text-decoration:none}.card strong{display:block;font-size:17px;color:#096e7b}.card span{display:block;font-size:14px;color:var(--muted);margin-top:8px}
footer{border-top:1px solid var(--line);margin-top:38px;padding-top:18px;font-size:13px;color:var(--muted)}
@media(max-width:900px){.layout{grid-template-columns:190px minmax(0,1fr);gap:16px;padding:20px 16px}main{padding:26px 22px}.cards{grid-template-columns:1fr}}
@media(max-width:650px){.top{padding:18px}.layout{display:block;padding:14px}.sidebar{position:static;max-height:none;padding:0 0 18px}.sidebar nav{display:flex;flex-wrap:wrap;gap:4px}.sidebar a{font-size:13px;padding:6px 9px}.sidebar h2{margin:12px 8px 6px}main{padding:24px 18px}h1{font-size:25px}h2{font-size:21px}}
@media print{body{background:white}.top,.sidebar,.toc,.skip,.meta{display:none}.layout{display:block;padding:0}main{border:0;padding:0;box-shadow:none}.table-wrap,pre{overflow:visible}pre{white-space:pre-wrap}h1,h2,h3{break-after:avoid}tr,img{break-inside:avoid}a{color:inherit}}
"""


def relative_url(target, current):
    return quote(Path(os.path.relpath(target, current.parent)).as_posix(), safe="/.-_")


def render_markdown(text, source, targets):
    try:
        from markdown_it import MarkdownIt
    except ImportError as exc:
        raise SystemExit("Install documentation support: python -m pip install -r requirements-docs.txt") from exc
    parser = MarkdownIt("commonmark", {"html": False}).enable("table").enable("strikethrough")
    # Keep source-extraction metadata in the .md source, but hide it in the reader.
    text = re.sub(r'^<!-- (?:simfile path="[^"\n]+" sha256="[a-f0-9]+"|/simfile) -->\s*$', '', text, flags=re.M)
    tokens = parser.parse(text)
    headings, seen = [], {}
    for index, token in enumerate(tokens):
        if token.type == "heading_open":
            inline = tokens[index + 1]
            title = "".join(t.content for t in (inline.children or []) if t.type in ("text", "code_inline"))
            slug = re.sub(r"[^\w\-\s]", "", title.lower()).strip().replace(" ", "-") or "section"
            count = seen.get(slug, 0)
            seen[slug] = count + 1
            anchor = slug if not count else f"{slug}-{count}"
            token.attrSet("id", anchor)
            headings.append((int(token.tag[1:]), title, anchor))
        for child in token.children or []:
            if child.type != "link_open":
                continue
            parts = urlsplit(child.attrGet("href") or "")
            if parts.scheme or parts.netloc or not parts.path.lower().endswith(".md"):
                continue
            destination = (source.parent / unquote(parts.path)).resolve()
            if destination in targets:
                path = relative_url(targets[destination], targets[source.resolve()])
                child.attrSet("href", urlunsplit(("", "", path, parts.query, parts.fragment)))
    body = parser.renderer.render(tokens, parser.options, {})
    body = body.replace("<table>", '<div class="table-wrap"><table>').replace("</table>", "</table></div>")
    toc = "".join(f'<li class="level-{level}"><a href="#{quote(anchor)}">{html.escape(title)}</a></li>'
                  for level, title, anchor in headings if level in (2, 3))
    if toc:
        toc = '<details class="toc" open><summary>本页目录</summary><ul>' + toc + '</ul></details>'
        end_title = body.find("</h1>")
        at = end_title + 5 if end_title >= 0 else 0
        body = body[:at] + toc + body[at:]
    title = next((title for level, title, _ in headings if level == 1), source.stem)
    return title, body


def page_shell(root, current, title, body, pages, source=None):
    def link(relative, label, active=False):
        attr = ' aria-current="page"' if active else ""
        return f'<a href="{relative_url(root / relative, current)}"{attr}>{html.escape(label)}</a>'
    navigation = link("docs/index.html", "文档导航", current == root / "docs/index.html")
    navigation += "".join(link(str(Path(path).with_suffix(".html")), label,
                               current == root / Path(path).with_suffix(".html")) for path, label, _ in pages)
    replays = "".join(link(path, label) for path, label in REPLAYS)
    source_link = f'<a href="{relative_url(source, current)}">查看 Markdown 源文档</a>' if source else ""
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)} · 人车交互实验</title><style>{STYLE}</style></head>
<body><a class="skip" href="#content">跳转到正文</a>
<header class="top"><a class="brand" href="{relative_url(root / 'docs/index.html', current)}">Week06 · 人车交互实验</a>
<nav aria-label="主要入口">{link('index.html', '动态主页')}{link('docs/index.html', '文档导航')}{link('docs/REPORT.html', '实验报告')}</nav></header>
<div class="layout"><aside class="sidebar" aria-label="文档导航"><h2>模型与实验</h2><nav>{navigation}</nav><h2>交互回放</h2><nav>{replays}</nav></aside>
<main id="content"><div class="meta"><span>本地离线文档</span>{source_link}</div>{body}
<footer>Markdown 为源文档；修改后运行 <code>python -m pvsim.render_docs --root .</code> 更新网页。回放与实验数据由仿真代码另行生成。</footer></main></div></body></html>
'''


def build_docs(root):
    root = Path(root).resolve()
    sources = [root / "README.md", *sorted((root / "docs").glob("*.md"))]
    sources = [p for p in sources if p.is_file()]
    if not sources:
        raise SystemExit(f"No README.md or docs/*.md found under {root}")
    known = {path for path, _, _ in PAGES}
    pages = [p for p in PAGES if (root / p[0]).is_file()]
    pages += [(p.relative_to(root).as_posix(), p.stem, "补充文档") for p in sources if p.relative_to(root).as_posix() not in known]
    targets = {p.resolve(): p.with_suffix(".html") for p in sources}
    generated = []
    for source in sources:
        title, body = render_markdown(source.read_text(encoding="utf-8-sig"), source, targets)
        output = targets[source.resolve()]
        output.write_text(page_shell(root, output, title, body, pages, source), encoding="utf-8")
        generated.append(output.relative_to(root).as_posix())
    current = root / "docs/index.html"
    current.parent.mkdir(parents=True, exist_ok=True)
    cards = "".join(f'<a class="card" href="{relative_url(root / Path(path).with_suffix(".html"), current)}"><strong>{html.escape(label)}</strong><span>{html.escape(description)}</span></a>'
                    for path, label, description in pages)
    body = ('<h1>模型、规则与实验文档</h1><p>先从模型与规则概览了解运动和避障逻辑，再查看参数、实验比较及灵敏度结果。每页都有统一导航和章节目录。</p>'
            '<div class="cards">' + cards + '</div><h2>交互回放</h2><p>动态主页直接播放圆环向心穿越；左侧入口还可切换直路、模型对比和失败修正回放。回放支持播放、暂停、进度拖动与速度调整。</p>')
    current.write_text(page_shell(root, current, "文档导航", body, pages), encoding="utf-8")
    generated.append(current.relative_to(root).as_posix())
    return generated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()
    print(json.dumps({"rendered": build_docs(args.root)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
