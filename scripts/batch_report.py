"""批量生成各省人口画像报告：模板里没有任何一个省的数值，全部按省名从 data/pop/ 现取。

用法（项目根目录）：
  python3 scripts/batch_report.py             # 生成全部省份，并写出 reports/汇总.xlsx
  python3 scripts/batch_report.py 上海 重庆    # 只生成指定省份，不动汇总表；省名用 data/pop 里的短名

每省输出 reports/{省名}人口画像.pptx 和 reports/_charts/{省名}.png。
缺的年份不补 0；省名或口径对不上就中止，不静默出一份错报告。
"""
import csv
import sys
from functools import lru_cache
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from lxml import etree
from matplotlib import font_manager
from matplotlib.ticker import FuncFormatter, MaxNLocator
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
POP_DIR = ROOT / "data" / "pop"
REPORT_DIR = ROOT / "reports"

# —— 报告口径：这些是所有省共用的参数，不是某个省的值 ——
BASE_YEAR = 2010
CENSUS_YEAR = 2020
LATEST_YEAR = 2023
RECENT_BASE = CENSUS_YEAR + 1  # 普查年的次年，从这年起都是抽样推算
CENSUS_SOURCE = "普查推算"
JUMP_PCT = 5  # 单年变动超过这个百分比，趋势页要加脚注提醒
FLAT_RATE = 0.001  # 年均增减不足人口的 0.1%，结论里算「基本持平」
WIDEN_RATIO = 1.25  # 年均增量超过前十年的这个倍数，结论里才算「增量扩大」

# 聚类编号 → 类别名，与 apps/pop-cockpit/build_data.py 一致
CLUSTER_NAMES = {
    0: "极端流入（上海）",
    1: "收缩型",
    2: "增长流入型",
    3: "人口输出型",
}

# —— 版式：颜色沿用人口大屏（apps/pop-cockpit）——
FONT = "Microsoft YaHei"
CHART_FONTS = ["PingFang SC", "Hiragino Sans GB", "Heiti SC", "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Arial Unicode MS"]
NAVY = RGBColor(0x06, 0x12, 0x2A)
NAVY_CARD = RGBColor(0x0F, 0x25, 0x47)
BLUE = RGBColor(0x2B, 0x70, 0xC2)
CORAL = RGBColor(0xEF, 0x5F, 0x4C)
TINT = RGBColor(0xF0, 0xF5, 0xFB)
INK = RGBColor(0x0F, 0x1B, 0x2D)
MUTED = RGBColor(0x55, 0x65, 0x7C)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
ON_DARK = RGBColor(0xE3, 0xEE, 0xFF)
ON_DARK_2 = RGBColor(0xA9, 0xBC, 0xD8)

SLIDE_W, SLIDE_H = 13.333, 7.5
MARGIN = 0.6
CONTENT_W = SLIDE_W - 2 * MARGIN
CHART_W, CHART_H = CONTENT_W, 4.85


def read_csv(name):
    with open(POP_DIR / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


# —— 数据层：只认省名 ——


@lru_cache(maxsize=1)
def load_tables():
    """读 data/pop/ 的各张表。排名要和全国比，所以整表读入。"""
    panel, source = {}, {}
    for r in read_csv("pop_panel_long.csv"):
        panel.setdefault(r["province"], {})[int(r["year"])] = float(r["pop_10k"])
        source[(r["province"], int(r["year"]))] = r["source_type"]

    # 净流入 = 流入 − 流出（人），与大屏数据层同一算法
    net = {p: 0 for p in panel}
    for r in read_csv("od_long.csv"):
        net[r["hukou_province"]] -= int(r["persons"])
        net[r["current_province"]] += int(r["persons"])

    density = {r["province"]: float(r["density"]) for r in read_csv("density_2020.csv")}
    profile = {r["province"]: r for r in read_csv("cluster_profile.csv")}
    order = [r["province"] for r in read_csv("province_adcode.csv")]  # 行政区划代码顺序
    if set(order) != set(panel):
        sys.exit(f"✗ province_adcode.csv 和人口面板的省份对不上：{sorted(set(order) ^ set(panel))}")
    return {"panel": panel, "source": source, "net": net, "density": density, "profile": profile, "order": order}


def rank_desc(values, province):
    """从大到小排第几，1 = 最大。"""
    return sorted(values, key=values.get, reverse=True).index(province) + 1


def largest_jump(series, sources):
    """最大的单年变动；没超过 JUMP_PCT 就返回 None。"""
    years = sorted(series)
    a, b = max(zip(years, years[1:]), key=lambda ab: abs(series[ab[1]] / series[ab[0]] - 1))
    pct = (series[b] / series[a] - 1) * 100
    if abs(pct) < JUMP_PCT:
        return None
    return {
        "from": a,
        "to": b,
        "delta": series[b] - series[a],
        "pct": pct,
        "census_seam": CENSUS_SOURCE in (sources[a], sources[b]),
    }


def get_metrics(province):
    """按省名取齐报告要用的所有数字。模板只读这个字典。"""
    t = load_tables()
    if province not in t["panel"]:
        sys.exit(f"✗ 没有这个省：{province!r}。可选：{'、'.join(sorted(t['panel']))}")

    series = t["panel"][province]
    sources = {y: t["source"][(province, y)] for y in series}
    absent = [y for y in (BASE_YEAR, CENSUS_YEAR, RECENT_BASE, LATEST_YEAR) if y not in series]
    if absent:
        sys.exit(f"✗ {province} 缺 {absent} 年常住人口，算不了增长率，已中止")

    pop_base, pop_census, pop_latest = series[BASE_YEAR], series[CENSUS_YEAR], series[LATEST_YEAR]
    growth = (pop_census / pop_base - 1) * 100
    net = t["net"][province] / 1e4
    density = t["density"][province]
    profile = t["profile"][province]

    # 分型表里也有这三个数，必须和现算的一致，否则两套口径混用
    for label, ours, theirs in [("增长率", growth, profile["growth_10_20"]),
                                ("净流入", net, profile["net_10k"]),
                                ("密度", density, profile["density"])]:
        if abs(ours - float(theirs)) > 0.01:
            sys.exit(f"✗ {province} 的{label}对不上：现算 {ours}，cluster_profile.csv 为 {theirs}")

    cluster_id = int(profile["cluster"])
    if cluster_id not in CLUSTER_NAMES:
        sys.exit(f"✗ cluster_profile.csv 出现未命名的类别编号 {cluster_id}（{province}），请补 CLUSTER_NAMES")

    all_years = sorted({y for s in t["panel"].values() for y in s})
    return {
        "province": province,
        "n_provinces": len(t["panel"]),
        "series": series,
        "all_years": all_years,
        "missing_years": [y for y in all_years if y not in series],
        "census_years": sorted({y for (_, y), s in t["source"].items() if s == CENSUS_SOURCE}),
        "latest_source": sources[LATEST_YEAR],
        "pop_base": pop_base,
        "pop_census": pop_census,
        "pop_latest": pop_latest,
        "growth": growth,
        "annual_before": (pop_census - pop_base) / (CENSUS_YEAR - BASE_YEAR),
        "annual_after": (pop_latest - pop_census) / (LATEST_YEAR - CENSUS_YEAR),
        "pop_recent": series[RECENT_BASE],
        "annual_recent": (pop_latest - series[RECENT_BASE]) / (LATEST_YEAR - RECENT_BASE),
        "net": net,
        "net_rank": rank_desc(t["net"], province),
        "density": density,
        "density_rank": rank_desc(t["density"], province),
        "cluster": CLUSTER_NAMES[cluster_id],
        "jump": largest_jump(series, sources),
    }


# —— 结论：句子由规则决定，方向变了措辞跟着变 ——


def widening(m, annual):
    """按这个年均增量，算不算比前十年「增量扩大」；基本持平的不算。"""
    before = m["annual_before"]
    return before > 0 and abs(annual) >= m["pop_census"] * FLAT_RATE and annual > before * WIDEN_RATIO


def seam_distorted(m):
    """「增量扩大」只来自普查年到次年这一步：从次年算起就不成立，不能据此下判断。"""
    return widening(m, m["annual_after"]) and not widening(m, m["annual_recent"])


def trend_sentence(m):
    before, after = m["annual_before"], m["annual_after"]
    span = f"在 {BASE_YEAR}–{CENSUS_YEAR} 年人口" + ("增长" if before > 0 else "减少")
    if abs(after) < m["pop_census"] * FLAT_RATE:
        return f"{span}，{CENSUS_YEAR} 年后基本持平"
    if before > 0 and after < 0:
        return f"{span}，{CENSUS_YEAR} 年后转为减少"
    if before <= 0 and after > 0:
        return f"{span}，{CENSUS_YEAR} 年后转为增长"
    if before <= 0:
        return "人口持续减少"
    if after < before / 2:
        return f"人口仍在增长，但 {CENSUS_YEAR} 年后增量明显收窄"
    if after < before * 0.8:
        return f"人口仍在增长，但 {CENSUS_YEAR} 年后增量有所收窄"
    if seam_distorted(m):
        return f"{span}，{CENSUS_YEAR} 年后的变化受普查衔接影响，暂不判断"
    if after > before * 2:
        return f"人口保持增长，{CENSUS_YEAR} 年后增量明显扩大"
    if after > before * WIDEN_RATIO:
        return f"人口保持增长，{CENSUS_YEAR} 年后增量有所扩大"
    return f"人口保持增长，{CENSUS_YEAR} 年前后增量相近"


def flow_sentence(m):
    if m["net_rank"] == 1 and m["net"] > 0:
        return "是全国净流入人口最多的省份"
    if m["net_rank"] == m["n_provinces"] and m["net"] < 0:
        return "是全国净流出人口最多的省份"
    kind = "净流入" if m["net"] > 0 else "净流出"
    return f"是人口{kind}省，净流入排名全国第 {m['net_rank']}"


def type_sentence(m):
    grow = "人口增长" if m["growth"] > 0 else "人口减少"
    if m["growth"] > 0:
        link = "且净流入" if m["net"] > 0 else "但净流出"
    else:
        link = "但净流入" if m["net"] > 0 else "且净流出"
    third = m["n_provinces"] / 3
    level = "前列" if m["density_rank"] <= third else ("中游" if m["density_rank"] <= 2 * third else "后列")
    cluster = m["cluster"].split("（")[0]  # 句子里省名已出现过，不重复类别名括号里的省名
    return f"属「{cluster}」：{grow}{link}，人口密度居全国{level}"


def build_conclusions(m):
    """三句话，每句都带依据；依据里的数都出现在前面两页或由它们直接算出。"""
    p, n = m["province"], m["n_provinces"]
    recent = ""
    if seam_distorted(m):
        recent = (f"，从 {RECENT_BASE} 年算起（{m['pop_recent']:,.0f}→{m['pop_latest']:,.0f} 万人）"
                  f"年均 {m['annual_recent']:+,.1f} 万")
    return [
        (f"{p}{trend_sentence(m)}。",
         f"依据：{BASE_YEAR}→{CENSUS_YEAR} 年 {m['pop_base']:,.0f}→{m['pop_census']:,.0f} 万人，增长率 {m['growth']:+.1f}%"
         f"（年均 {m['annual_before']:+,.1f} 万）；\n{CENSUS_YEAR}→{LATEST_YEAR} 年 "
         f"{m['pop_census']:,.0f}→{m['pop_latest']:,.0f} 万人（年均 {m['annual_after']:+,.1f} 万）{recent}"),
        (f"{p}{flow_sentence(m)}。",
         f"依据：{CENSUS_YEAR} 年净流入 {m['net']:+,.1f} 万人，全国第 {m['net_rank']} / {n}"),
        (f"{p}{type_sentence(m)}。",
         f"依据：增长率 {m['growth']:+.1f}%，净流入 {m['net']:+,.1f} 万人；"
         f"密度 {m['density']:,.1f} 人/km²，全国第 {m['density_rank']} / {n}"),
    ]


# —— 图表 ——


def chart_font():
    installed = {f.name for f in font_manager.fontManager.ttflist}
    for name in CHART_FONTS:
        if name in installed:
            return name
    sys.exit(f"✗ 没找到中文字体（{'、'.join(CHART_FONTS)}），图上的字会变方框，已中止")


def hex_of(color):
    return f"#{color}"


def draw_trend_chart(m, path):
    series = m["series"]
    first, last = m["all_years"][0], m["all_years"][-1]
    years = list(range(first, last + 1))
    values = [series.get(y, float("nan")) for y in years]  # 缺的年份留空，不画成 0
    top = max(series.values()) * 1.22
    ink, muted, line, accent = map(hex_of, (INK, MUTED, BLUE, CORAL))

    plt.rcParams["font.family"] = chart_font()
    fig, ax = plt.subplots(figsize=(CHART_W, CHART_H), dpi=200)
    fig.subplots_adjust(left=0.055, right=0.90, top=0.93, bottom=0.09)

    ax.plot(years, values, color=line, linewidth=2.2, solid_capstyle="round", solid_joinstyle="round", zorder=3)
    ax.axvline(CENSUS_YEAR, color=accent, linewidth=1, zorder=1)
    ax.scatter([CENSUS_YEAR], [series[CENSUS_YEAR]], s=90, color=accent, edgecolors="white", linewidths=2, zorder=5)
    start = min(series)
    ax.scatter([start, last], [series[start], series[last]], s=60, color=line, edgecolors="white", linewidths=2,
               zorder=4, clip_on=False)

    ax.text(CENSUS_YEAR - 0.35, top * 0.985, f"{CENSUS_YEAR} 普查年  {series[CENSUS_YEAR]:,.0f} 万人",
            ha="right", va="top", fontsize=13, fontweight="bold", color=ink)
    ax.annotate(f"{last} 年\n{series[last]:,.0f} 万人", (last, series[last]), xytext=(12, 0),
                textcoords="offset points", ha="left", va="center", fontsize=13, color=ink, annotation_clip=False)
    rising = series[start + 5] >= series[start]  # 线往上走就把标签放线下方，避开折线
    ax.annotate(f"{start} 年  {series[start]:,.0f} 万人", (start, series[start]),
                xytext=(4, -12 if rising else 12), textcoords="offset points",
                ha="left", va="top" if rising else "bottom", fontsize=13, color=ink)

    ax.set_xlim(first, last)
    ax.set_ylim(0, top)
    ax.set_xticks(sorted({y for y in years if y % 5 == 0} | {last}))
    ax.yaxis.set_major_locator(MaxNLocator(nbins=5, min_n_ticks=4))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.text(0, 1.015, "万人", transform=ax.transAxes, ha="left", va="bottom", fontsize=12, color=muted)
    ax.grid(axis="y", color="#E3E8EF", linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(length=0, labelsize=12, labelcolor=muted)
    ax.tick_params(axis="x", pad=8)  # 让 x 轴首个年份避开 y 轴的 0
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color("#B8C2D0")

    fig.savefig(path, facecolor="white")
    plt.close(fig)


# —— 幻灯片模板：只从 m 取数 ——


def run(text, size, color, bold=False):
    return (text, size, color, bold)


def fill_text(frame, paragraphs, align=PP_ALIGN.LEFT):
    """paragraphs：[[run, run], ...]，或 ([run, run], 段后间距 pt)。"""
    for i, spec in enumerate(paragraphs):
        runs, after = spec if isinstance(spec, tuple) else (spec, 0)
        p = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        p.alignment = align
        p.space_after = Pt(after)
        for text, size, color, bold in runs:
            r = p.add_run()
            r.text = text
            r.font.size = Pt(size)
            r.font.bold = bold
            r.font.color.rgb = color
            r.font.name = FONT
            # font.name 只管西文，中文字体要单独写 a:ea
            etree.SubElement(r._r.get_or_add_rPr(), qn("a:ea"), typeface=FONT)


def set_margins(frame, x=0.0, y=0.0):
    frame.margin_left = frame.margin_right = Inches(x)
    frame.margin_top = frame.margin_bottom = Inches(y)


def add_text(slide, x, y, w, h, paragraphs, name, anchor=MSO_ANCHOR.TOP):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    box.name = name
    frame = box.text_frame
    frame.word_wrap = True
    frame.vertical_anchor = anchor
    set_margins(frame)
    fill_text(frame, paragraphs)
    return box


def flat_shape(shape, color, name):
    """纯色无边框。去掉形状自带的主题样式，否则有的软件还会画出阴影。"""
    shape.name = name
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()
    shape._element.remove(shape._element.find(qn("p:style")))


def add_card(slide, x, y, w, h, color, paragraphs, name, pad=0.3):
    card = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    flat_shape(card, color, name)
    card.adjustments[0] = 0.1 / min(w, h)  # 所有卡片同一个 0.1" 圆角
    frame = card.text_frame
    frame.word_wrap = True
    frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    set_margins(frame, x=pad, y=0.1)
    fill_text(frame, paragraphs)
    return card


def set_title(slide, text, color=INK):
    frame = slide.shapes.title.text_frame
    frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    set_margins(frame)
    fill_text(frame, [[run(text, 32, color, True)]])


def set_box(shape, x, y, w, h):
    shape.left, shape.top, shape.width, shape.height = Inches(x), Inches(y), Inches(w), Inches(h)


def new_deck(province):
    """默认模板是 4:3：先把母版和版式拉成 16:9，再定好封面和内容页标题的位置。"""
    prs = Presentation()
    k = Inches(SLIDE_W) / prs.slide_width
    prs.slide_width, prs.slide_height = Inches(SLIDE_W), Inches(SLIDE_H)
    for holder in [prs.slide_master, *prs.slide_layouts]:
        for ph in holder.placeholders:
            left, top, width, height = ph.left, ph.top, ph.width, ph.height
            ph.left, ph.top, ph.width, ph.height = int(left * k), top, int(width * k), height

    cover = prs.slide_layouts[0].placeholders
    set_box(cover[0], 0.9, 1.5, SLIDE_W - 1.8, 3.1)
    set_box(cover[1], 0.9, 5.2, SLIDE_W - 1.8, 1.2)
    set_box(prs.slide_layouts[5].placeholders[0], MARGIN, 0.42, CONTENT_W, 0.85)

    props = prs.core_properties
    props.title = f"{province}人口画像"
    props.author = props.last_modified_by = "scripts/batch_report.py"
    return prs


def fill_background(slide, color):
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = color


def add_cover(prs, m):
    slide = prs.slides.add_slide(prs.slide_layouts[0])
    fill_background(slide, NAVY)
    title = slide.shapes.title.text_frame
    title.vertical_anchor = MSO_ANCHOR.BOTTOM
    set_margins(title)
    fill_text(title, [[run(m["province"], 96, WHITE, True)], [run("人口画像", 44, ON_DARK)]])

    source = slide.placeholders[1].text_frame
    set_margins(source)
    fill_text(source, [
        [run(f"数据来源：国家统计局年鉴与人口普查（{m['all_years'][0]}–{m['all_years'][-1]} 各省常住人口）", 14, ON_DARK_2)],
        [run(f"第七次全国人口普查省际流动（{CENSUS_YEAR}，户籍地 → 现住地）", 14, ON_DARK_2)],
    ])


def stat_paragraphs(label, value, unit, note, value_size=34):
    value_runs = [run(value, value_size, INK, True)]
    if unit:
        value_runs.append(run(f" {unit}", 15, INK))
    return [([run(label, 14, MUTED)], 6), (value_runs, 6), [run(note, 13, MUTED)]]


def add_key_numbers(prs, m):
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    n = m["n_provinces"]
    set_title(slide, f"{m['province']}关键数字")

    top, gap = 1.45, 0.3
    hero_w, total_h = 4.6, 4.75
    add_card(slide, MARGIN, top, hero_w, total_h, NAVY, [
        ([run(f"{LATEST_YEAR} 年常住人口", 16, ON_DARK)], 10),
        ([run(f"{m['pop_latest']:,.0f}", 60, WHITE, True), run(" 万人", 20, ON_DARK)], 10),
        [run(f"{LATEST_YEAR} 年为{m['latest_source']}", 13, ON_DARK_2)],
    ], "常住人口")

    grid_x = MARGIN + hero_w + gap
    w = (SLIDE_W - MARGIN - grid_x - gap) / 2
    h = (total_h - gap) / 2
    cluster_size = 30 if len(m["cluster"]) <= 6 else 24
    cards = [
        ("增长率", stat_paragraphs(f"{BASE_YEAR}–{CENSUS_YEAR} 增长率", f"{m['growth']:+.1f}%", "",
                                f"{m['pop_base']:,.0f} → {m['pop_census']:,.0f} 万人")),
        ("净流入", stat_paragraphs(f"净流入人数（{CENSUS_YEAR}）", f"{m['net']:+,.1f}", "万人",
                                f"全国第 {m['net_rank']} / {n}")),
        ("人口密度", stat_paragraphs(f"人口密度（{CENSUS_YEAR}）", f"{m['density']:,.1f}", "人/km²",
                                 f"全国第 {m['density_rank']} / {n}")),
        ("所属分型", stat_paragraphs("所属分型", m["cluster"], "", f"全国 {len(CLUSTER_NAMES)} 类分型之一", value_size=cluster_size)),
    ]
    for i, (name, paragraphs) in enumerate(cards):
        add_card(slide, grid_x + (i % 2) * (w + gap), top + (i // 2) * (h + gap), w, h, TINT, paragraphs, name)

    add_text(slide, MARGIN, top + total_h + 0.2, CONTENT_W, 0.55, [[run(
        f"净流入 = 跨省流入 − 流出，七普 {CENSUS_YEAR} 年存量（户籍地 → 现住地），不含省内流动；排名按 {n} 省从高到低。"
        f"密度 = {CENSUS_YEAR} 年常住人口 ÷ 省域面积。分型按增长率、净流入、密度、净流入率聚类。", 11, MUTED)]], "口径说明")


def jump_note(jump):
    head = f"最大单年变动：{jump['from']}→{jump['to']} 年 {jump['delta']:+,.0f} 万人（{jump['pct']:+.1f}%），"
    if jump["census_seam"]:
        return head + "发生在抽样推算与普查推算的衔接处，可能含口径差异，不宜直接读作当年实际增减。"
    return head + "数据表未标注原因，解读前需核对口径（如行政区划调整）。"


def add_trend(prs, m, chart_path):
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    start, last = min(m["series"]), m["all_years"][-1]
    set_title(slide, f"{m['province']}人口趋势：{start}–{last}")

    top = 1.3
    pic = slide.shapes.add_picture(str(chart_path), Inches(MARGIN), Inches(top), width=Inches(CHART_W))
    pic.name = "人口折线图"
    pic._element.nvPicPr.cNvPr.set(
        "descr",
        f"{m['province']}{start}–{last} 年常住人口折线图：{CENSUS_YEAR} 普查年 {m['pop_census']:,.0f} 万人，"
        f"{LATEST_YEAR} 年 {m['pop_latest']:,.0f} 万人",
    )

    census = "、".join(map(str, m["census_years"]))
    notes = f"来源：国家统计局年鉴与人口普查。普查年（{census}）为普查推算，其余年份为抽样推算。"
    if m["missing_years"]:
        notes += f"{m['missing_years'][0]}–{m['missing_years'][-1]} 年无数据，图中留空。"
    paragraphs = [([run(notes, 11, MUTED)], 2)]
    if m["jump"]:
        paragraphs.append([run(jump_note(m["jump"]), 11, MUTED)])
    if seam_distorted(m):
        paragraphs.append([run(
            f"{CENSUS_YEAR}→{LATEST_YEAR} 年年均 {m['annual_after']:+,.1f} 万人含普查推算到抽样推算的衔接；"
            f"从 {RECENT_BASE} 年（{m['pop_recent']:,.0f} 万人）算起年均 {m['annual_recent']:+,.1f} 万人。", 11, MUTED)])
    add_text(slide, MARGIN, top + CHART_H + 0.08, CONTENT_W, 0.75, paragraphs, "图注")


def add_conclusions(prs, m):
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    fill_background(slide, NAVY)
    set_title(slide, f"{m['province']}人口画像：三点结论", WHITE)

    top, h, gap, dot = 1.45, 1.55, 0.25, 0.6
    for i, (sentence, basis) in enumerate(build_conclusions(m)):
        y = top + i * (h + gap)
        card = add_card(slide, MARGIN, y, CONTENT_W, h, NAVY_CARD, [
            ([run(sentence, 20, WHITE, True)], 6),
            *[[run(line, 14, ON_DARK_2)] for line in basis.split("\n")],
        ], f"结论{i + 1}", pad=1.15)
        card.text_frame.margin_right = Inches(0.3)
        badge = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(MARGIN + 0.3), Inches(y + (h - dot) / 2), Inches(dot), Inches(dot))
        flat_shape(badge, BLUE, f"序号{i + 1}")
        frame = badge.text_frame
        frame.vertical_anchor = MSO_ANCHOR.MIDDLE
        set_margins(frame)
        fill_text(frame, [[run(str(i + 1), 18, WHITE, True)]], align=PP_ALIGN.CENTER)


def make_report(province, out_dir=REPORT_DIR):
    """按省名现取数字，出图、出 PPT，返回 PPT 路径。"""
    m = get_metrics(province)

    chart_path = out_dir / "_charts" / f"{province}.png"
    chart_path.parent.mkdir(parents=True, exist_ok=True)
    draw_trend_chart(m, chart_path)

    prs = new_deck(province)
    add_cover(prs, m)
    add_key_numbers(prs, m)
    add_trend(prs, m, chart_path)
    add_conclusions(prs, m)

    out_path = out_dir / f"{province}人口画像.pptx"
    prs.save(out_path)
    return out_path


# —— 汇总表：每省一行，列和关键数字页一一对应 ——

# (列名, 取值, Excel 数字格式, 列宽)
SUMMARY_COLUMNS = [
    ("省份", lambda m: m["province"], "General", 10),
    (f"{LATEST_YEAR} 年常住人口（万人）", lambda m: m["pop_latest"], "#,##0", 15),
    (f"{BASE_YEAR}–{CENSUS_YEAR} 增长率", lambda m: m["growth"] / 100, "+0.0%;-0.0%;0.0%", 13),
    (f"净流入人数（万人，{CENSUS_YEAR}）", lambda m: m["net"], "+#,##0.0;-#,##0.0;0.0", 15),
    ("净流入排名", lambda m: m["net_rank"], "0", 11),
    (f"人口密度（人/km²，{CENSUS_YEAR}）", lambda m: m["density"], "#,##0.0", 15),
    ("密度排名", lambda m: m["density_rank"], "0", 11),
    ("所属分型", lambda m: m["cluster"], "General", 20),
]
PANEL_SOURCE = "data/pop/pop_panel_long.csv（国家统计局年鉴与人口普查）"
SUMMARY_NOTES = [
    (f"{LATEST_YEAR} 年常住人口", "抽样推算，单位万人", PANEL_SOURCE),
    ("增长率", f"{CENSUS_YEAR} 年 ÷ {BASE_YEAR} 年 − 1，两端都是普查推算", PANEL_SOURCE),
    ("净流入人数", f"跨省流入 − 流出，七普 {CENSUS_YEAR} 年存量（户籍地 → 现住地），不含省内流动；负数为净流出",
     "data/pop/od_long.csv（第七次全国人口普查）"),
    ("净流入排名", "各省从高到低，第 1 名净流入最多，最后一名净流出最多", "由净流入人数算出"),
    ("人口密度", f"{CENSUS_YEAR} 年常住人口 ÷ 省域面积", "data/pop/density_2020.csv"),
    ("密度排名", "各省从高到低，第 1 名密度最高", "由人口密度算出"),
    ("所属分型", "按增长率、净流入、密度、净流入率聚类", "data/pop/cluster_profile.csv"),
    ("数值精度", "单元格存全精度，显示位数与各省报告一致", "由脚本算好写入，不含公式"),
]


def style_sheet(sheet, widths):
    """表头深底白字并冻结，正文统一字体。"""
    for i, width in enumerate(widths):
        sheet.column_dimensions[chr(ord("A") + i)].width = width
    for row in sheet.iter_rows():
        for cell in row:
            cell.font = Font(name=FONT, size=11, bold=cell.row == 1, color="FFFFFF" if cell.row == 1 else str(INK))
            cell.alignment = Alignment(vertical="center", wrap_text=True,
                                       horizontal="center" if cell.row == 1 else cell.alignment.horizontal)
            if cell.row == 1:
                cell.fill = PatternFill("solid", fgColor=str(NAVY))
    sheet.row_dimensions[1].height = 48
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True


def write_summary(provinces, out_path):
    """每省一行关键数字，数字都按省名现取，和报告同一个来源。"""
    wb = Workbook()
    wb.properties.creator = "scripts/batch_report.py"
    sheet = wb.active
    sheet.title = "汇总"
    sheet.append([name for name, *_ in SUMMARY_COLUMNS])
    for province in provinces:
        m = get_metrics(province)
        sheet.append([value(m) for _, value, *_ in SUMMARY_COLUMNS])
    for row in sheet.iter_rows(min_row=2):
        for cell, (_, _, number_format, _) in zip(row, SUMMARY_COLUMNS):
            cell.number_format = number_format
    style_sheet(sheet, [width for *_, width in SUMMARY_COLUMNS])
    sheet.freeze_panes = "B2"
    sheet.auto_filter.ref = sheet.dimensions

    notes = wb.create_sheet("口径说明")
    notes.append(["字段", "口径", "来源"])
    for row in SUMMARY_NOTES:
        notes.append(row)
    style_sheet(notes, [20, 62, 46])
    notes.freeze_panes = "A2"

    wb.save(out_path)


def main():
    provinces = sys.argv[1:] or load_tables()["order"]
    for province in provinces:
        out_path = make_report(province)
        print(f"✓ {out_path.relative_to(ROOT)}  图表 reports/_charts/{province}.png")
    print(f"共 {len(provinces)} 份")
    if not sys.argv[1:]:  # 只跑部分省时不写，免得把汇总表盖成残缺版
        write_summary(provinces, REPORT_DIR / "汇总.xlsx")
        print(f"✓ reports/汇总.xlsx  {len(provinces)} 行")


if __name__ == "__main__":
    main()
