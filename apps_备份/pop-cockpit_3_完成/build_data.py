# -*- coding: utf-8 -*-
"""D4-1 实操 1 参考答案：人口版图素材 → 大屏数据层 data.js（window.POP_DATA）。
放到学员项目 apps/pop-cockpit/ 下，在项目根目录运行：python apps/pop-cockpit/build_data.py
读：data/pop/pop_panel_long.csv、od_long.csv、density_2020.csv、cluster_profile.csv；省名对齐 assets/china.js（DataV 全称）。"""
import csv, json, os, sys
from pathlib import Path

ROOT = Path.cwd(); POP = ROOT / "data" / "pop"; OUT = Path(__file__).resolve().parent / "data.js"
rows = lambda f: list(csv.DictReader(open(POP / f, encoding="utf-8-sig")))
t = (ROOT / "assets" / "china.js").read_text(encoding="utf-8")
geo = json.loads(t[t.index("=") + 1:t.rstrip().rstrip(";").rstrip().rindex("}") + 1])
FULL = [f["properties"]["name"] for f in geo["features"] if f["properties"].get("name")]
SUF = ("维吾尔自治区", "回族自治区", "壮族自治区", "特别行政区", "自治区", "省", "市")
def short(n):
    for s in SUF:
        if n.endswith(s): return n[: -len(s)]
    return n
full = {short(n): n for n in FULL}
center = {f["properties"]["name"]: f["properties"].get("center") for f in geo["features"] if f["properties"].get("name")}

miss = set()
def F(p):
    if p not in full: miss.add(p); return None
    return full[p]

pop = rows("pop_panel_long.csv"); years = sorted({int(r["year"]) for r in pop})
panel = {}
for r in pop:
    k = F(r["province"])
    if k: panel.setdefault(k, [None] * len(years))[years.index(int(r["year"]))] = round(float(r["pop_10k"]), 2)
od = [[F(r["hukou_province"]), F(r["current_province"]), int(float(r["persons"]))] for r in rows("od_long.csv")]
net = {}
for o, d, p in od:
    net[d] = net.get(d, 0) + p; net[o] = net.get(o, 0) - p
net = {k: round(v / 1e4, 1) for k, v in net.items()}
density = {F(r["province"]): round(float(r["density"]), 1) for r in rows("density_2020.csv")}
clu = rows("cluster_profile.csv"); groups = {}
for r in clu: groups.setdefault(r["cluster"], []).append(r)
cname = {}
for c, m in groups.items():          # 按类中心起名（与第一轮同一规则）
    gr = sum(float(x["growth_10_20"]) for x in m) / len(m); nr = sum(float(x["net_rate"]) for x in m) / len(m)
    cname[c] = f"极端流入（{m[0]['province']}）" if len(m) == 1 else ("收缩型" if gr < 0 else ("增长流入型" if nr > 5 else "人口输出型"))
cluster = {F(r["province"]): cname[r["cluster"]] for r in clu}
if miss:
    sys.exit(f"这些省名和地图对不上，请先处理：{sorted(miss)}")
data = {"meta": {"years": years, "provinces": sorted(panel), "数据来源": "中国人口和就业统计年鉴 2024（1990–2023 年末常住人口）；第七次人口普查（省际流动、2020 人口）",
                 "口径说明": "人口：年末常住人口（万人），缺失写 null；净流入 = 迁入 − 迁出（七普，户籍地 → 现住地，万人）；密度：2020 年人口 ÷ 等积投影面积（人/km²）；分型：K-Means k = 4（增长率、净流入率、密度）"},
        "panel": panel, "od": od, "net": net, "density": density, "cluster": cluster, "center": {k: center[k] for k in panel}}
OUT.write_text("window.POP_DATA = " + json.dumps(data, ensure_ascii=False) + ";\n", encoding="utf-8")
y23 = sum(v[years.index(2023)] or 0 for v in panel.values()); top = sorted(net.items(), key=lambda x: -x[1])
print(f"data.js {OUT.stat().st_size / 1024:.0f} KB · 省 {len(panel)} · 2023 合计 {y23:,.0f} 万人 · null {sum(v.count(None) for v in panel.values())} 个")
print(f"OD {len(od)} 条，合计 {sum(p for *_, p in od):,} 人 · 净流入前三 {top[:3]} · 后三 {top[-3:]}")
