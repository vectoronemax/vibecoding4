# -*- coding: utf-8 -*-
"""D4-5 实操 2 存档点：45 城通勤数据 → 驾驶舱数据层 data.js（window.CM_DATA）。
复制到学员项目 apps/commute/ 下运行：python apps/commute/build_dashboard_data.py（在哪个目录运行都行）。
读：data/commute/（01 城市主表、02 长表、07 指标字典、08 / 12 校验表、09 城市背景、00 元数据）；
    data/processed/45城_通勤分型.json（第二天 D2-5 的结果；没有就读 data/processed_备份/ 里的标准结果）。
结构：values[指标下标][年份下标][城市下标] = 数值 | null（缺失写 null，不写 0）。"""
import json
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]                                   # apps/commute/ → 项目根目录
CM = ROOT / "data" / "commute"
OUT = HERE / "data.js"
rd = lambda f: pd.read_csv(CM / f, dtype={"adcode": str}, encoding="utf-8-sig")

meta_src = json.loads((CM / "00_元数据.json").read_text(encoding="utf-8"))
longdf, bg, dic = rd("02_通勤指标长表.csv"), rd("09_城市背景数据.csv"), rd("07_指标字典.csv")
CLASSES = ["超大城市", "特大城市", "Ⅰ型大城市", "Ⅱ型大城市"]
YEARS = sorted(longdf["年份"].unique().tolist())
IND = dic["指标"].tolist()

# 城市顺序：规模 → 2024 年「45分钟以内通勤比重」降序
k45 = longdf[(longdf["指标"] == "45分钟以内通勤比重") & (longdf["年份"] == max(YEARS))].set_index("城市")["数值"]
bg["_c"] = bg["城市规模"].map(CLASSES.index)
bg["_v"] = bg["城市"].map(k45)
bg = bg.sort_values(["_c", "_v"], ascending=[True, False]).reset_index(drop=True)
cities = [{"name": r["城市"], "short": r["城市"].removesuffix("市"), "adcode": r["adcode"], "cls": int(r["_c"]),
           "prov": r["省级行政区"], "lon": round(float(r["lon"]), 4), "lat": round(float(r["lat"]), 4),
           "pop": int(r["七普常住人口"]), "rail": int(r["是否已开通轨道"])} for _, r in bg.iterrows()]
CI = {c["name"]: i for i, c in enumerate(cities)}

values = [[[None] * len(cities) for _ in YEARS] for _ in IND]
for _, r in longdf.iterrows():
    if pd.notna(r["数值"]):
        values[IND.index(r["指标"])][YEARS.index(int(r["年份"]))][CI[r["城市"]]] = round(float(r["数值"]), 2)

# 报告公布值：分规模（算术平均）+ 总体（人口加权），画参照线用
chk = rd("08_校验_分级均值.csv")
report = {}
for k in IND:
    s = chk[chk["指标"] == k].set_index("分组")["报告公布均值"]
    report[k] = [None if pd.isna(s.get(g)) else float(s.get(g)) for g in CLASSES + ["总体"]]

indicators = [{"name": r["指标"], "unit": r["单位"], "dir": int(r["指标方向"]), "dim": r["指标维度"], "def": r["口径说明"]}
              for _, r in dic.iterrows()]

cj = ROOT / "data" / "processed" / "45城_通勤分型.json"
if not cj.exists():
    cj = ROOT / "data" / "processed_备份" / "45城_通勤分型.json"
cl = json.loads(cj.read_text(encoding="utf-8"))
order = cl["meta"]["类名顺序"]
cluster = {"names": order, "basis": cl["meta"]["依据"], "note": cl["meta"]["分型说明"], "source": str(cj.relative_to(ROOT)),
           "of": [None] * len(cities)}
for c in cl["cities"]:
    cluster["of"][CI[c["城市"]]] = order.index(c["通勤分型"])

DATA = {"meta": {"title": "中国主要城市通勤监测驾驶舱", "cities": cities, "years": YEARS, "classes": CLASSES,
                 "indicators": indicators, "reportMean": report, "caliber": meta_src["口径提示"], "issues": meta_src["已知问题"],
                 "survey": meta_src["调查期"], "source": "中规院《2025年中国主要城市通勤监测报告》；人口：第七次全国人口普查",
                 "schema": "values[指标下标][年份下标][城市下标] = 数值 | null；cluster.of[城市下标] = 类名下标"},
        "values": values, "cluster": cluster}
OUT.write_text("window.CM_DATA = " + json.dumps(DATA, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")

n = sum(len(y) for v in values for y in v)
nulls = sum(x is None for v in values for y in v for x in y)
print(f"data.js {OUT.stat().st_size / 1024:.0f} KB · 城市 {len(cities)} · 指标 {len(IND)} · 年份 {YEARS}")
print(f"指标值 {n} 个，其中 null {nulls} 个 · 分型 {sum(x is not None for x in cluster['of'])} 城（读 {cluster['source']}）")
print("指标方向：" + "；".join(f"{lab}：" + "、".join(i["name"] for i in indicators if i["dir"] == d) for d, lab in ((1, "+1"), (-1, "−1"), (0, "0"))))
