"""把北京分区宽表和区县边界聚合成大屏数据层 apps/bj-cockpit/data.js、bj_geo.js。

用法（项目根目录）：python3 apps/bj-cockpit/build_data.py

输出 window.BJ_DATA = {meta, poi, area, pop, density, perCap, mix} 和 window.BJ_GEO（区界 GeoJSON），
区名统一成边界文件里的全称。任何一个区名对不上地图都会列出来并中止，不静默丢弃。
"""
import json
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[2]
TABLE_XLSX = ROOT / "data" / "processed_备份" / "北京分区宽表.xlsx"
GEO_JSON = ROOT / "data" / "raw" / "北京POI" / "北京区县边界_高德GCJ02.geojson"
OUT_JS = Path(__file__).resolve().parent / "data.js"
OUT_GEO = Path(__file__).resolve().parent / "bj_geo.js"

# 宽表里不是 POI 大类的列；其余列都算大类，必须正好 13 个
BASE_COLS = ["区划代码", "区名", "公报区域", "POI总数", "面积_km2", "POI密度_个每km2", "常住人口_2020", "每万人POI"]


def read_table():
    """读宽表和口径说明，返回 (表头, 行字典列表, 口径说明行)。"""
    wb = openpyxl.load_workbook(TABLE_XLSX, data_only=True)
    rows = list(wb["分区宽表"].iter_rows(values_only=True))
    header = list(rows[0])
    table = [dict(zip(header, r)) for r in rows[1:] if any(v is not None for v in r)]
    notes = [r[0] for r in wb["口径说明"].iter_rows(min_row=2, values_only=True) if r[0]]
    return header, table, notes


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


def check_row(r, categories):
    """宽表自洽：13 大类之和 = POI 总数；密度、每万人能由原列复算。"""
    errs = []
    poi, area, pop = r["POI总数"], r["面积_km2"], r["常住人口_2020"]
    total = sum(r[c] for c in categories)
    if total != poi:
        errs.append(f"13 大类之和 {total} ≠ POI总数 {poi}")
    # 面积只存到 0.1 km²，密度是用未取整面积算的，所以按面积 ±0.05 放宽
    lo, hi = poi / (area + 0.05) - 0.05, poi / (area - 0.05) + 0.05
    if not lo <= r["POI密度_个每km2"] <= hi:
        errs.append(f"密度 {r['POI密度_个每km2']} 不在复算范围 {lo:.1f}–{hi:.1f}")
    per_cap = poi / pop * 1e4
    if abs(per_cap - r["每万人POI"]) > 0.051:
        errs.append(f"每万人 {r['每万人POI']} ≠ 复算 {per_cap:.1f}")
    return errs


def main():
    geo = json.loads(GEO_JSON.read_text(encoding="utf-8"))
    map_names = [f["properties"]["name"] for f in geo["features"]]
    map_codes = {f["properties"]["name"]: f["properties"]["adcode"] for f in geo["features"]}

    header, table, notes = read_table()
    categories = [c for c in header if c not in BASE_COLS]
    if len(categories) != 13:
        sys.exit(f"✗ 宽表 POI 大类不是 13 个：{categories}")
    blanks = [(r["区名"], k) for r in table for k, v in r.items() if v is None]
    if blanks:
        sys.exit(f"✗ 宽表有空值：{blanks}")

    # —— 区名对齐：两边都要一个不差 ——
    names = [r["区名"] for r in table]
    if len(set(names)) != len(names):
        sys.exit(f"✗ 宽表区名重复：{sorted(n for n in set(names) if names.count(n) > 1)}")
    to_full, unmatched = build_name_map(names, map_names)
    if unmatched:
        print("✗ 以下区名对不上边界文件，已中止，未写出 data.js：")
        for name, hits in unmatched.items():
            print(f"  - {name!r}  候选 {hits or '无'}")
        sys.exit(1)
    no_data = [m for m in map_names if m not in to_full.values()]
    if no_data:
        print(f"✗ 地图上这些区在宽表里没有：{no_data}，已中止，未写出 data.js")
        sys.exit(1)
    code_diff = [(r["区名"], r["区划代码"], map_codes[to_full[r["区名"]]]) for r in table
                 if str(r["区划代码"]) != str(map_codes[to_full[r["区名"]]])]
    if code_diff:
        sys.exit(f"✗ 区划代码和边界文件不一致（区名, 宽表, 边界）：{code_diff}")

    # —— 宽表自洽检查 ——
    bad = {r["区名"]: check_row(r, categories) for r in table}
    bad = {k: v for k, v in bad.items() if v}
    if bad:
        print("✗ 宽表数字对不上，已中止，未写出 data.js：")
        for name, errs in bad.items():
            print(f"  - {name}：{'；'.join(errs)}")
        sys.exit(1)

    # 按地图顺序输出；密度、每万人直接用宽表的值（面积取整后复算会有偏差，如东城 1002.2 ≠ 1002.5）
    by_name = {to_full[r["区名"]]: r for r in table}
    districts = [m for m in map_names if m in by_name]
    meta = {
        "districts": districts,
        "categories": categories,
        "数据来源": {
            "table": "data/processed_备份/北京分区宽表.xlsx",
            "geo": "data/raw/北京POI/北京区县边界_高德GCJ02.geojson：" + geo.get("crs_note", ""),
            "宽表口径": notes,
        },
        "口径说明": {
            "poi": "单位个，16 区 13 大类之和",
            "area": "单位 km²（宽表取整到 0.1）",
            "pop": "单位人，2020 七普常住人口",
            "density": "单位个/km²，取宽表值",
            "perCap": "单位个/万人，取宽表值；POI 是 2026-10 采集，人口是 2020 七普，时点不同",
            "mix": "{区: [各大类个数]}，数组与 categories 一一对应",
            "区名": "统一为边界文件全称（如 朝阳区）",
        },
    }
    data = {
        "meta": meta,
        "poi": {d: by_name[d]["POI总数"] for d in districts},
        "area": {d: by_name[d]["面积_km2"] for d in districts},
        "pop": {d: by_name[d]["常住人口_2020"] for d in districts},
        "density": {d: by_name[d]["POI密度_个每km2"] for d in districts},
        "perCap": {d: by_name[d]["每万人POI"] for d in districts},
        "mix": {d: [by_name[d][c] for c in categories] for d in districts},
    }
    OUT_JS.write_text(
        "// 由 build_data.py 生成，勿手改\n"
        "window.BJ_DATA = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    OUT_GEO.write_text(
        "// 由 build_data.py 生成，勿手改；坐标为 GCJ-02，未转换\n"
        "window.BJ_GEO = " + json.dumps(geo, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )

    # —— 报告 ——
    by_density = sorted(districts, key=lambda d: -data["density"][d])
    by_per_cap = sorted(districts, key=lambda d: -data["perCap"][d])
    cy = "朝阳区"
    cy_top = sorted(zip(categories, data["mix"][cy]), key=lambda x: -x[1])[:3]

    print(f"✓ 写出 {OUT_JS.relative_to(ROOT)}  {OUT_JS.stat().st_size / 1024:.1f} KB")
    print(f"✓ 写出 {OUT_GEO.relative_to(ROOT)}  {OUT_GEO.stat().st_size / 1024:.1f} KB")
    print(f"区名对齐：宽表 {len(names)} 区 ↔ 地图 {len(map_names)} 区，对不上的：无；区划代码全部一致")
    print(f"大类：{len(categories)} 个（{'、'.join(categories)}）")
    print(f"POI 合计：{sum(data['poi'].values()):,}")
    print(f"常住人口合计：{sum(data['pop'].values()):,}")
    print("POI 密度最高：" + "、".join(f"{d} {data['density'][d]:,.1f}" for d in by_density[:2])
          + f"；最低：{by_density[-1]} {data['density'][by_density[-1]]:,.1f}")
    print("每万人 POI 前三：" + "、".join(f"{d} {data['perCap'][d]:,.1f}" for d in by_per_cap[:3]))
    print(f"{cy}构成前三：" + "、".join(f"{c} {n:,}" for c, n in cy_top))


if __name__ == "__main__":
    main()
