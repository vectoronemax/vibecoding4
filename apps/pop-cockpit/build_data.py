"""把 data/pop/ 下的人口版图素材聚合成大屏数据层 apps/pop-cockpit/data.js。

用法（项目根目录）：python3 apps/pop-cockpit/build_data.py

输出 window.POP_DATA = {meta, panel, od, net, density, cluster}，省名统一成
assets/china.js 里的全称。任何一个省名对不上地图都会列出来并中止，不静默丢弃。
"""
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
POP_DIR = ROOT / "data" / "pop"
GEO_JS = ROOT / "assets" / "china.js"
OUT_JS = Path(__file__).resolve().parent / "data.js"

# 聚类编号 → 类别名，与课程存档点 apps_备份/pop-cockpit_1_数据层 一致。各类均值：
# 0 仅上海（密度 3130 人/km²、净流入率 +40.6%）；1 十年增长 -6.7%；
# 2 十年增长 +14.9% 且净流入；3 净流入率 -8.2%
CLUSTER_NAMES = {
    0: "极端流入（上海）",
    1: "收缩型",
    2: "增长流入型",
    3: "人口输出型",
}


def read_csv(name):
    with open(POP_DIR / name, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_map_names():
    """读 china.js 的 GeoJSON，按地图顺序返回省级全称。"""
    text = GEO_JS.read_text(encoding="utf-8")
    geo = json.loads(text[text.index("{"): text.rindex("}") + 1])
    return [f["properties"]["name"] for f in geo["features"] if f["properties"].get("name")]


def build_name_map(short_names, map_names):
    """短名 → 地图全称：先精确匹配，再按前缀唯一匹配。返回 (映射, {对不上的名字: 候选})。"""
    mapping, unmatched = {}, {}
    for s in sorted(short_names):
        key = s.strip()
        if key in map_names:
            mapping[s] = key
            continue
        hits = [m for m in map_names if key and m.startswith(key)]
        if len(hits) == 1:
            mapping[s] = hits[0]
        else:
            unmatched[s] = hits
    return mapping, unmatched


def num(x, nd=2):
    """整数值写成 int，其余保留 nd 位小数，压小文件。"""
    v = round(float(x), nd)
    return int(v) if v == int(v) else v


def main():
    map_names = load_map_names()

    panel_rows = read_csv("pop_panel_long.csv")
    od_rows = read_csv("od_long.csv")
    density_rows = read_csv("density_2020.csv")
    cluster_rows = read_csv("cluster_profile.csv")

    # —— 省名对齐：四个文件里出现过的名字一个都不能漏 ——
    names_by_file = {
        "pop_panel_long.csv": {r["province"] for r in panel_rows},
        "od_long.csv": {r["hukou_province"] for r in od_rows} | {r["current_province"] for r in od_rows},
        "density_2020.csv": {r["province"] for r in density_rows},
        "cluster_profile.csv": {r["province"] for r in cluster_rows},
    }
    all_names = set().union(*names_by_file.values())
    to_full, unmatched = build_name_map(all_names, map_names)
    if unmatched:
        print("✗ 以下省名对不上 assets/china.js，已中止，未写出 data.js：")
        for name, hits in unmatched.items():
            files = [f for f, ns in names_by_file.items() if name in ns]
            print(f"  - {name!r}  候选 {hits or '无'}  出现在 {files}")
        sys.exit(1)

    # 每个文件都必须覆盖全部省份
    provinces = [m for m in map_names if m in set(to_full.values())]
    for fname, ns in names_by_file.items():
        missing = sorted(set(provinces) - {to_full[n] for n in ns})
        if missing:
            print(f"✗ {fname} 缺省份：{missing}")
            sys.exit(1)

    # —— panel：每省按 years 排成等长数组，缺失写 null ——
    years = sorted({int(r["year"]) for r in panel_rows})
    years = list(range(years[0], years[-1] + 1))
    units = {r["unit"] for r in panel_rows}
    if units != {"万人"}:
        sys.exit(f"✗ pop_panel_long.csv 单位不统一：{units}")
    lookup = {}
    for r in panel_rows:
        k = (to_full[r["province"]], int(r["year"]))
        if k in lookup:
            sys.exit(f"✗ pop_panel_long.csv 重复记录：{k}")
        lookup[k] = num(r["pop_10k"])
    panel = {p: [lookup.get((p, y)) for y in years] for p in provinces}

    # —— od：[迁出(户籍地), 迁入(现住地), 人数]，按人数降序 ——
    od = sorted(
        ([to_full[r["hukou_province"]], to_full[r["current_province"]], int(r["persons"])] for r in od_rows),
        key=lambda x: -x[2],
    )

    # —— net：净流入 = 流入 − 流出（人） ——
    net = {p: 0 for p in provinces}
    for src, dst, n in od:
        net[src] -= n
        net[dst] += n

    density = {to_full[r["province"]]: num(r["density"]) for r in density_rows}

    cluster, profile = {}, {}
    for r in cluster_rows:
        cid = int(r["cluster"])
        if cid not in CLUSTER_NAMES:
            sys.exit(f"✗ cluster_profile.csv 出现未命名的类别编号 {cid}（{r['province']}），请补 CLUSTER_NAMES")
        p = to_full[r["province"]]
        # 这张表里的净流入、密度必须和上面算出来的一致，否则两套口径混用
        if abs(float(r["net_10k"]) - net[p] / 1e4) > 0.01 or abs(float(r["density"]) - density[p]) > 0.01:
            sys.exit(f"✗ cluster_profile.csv 的净流入或密度与 od / density 不一致：{r['province']}")
        cluster[p] = CLUSTER_NAMES[cid]
        profile[p] = {"growth": num(r["growth_10_20"]), "netRate": num(r["net_rate"])}

    census_years = sorted({int(r["year"]) for r in panel_rows if r["source_type"] == "普查推算"})
    meta = {
        "years": years,
        "provinces": provinces,
        "数据来源": {
            "panel": f"data/pop/pop_panel_long.csv：国家统计局年鉴与人口普查，{years[0]}–{years[-1]} 年各省常住人口；"
                     f"普查年（{'、'.join(map(str, census_years))}）为普查推算，其余年份为抽样推算",
            "od": "data/pop/od_long.csv：第七次全国人口普查（2020）省际流动人口，户籍地 → 现住地",
            "density": "data/pop/density_2020.csv：2020 年（七普）常住人口 ÷ 省域面积",
            "cluster": "data/pop/cluster_profile.csv：按 2010–2020 增长率、净流入、密度、净流入率聚类",
        },
        "口径说明": {
            "panel": f"单位万人；数组与 years 一一对应，共 {len(years)} 年；缺失写 null（不是 0）",
            "od": "[迁出省(户籍地), 迁入省(现住地), 人数]，单位人，按人数降序；不含省内流动",
            "net": "由 od 计算：流入合计 − 流出合计，单位人；正为净流入，负为净流出",
            "density": "单位人/km²",
            "cluster": "类别名：" + "；".join(f"{k}={v}" for k, v in CLUSTER_NAMES.items()),
            "profile": "growth 为 2010→2020 常住人口增长率（%）；netRate 为净流入率（%），净流入 ÷ 2020 年常住人口",
            "省名": "统一为 assets/china.js 地图全称（如 内蒙古自治区）",
        },
    }

    data = {"meta": meta, "panel": panel, "od": od, "net": net, "density": density, "cluster": cluster, "profile": profile}
    OUT_JS.write_text(
        "// 由 build_data.py 生成，勿手改\n"
        "window.POP_DATA = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )

    # —— 报告 ——
    i23 = years.index(2023)
    nulls = [(p, years[i]) for p, vals in panel.items() for i, v in enumerate(vals) if v is None]
    null_2023 = [p for p, _ in nulls if _ == 2023]
    total_2023 = sum(v[i23] for v in panel.values() if v[i23] is not None)
    ranked = sorted(net.items(), key=lambda kv: -kv[1])
    no_data = [m for m in map_names if m not in provinces]

    print(f"✓ 写出 {OUT_JS.relative_to(ROOT)}  {OUT_JS.stat().st_size / 1024:.1f} KB")
    print(f"省份：{len(provinces)} 个 {'✓ 31 省齐全' if len(provinces) == 31 else '✗ 不是 31 省'}"
          f"（地图上无数据：{'、'.join(no_data)}）")
    print(f"面板：{years[0]}–{years[-1]} 共 {len(years)} 年，null {len(nulls)} 个"
          + (f"（{nulls[0][0]} {nulls[0][1]}–{nulls[-1][1]}）" if nulls and len({p for p, _ in nulls}) == 1 else ""))
    print(f"2023 年合计：{total_2023:,.0f} 万人" + (f"（{len(null_2023)} 省缺值未计入）" if null_2023 else ""))
    print(f"OD：{len(od)} 条，合计 {sum(x[2] for x in od):,} 人")
    print("净流入前三：" + "；".join(f"{p} {n / 1e4:+,.1f} 万" for p, n in ranked[:3]))
    print("净流入后三：" + "；".join(f"{p} {n / 1e4:+,.1f} 万" for p, n in ranked[-3:]))
    counts = {n: sum(v == n for v in cluster.values()) for n in CLUSTER_NAMES.values()}
    print("分型：" + "；".join(f"{n} {c} 省" for n, c in counts.items()))


if __name__ == "__main__":
    main()
