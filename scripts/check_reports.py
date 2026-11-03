"""逐份打开 reports/ 里的人口画像和汇总表，把内容和 data/pop/ 现算的数比对。不凭文件名下结论。

用法（项目根目录）：
  python3 scripts/check_reports.py            # 查 reports/
  python3 scripts/check_reports.py 某目录      # 查别的目录

期望值在这里独立重算，不 import batch_report，否则两边错得一样也查不出来；分型名取自大屏 data.js。
所有省都查，不抽样。有问题就逐条列出，退出码 1。
"""
import csv
import hashlib
import json
import re
import sys
from pathlib import Path

from openpyxl import load_workbook
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

ROOT = Path(__file__).resolve().parents[1]
POP_DIR = ROOT / "data" / "pop"
COCKPIT_JS = ROOT / "apps" / "pop-cockpit" / "data.js"

EXPECTED_REPORTS = 31  # 期望值只由人改
SLIDES = 4
BASE_YEAR, CENSUS_YEAR, LATEST_YEAR = 2010, 2020, 2023
JUMP_PCT = 5
FLAT_RATE = 0.001
WIDEN_RATIO = 1.25
NUMBER =re.compile(r"[+-]?\d[\d,]*(?:\.\d+)?%?")


def read_csv(name):
    with open(POP_DIR / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def rank_of(values, province):
    return sorted(values, key=values.get, reverse=True).index(province) + 1


def load_truth():
    """按省算出页面上应该出现的数。"""
    pop = {}
    for r in read_csv("pop_panel_long.csv"):
        pop.setdefault(r["province"], {})[int(r["year"])] = float(r["pop_10k"])

    net = {p: 0 for p in pop}
    for r in read_csv("od_long.csv"):
        net[r["current_province"]] += int(r["persons"])
        net[r["hukou_province"]] -= int(r["persons"])

    density = {r["province"]: float(r["density"]) for r in read_csv("density_2020.csv")}

    text = COCKPIT_JS.read_text(encoding="utf-8")
    cockpit = json.loads(text[text.index("{"): text.rindex("}") + 1])
    full_name = {r["province"]: r["geo_name"] for r in read_csv("province_adcode.csv")}

    all_years = range(min(min(s) for s in pop.values()), max(max(s) for s in pop.values()) + 1)
    truth = {}
    for p, series in pop.items():
        base, census, latest = series[BASE_YEAR], series[CENSUS_YEAR], series[LATEST_YEAR]
        years = sorted(series)
        jump = max(abs(series[b] / series[a] - 1) * 100 for a, b in zip(years, years[1:]))
        before = (census - base) / (CENSUS_YEAR - BASE_YEAR)
        after = (latest - census) / (LATEST_YEAR - CENSUS_YEAR)
        recent_pop = series[CENSUS_YEAR + 1]
        recent = (latest - recent_pop) / (LATEST_YEAR - CENSUS_YEAR - 1)
        widens = [before > 0 and abs(a) >= census * FLAT_RATE and a > before * WIDEN_RATIO for a in (after, recent)]
        truth[p] = {
            "base": base,
            "census": census,
            "latest": latest,
            "growth": (census / base - 1) * 100,
            "before": before,
            "after": after,
            "recent_pop": recent_pop,
            "recent": recent,
            "seam": widens[0] and not widens[1],  # 「增量扩大」只来自普查年到次年这一步
            "net": net[p] / 1e4,
            "net_rank": rank_of(net, p),
            "density": density[p],
            "density_rank": rank_of(density, p),
            "cluster": cockpit["cluster"][full_name[p]],
            "start": years[0],
            "missing": [y for y in all_years if y not in series],
            "has_jump": jump >= JUMP_PCT,
        }
    return truth


def picture_hash(slide):
    for shape in slide.shapes:
        if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
            alt = shape._element.nvPicPr.cNvPr.get("descr", "")
            return hashlib.md5(shape.image.blob).hexdigest(), alt
    return None, ""


def need(problems, text, wanted, where):
    if wanted not in text:
        problems.append(f"{where}：应含 {wanted!r}，实际 {text!r}")


def check_sentences(problems, t, n, cards):
    """结论的方向必须和数字一致，依据里的数必须都来自前面的页面。"""
    sentences = [cards.get(f"结论{i}", "").split("\n")[0] for i in (1, 2, 3)]
    if not all("依据" in cards.get(f"结论{i}", "") for i in (1, 2, 3)):
        problems.append("结论页：不是三句都带依据")
    s1, s2, s3 = sentences

    if t["before"] > 0 and "增长" not in s1:
        problems.append(f"结论1：前十年增长却写成 {s1!r}")
    if t["before"] < 0 and "减少" not in s1:
        problems.append(f"结论1：前十年减少却写成 {s1!r}")
    if t["after"] > 0 and ("转为减少" in s1 or "持续减少" in s1):
        problems.append(f"结论1：2020 年后增加却写成 {s1!r}")
    if t["after"] < 0 and ("仍在增长" in s1 or "保持增长" in s1 or "转为增长" in s1):
        problems.append(f"结论1：2020 年后减少却写成 {s1!r}")
    if t["seam"] != ("暂不判断" in s1) or (t["seam"] and "扩大" in s1):
        problems.append(f"结论1：增量扩大{'只' if t['seam'] else '不只'}来自普查衔接，却写成 {s1!r}")

    if (t["net"] < 0) != ("净流出" in s2):
        problems.append(f"结论2：净流入 {t['net']:+,.1f} 万却写成 {s2!r}")
    if "最多" in s2 and t["net_rank"] not in (1, n):
        problems.append(f"结论2：排名第 {t['net_rank']} 却写成 {s2!r}")

    need(problems, s3, t["cluster"].split("（")[0], "结论3")
    need(problems, s3, "人口增长" if t["growth"] > 0 else "人口减少", "结论3")
    need(problems, s3, "净流入" if t["net"] > 0 else "净流出", "结论3")
    third = n / 3
    level = "前列" if t["density_rank"] <= third else ("中游" if t["density_rank"] <= 2 * third else "后列")
    need(problems, s3, f"人口密度居全国{level}", "结论3")

    allowed = {str(y) for y in (BASE_YEAR, CENSUS_YEAR, LATEST_YEAR)} | {
        str(t["net_rank"]), str(t["density_rank"]), str(n),
        f"{t['base']:,.0f}", f"{t['census']:,.0f}", f"{t['latest']:,.0f}",
        f"{t['growth']:+.1f}%", f"{t['before']:+,.1f}", f"{t['after']:+,.1f}",
        f"{t['net']:+,.1f}", f"{t['density']:,.1f}",
    }
    if t["seam"]:  # 这种省的趋势页图注会列出次年的数
        allowed |= {str(CENSUS_YEAR + 1), f"{t['recent_pop']:,.0f}", f"{t['recent']:+,.1f}"}
    for i in (1, 2, 3):
        for number in NUMBER.findall(cards.get(f"结论{i}", "")):
            if number not in allowed:
                problems.append(f"结论{i}：出现了前面页面没有的数 {number}")


def check_report(path, province, truth, charts):
    """返回 (问题列表, 嵌入图的 hash)。"""
    t = truth[province]
    n = len(truth)
    prs = Presentation(path)
    slides = list(prs.slides)
    if len(slides) != SLIDES:
        return [f"应为 {SLIDES} 页，实际 {len(slides)} 页"], None

    problems = []
    cards = {sh.name: sh.text_frame.text for s in slides for sh in s.shapes if sh.has_text_frame}
    all_text = "\n".join(sh.text_frame.text for s in slides for sh in s.shapes if sh.has_text_frame)

    # 串省：文件名说是这个省，每一页标题也必须是这个省，且不能出现别省的名字
    for i, slide in enumerate(slides, 1):
        need(problems, slide.shapes.title.text_frame.text, province, f"第 {i} 页标题")
    for other in truth:
        if other != province and other in all_text:
            problems.append(f"出现了别省的名字：{other}")

    need(problems, slides[0].shapes.title.text_frame.text, "人口画像", "封面")
    need(problems, all_text, "数据来源", "封面")

    need(problems, cards.get("常住人口", ""), f"{t['latest']:,.0f} 万人", "常住人口")
    need(problems, cards.get("增长率", ""), f"{t['growth']:+.1f}%", "增长率")
    need(problems, cards.get("增长率", ""), f"{t['base']:,.0f} → {t['census']:,.0f} 万人", "增长率")
    need(problems, cards.get("净流入", ""), f"{t['net']:+,.1f} 万人", "净流入")
    need(problems, cards.get("净流入", ""), f"全国第 {t['net_rank']} / {n}", "净流入排名")
    need(problems, cards.get("人口密度", ""), f"{t['density']:,.1f} 人/km²", "人口密度")
    need(problems, cards.get("人口密度", ""), f"全国第 {t['density_rank']} / {n}", "密度排名")
    need(problems, cards.get("所属分型", ""), t["cluster"], "所属分型")

    # 趋势页：嵌入的图必须就是这个省的图文件
    need(problems, slides[2].shapes.title.text_frame.text, f"{t['start']}–{LATEST_YEAR}", "趋势页标题")
    embedded, alt = picture_hash(slides[2])
    chart = charts / f"{province}.png"
    if embedded is None:
        problems.append("趋势页没有图")
    elif not chart.exists():
        problems.append(f"缺图文件 {chart.name}")
    elif hashlib.md5(chart.read_bytes()).hexdigest() != embedded:
        problems.append(f"趋势页嵌入的图和 {chart.name} 不是同一张")
    need(problems, alt, province, "图的替代文字")
    need(problems, alt, f"{t['census']:,.0f} 万人", "图的替代文字")
    need(problems, alt, f"{t['latest']:,.0f} 万人", "图的替代文字")

    note = cards.get("图注", "")
    if t["missing"]:
        need(problems, note, f"{t['missing'][0]}–{t['missing'][-1]} 年无数据", "图注")
    if t["has_jump"] != ("最大单年变动" in note):
        problems.append(f"图注：单年跳变超过 {JUMP_PCT}% 与否和脚注不符")
    seam_note = f"从 {CENSUS_YEAR + 1} 年（{t['recent_pop']:,.0f} 万人）算起年均 {t['recent']:+,.1f} 万人"
    if t["seam"] != (seam_note in note):
        problems.append(f"图注：普查衔接说明和数据不符，应{'含' if t['seam'] else '不含'} {seam_note!r}")

    check_sentences(problems, t, n, cards)
    return problems, embedded


def check_summary(path, truth):
    """汇总表每省恰好一行，每格都和现算的数一致。比的是单元格的值，串行、数字存成文本都会报。"""
    if not path.exists():
        return [f"缺 {path.name}"]
    rows = list(load_workbook(path)["汇总"].values)
    columns = {
        f"{LATEST_YEAR} 年常住人口（万人）": lambda t: t["latest"],
        f"{BASE_YEAR}–{CENSUS_YEAR} 增长率": lambda t: t["growth"] / 100,
        f"净流入人数（万人，{CENSUS_YEAR}）": lambda t: t["net"],
        "净流入排名": lambda t: t["net_rank"],
        f"人口密度（人/km²，{CENSUS_YEAR}）": lambda t: t["density"],
        "密度排名": lambda t: t["density_rank"],
        "所属分型": lambda t: t["cluster"],
    }
    header = list(rows[0])
    expected_header = ["省份", *columns]
    if header != expected_header:
        return [f"表头应为 {expected_header}，实际 {header}"]

    problems = []
    names = [row[0] for row in rows[1:]]
    if sorted(names) != sorted(truth):
        problems.append(f"省份不对：缺 {sorted(set(truth) - set(names))}，多或重复 "
                        f"{sorted({n for n in names if n not in truth or names.count(n) > 1})}")
    for row in rows[1:]:
        province = row[0]
        if province not in truth:
            continue
        for col, want_of in columns.items():
            got, want = row[header.index(col)], want_of(truth[province])
            same = got == want if isinstance(want, str) else (
                isinstance(got, (int, float)) and abs(got - want) < 1e-6)
            if not same:
                problems.append(f"{province}的「{col}」：应为 {want!r}，实际 {got!r}")
    return problems


def main():
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "reports"
    truth = load_truth()
    charts = folder / "_charts"

    found = sorted(p.name for p in folder.glob("*人口画像.pptx") if not p.name.startswith("~$"))
    expected = {f"{p}人口画像.pptx" for p in truth}
    bad = {}
    extra = sorted(set(found) - expected)
    if extra:
        bad["多余文件"] = extra

    hashes = {}
    for province in truth:
        path = folder / f"{province}人口画像.pptx"
        if not path.exists():
            bad[province] = ["缺这份报告"]
            continue
        problems, embedded = check_report(path, province, truth, charts)
        if embedded:
            hashes.setdefault(embedded, []).append(province)
        if problems:
            bad[province] = problems

    for provinces in hashes.values():
        if len(provinces) > 1:
            for p in provinces:
                bad.setdefault(p, []).append(f"趋势图和别省完全相同：{'、'.join(provinces)}")

    summary_problems = check_summary(folder / "汇总.xlsx", truth)
    if summary_problems:
        bad["汇总表"] = summary_problems

    for name, problems in bad.items():
        print(f"✗ {name}")
        for problem in problems:
            print(f"    {problem}")

    print(f"报告 {len(found)} 份（期望 {EXPECTED_REPORTS}）；有问题 {len(bad)} 份（汇总表{'有问题' if summary_problems else '无问题'}）")
    if len(found) != EXPECTED_REPORTS or bad:
        sys.exit(1)


if __name__ == "__main__":
    main()
