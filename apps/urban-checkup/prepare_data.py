"""静安区城市体检数据准备：统一 GCJ-02 → 点/面分别处理 → 切 100 米网格 → 定街镇归属。

用法（项目根目录）：python3 apps/urban-checkup/prepare_data.py

data/urban/ 只读，产物写到 apps/urban-checkup/prepared/。任何断言没过都中止，不静默丢数据。

各文件的实际坐标系（不能只看来源，也不能只看「落在区界内的比例」）：
  GCJ-02  静安区_边界（DataV）、静安区_餐饮POI（gcj 列）、静安_城市POI（OSM 来源但已转过）
  WGS-84  静安_街镇边界、静安_路网、静安_城市POI_扩、静安_轨道公交、静安_建筑、
          静安_人口栅格100m、地铁_站点职住
其中 轨道公交/建筑/人口栅格/站点职住 是 WGS-84 坐标却按 GCJ-02 区界筛过：原值 100% 落界，
看着像 GCJ-02，转完才露出真实位置，且西北侧约 500 米宽的带子上本来就缺数据。
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pyproj
import shapely
from shapely.geometry import mapping, shape

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "data" / "urban"
OUT = Path(__file__).resolve().parent / "prepared"

CELL_M = 100
GHSL_MAX_GAP_M = 75  # GHSL 像元约 105×95 米，半对角线约 71 米；超过这个距离说明附近没有像元

# GCJ-02 不是真正的 CRS，这里只借 UTM 51N 算米：10 公里内偏移几乎不变，距离误差可忽略
TO_M = pyproj.Transformer.from_crs(4326, 32651, always_xy=True)
TO_DEG = pyproj.Transformer.from_crs(32651, 4326, always_xy=True)
GEOD = pyproj.Geod(ellps="WGS84")

A = 6378245.0
EE = 0.00669342162296594323


def _dlat(x, y):
    r = -100 + 2 * x + 3 * y + 0.2 * y * y + 0.1 * x * y + 0.2 * np.sqrt(np.abs(x))
    r += (20 * np.sin(6 * x * np.pi) + 20 * np.sin(2 * x * np.pi)) * 2 / 3
    r += (20 * np.sin(y * np.pi) + 40 * np.sin(y / 3 * np.pi)) * 2 / 3
    r += (160 * np.sin(y / 12 * np.pi) + 320 * np.sin(y * np.pi / 30)) * 2 / 3
    return r


def _dlon(x, y):
    r = 300 + x + 2 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * np.sqrt(np.abs(x))
    r += (20 * np.sin(6 * x * np.pi) + 20 * np.sin(2 * x * np.pi)) * 2 / 3
    r += (20 * np.sin(x * np.pi) + 40 * np.sin(x / 3 * np.pi)) * 2 / 3
    r += (150 * np.sin(x / 12 * np.pi) + 300 * np.sin(x / 30 * np.pi)) * 2 / 3
    return r


def wgs_to_gcj(lon, lat):
    lon, lat = np.asarray(lon, float), np.asarray(lat, float)
    dlat, dlon = _dlat(lon - 105, lat - 35), _dlon(lon - 105, lat - 35)
    rad = lat / 180 * np.pi
    magic = 1 - EE * np.sin(rad) ** 2
    sq = np.sqrt(magic)
    return (
        lon + dlon * 180 / (A / sq * np.cos(rad) * np.pi),
        lat + dlat * 180 / (A * (1 - EE) / (magic * sq) * np.pi),
    )


def geom_wgs_to_gcj(geom):
    return shapely.transform(geom, lambda c: np.round(np.column_stack(wgs_to_gcj(c[:, 0], c[:, 1])), 7))


def geom_to_m(geom):
    return shapely.transform(geom, lambda c: np.column_stack(TO_M.transform(c[:, 0], c[:, 1])))


def metres(lon1, lat1, lon2, lat2):
    return GEOD.inv(lon1, lat1, lon2, lat2)[2]


def area_km2(geom):
    return abs(GEOD.geometry_area_perimeter(geom)[0]) / 1e6


def read_csv(name):
    return pd.read_csv(SRC / name, encoding="utf-8-sig")


def read_geojson(name):
    return json.loads((SRC / name).read_text(encoding="utf-8"))["features"]


def write_geojson(name, rows):
    features = [{"type": "Feature", "properties": p, "geometry": mapping(g)} for p, g in rows]
    text = json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False)
    (OUT / name).write_text(text, encoding="utf-8")


def write_csv(name, df):
    df.to_csv(OUT / name, index=False, encoding="utf-8-sig")


def expect(label, ok, detail=""):
    print(f"  {'通过' if ok else '失败'}  {label} {detail}")
    if not ok:
        raise SystemExit(f"断言失败：{label} {detail}")


class Towns:
    """14 个街镇的归属判定。区界是总口径：界外的点不归任何街镇。"""

    def __init__(self, district, names, polys):
        self.district = district
        self.names = np.array(names, dtype=object)
        self.tree = shapely.STRtree(polys)
        self.tree_m = shapely.STRtree([geom_to_m(p) for p in polys])

    def assign(self, lon, lat):
        """返回 (是否在区界内, 街镇名, 归属方式)。界内但落在街镇拼合缝隙里的取最近街镇并标出来。"""
        lon, lat = np.asarray(lon, float), np.asarray(lat, float)
        pts = shapely.points(lon, lat)
        inside = shapely.contains(self.district, pts)
        town = np.full(len(pts), None, dtype=object)
        how = np.full(len(pts), "界外", dtype=object)

        i_pt, i_poly = self.tree.query(pts, predicate="within")
        assert len(i_pt) == len(np.unique(i_pt)), "有点同时落在两个街镇里"
        keep = inside[i_pt]
        town[i_pt[keep]] = self.names[i_poly[keep]]
        how[i_pt[keep]] = "面内"

        gap = np.flatnonzero(inside & pd.isna(town))
        if len(gap):
            x, y = TO_M.transform(lon[gap], lat[gap])
            i_q, i_near = self.tree_m.query_nearest(shapely.points(x, y), all_matches=False)
            town[gap[i_q]] = self.names[i_near]
            how[gap[i_q]] = "最近"
        return inside, town, how


def build_grid(district, towns):
    """100 米米制网格，格心落在区界内的保留（面积守恒，比「整格在界内」不丢边缘）。"""
    district_m = geom_to_m(district)
    xmin, ymin, xmax, ymax = district_m.bounds
    x0, y0 = np.floor(xmin / CELL_M) * CELL_M, np.floor(ymin / CELL_M) * CELL_M
    cols = np.arange(int(np.ceil((xmax - x0) / CELL_M)))
    rows = np.arange(int(np.ceil((ymax - y0) / CELL_M)))
    cc, rr = np.meshgrid(cols, rows)
    cc, rr = cc.ravel(), rr.ravel()
    x, y = x0 + (cc + 0.5) * CELL_M, y0 + (rr + 0.5) * CELL_M
    lon, lat = TO_DEG.transform(x, y)
    inside, town, how = towns.assign(lon, lat)
    return pd.DataFrame({
        "grid_id": [f"{r:03d}_{c:03d}" for r, c in zip(rr[inside], cc[inside])],
        "row": rr[inside],
        "col": cc[inside],
        "x_m": x[inside],
        "y_m": y[inside],
        "lon": np.round(lon[inside], 7),
        "lat": np.round(lat[inside], 7),
        "街镇": town[inside],
        "归属方式": how[inside],
    })


def main():
    OUT.mkdir(exist_ok=True)
    report = {}

    # ---------- 边界 ----------
    print("\n[1] 边界")
    district = shape(read_geojson("静安区_边界.geojson")[0]["geometry"])
    town_feats = read_geojson("静安_街镇边界.geojson")
    town_names = [f["properties"]["name"] for f in town_feats]
    town_wgs = [shape(f["geometry"]) for f in town_feats]
    town_gcj = [geom_wgs_to_gcj(g) for g in town_wgs]
    union_wgs, union_gcj = shapely.union_all(town_wgs), shapely.union_all(town_gcj)
    iou = lambda a, b: a.intersection(b).area / a.union(b).area
    expect("街镇边界是 WGS-84：转完才和 GCJ 区界重合", iou(district, union_gcj) > 0.99 > 0.8 > iou(district, union_wgs),
           f"IoU 转前 {iou(district, union_wgs):.3f} → 转后 {iou(district, union_gcj):.3f}")
    towns = Towns(district, town_names, town_gcj)
    report["区界面积_km2"] = round(area_km2(district), 2)
    report["街镇缝隙_km2"] = {"区界有街镇无": round(area_km2(district.difference(union_gcj)), 3),
                          "街镇有区界无": round(area_km2(union_gcj.difference(district)), 3)}
    write_geojson("静安区_边界.geojson", [({"name": "静安区"}, district)])
    write_geojson("街镇边界.geojson", [(f["properties"], g) for f, g in zip(town_feats, town_gcj)])

    # ---------- 路网（线）：不裁，界外的路生活圈还要走 ----------
    print("\n[2] 路网")
    road_feats = read_geojson("静安_路网.geojson")
    roads = [geom_wgs_to_gcj(shape(f["geometry"])) for f in road_feats]
    write_geojson("路网.geojson", [(f["properties"], g) for f, g in zip(road_feats, roads)])
    vertices = shapely.get_coordinates(roads)
    road_in = shapely.contains(district, shapely.points(vertices)).mean()
    report["路网"] = {"条数": len(roads), "节点": len(vertices), "节点界内%": round(road_in * 100, 2)}
    print(f"  {len(roads)} 条，全部保留")

    # ---------- 点：界外保留 ----------
    print("\n[3] 点数据（界外保留）")
    poi = read_csv("静安_城市POI_扩.csv")
    poi_small = read_csv("静安_城市POI.csv")
    poi["lon"], poi["lat"] = wgs_to_gcj(poi.lon, poi.lat)
    poi["在区界内"], poi["街镇"], poi["归属方式"] = towns.assign(poi.lon, poi.lat)
    m = poi_small.merge(poi, on="osmid", suffixes=("", "_扩"))
    offset = metres(m.lon.values, m.lat.values, m.lon_扩.values, m.lat_扩.values)
    expect("城市POI 已是 GCJ-02：与「扩」转换后逐点重合", len(m) == len(poi_small) and offset.max() < 1,
           f"{len(m)} 对，最大差 {offset.max():.2f} 米")
    expect("城市POI 正好是「扩」的界内部分，不能两表相加", set(poi.osmid[poi.在区界内]) == set(poi_small.osmid),
           f"界内 {poi.在区界内.sum()} = 城市POI {len(poi_small)}")
    write_csv("POI.csv", poi)

    food = read_csv("静安区_餐饮POI.csv")
    gx, gy = wgs_to_gcj(food.lng_wgs84, food.lat_wgs84)
    gap = metres(food.lng_gcj02.values, food.lat_gcj02.values, gx, gy)
    expect("餐饮 gcj 列 = wgs 列正算", gap.max() < 1, f"最大差 {gap.max():.2f} 米")
    expect("餐饮两套坐标相距中位 484±3 米", abs(np.median(metres(food.lng_gcj02.values, food.lat_gcj02.values,
                                                       food.lng_wgs84.values, food.lat_wgs84.values)) - 484) <= 3)
    food = food.rename(columns={"lng_gcj02": "lon", "lat_gcj02": "lat"}).drop(columns=["lng_wgs84", "lat_wgs84"])
    food["在区界内"], food["街镇"], food["归属方式"] = towns.assign(food.lon, food.lat)
    write_csv("餐饮POI.csv", food)

    transit = read_csv("静安_轨道公交.csv").drop(columns="line")  # line 列 724 行全空
    expect("轨道公交是 WGS-84：同 osmid 与「扩」原值重合",
           metres(*_pairs(transit, read_csv("静安_城市POI_扩.csv"))).max() < 1)
    transit["lon"], transit["lat"] = wgs_to_gcj(transit.lon, transit.lat)
    transit["在区界内"], transit["街镇"], transit["归属方式"] = towns.assign(transit.lon, transit.lat)
    write_csv("轨道公交.csv", transit)

    stations = read_csv("地铁_站点职住.csv").rename(columns={"在静安": "在静安_原"})
    stations["lon"], stations["lat"] = wgs_to_gcj(stations.lon, stations.lat)
    stations["在静安"], stations["街镇"], stations["归属方式"] = towns.assign(stations.lon, stations.lat)
    write_csv("地铁站.csv", stations)
    flips = stations[stations.在静安 != stations.在静安_原]

    # ---------- 面：裁剪 + 标定 ----------
    print("\n[4] 人口栅格、建筑（按区界裁）")
    census = json.loads((SRC / "静安_人口基准.json").read_text(encoding="utf-8"))["常住人口"]
    pop_raw = read_csv("静安_人口栅格100m.csv")
    expect("栅格是 WGS-84：GHSL 同一行纬度完全相同，转过 GCJ 就不可能这样",
           pop_raw.lat.nunique() == 124 and len(np.unique(np.round(wgs_to_gcj(pop_raw.lon, pop_raw.lat)[1], 6))) > 1000,
           f"纬度取值 {pop_raw.lat.nunique()} 个")
    glon, glat = wgs_to_gcj(pop_raw.lon, pop_raw.lat)
    inside, town, how = towns.assign(glon, glat)
    pop = pd.DataFrame({"lon": np.round(glon[inside], 7), "lat": np.round(glat[inside], 7),
                        "人口_GHSL": pop_raw.人口.values[inside], "街镇": town[inside], "归属方式": how[inside]})
    factor = census / pop.人口_GHSL.sum()
    pop["人口_七普校准"] = (pop.人口_GHSL * factor).round(4)
    expect("裁后人口合计 = 七普常住人口", abs(pop.人口_七普校准.sum() - census) < 1, f"{pop.人口_七普校准.sum():.1f} / {census}")
    write_csv("人口栅格.csv", pop)

    bld_raw = read_csv("静安_建筑.csv")
    bld = bld_raw.drop_duplicates().copy()
    bld["lon"], bld["lat"] = wgs_to_gcj(bld.lon, bld.lat)
    bld["在区界内"], bld["街镇"], bld["归属方式"] = towns.assign(bld.lon, bld.lat)
    bld_in = bld[bld.在区界内].drop(columns="在区界内")
    write_csv("建筑.csv", bld_in)

    # ---------- 网格 ----------
    print("\n[5] 100 米网格")
    grid = build_grid(district, towns)
    ghsl_tree = shapely.STRtree(shapely.points(*TO_M.transform(pop.lon.values, pop.lat.values)))
    _, d = ghsl_tree.query_nearest(shapely.points(grid.x_m, grid.y_m), return_distance=True, all_matches=False)
    grid["有人口像元"] = d <= GHSL_MAX_GAP_M
    write_csv("网格100m.csv", grid)
    expect("每个格子都有街镇", grid.街镇.notna().all() and grid.街镇.nunique() == 14)
    expect("grid_id 不重复", grid.grid_id.is_unique)
    expect("网格面积 ≈ 区界面积（±1%）", abs(len(grid) / 100 / area_km2(district) - 1) < 0.01,
           f"{len(grid) / 100:.2f} / {area_km2(district):.2f} km²")
    for label, df in [("POI", poi), ("餐饮", food), ("轨道公交", transit), ("地铁站", stations)]:
        flag = df["在静安"] if "在静安" in df else df["在区界内"]
        expect(f"{label}：界内⇔有街镇", (flag == df.街镇.notna()).all())

    # ---------- 汇总 ----------
    def rate(df, flag="在区界内"):
        return {"总数": len(df), "界内": int(df[flag].sum()), "界外": int((~df[flag]).sum()),
                "界内%": round(df[flag].mean() * 100, 2)}

    pop_old = pop_raw.groupby("街镇").人口_校准.sum()
    by_town = pd.DataFrame({
        "网格数": grid.groupby("街镇").size(),
        "缝隙取最近": grid[grid.归属方式 == "最近"].groupby("街镇").size(),
        "有人口格": grid[grid.有人口像元].groupby("街镇").size(),
        "POI": poi[poi.在区界内].groupby("街镇").size(),
        "餐饮": food.groupby("街镇").size(),
        "建筑": bld_in.groupby("街镇").size(),
        "人口_原表": pop_old.round(),
        "人口_新": pop.groupby("街镇").人口_七普校准.sum().round(),
    }).fillna(0).astype(int).sort_values("网格数", ascending=False)
    by_town["人口格覆盖%"] = (by_town.有人口格 / by_town.网格数 * 100).round(1)

    report.update({
        "POI_扩": rate(poi),
        "POI_分类": {c: rate(g) for c, g in poi.groupby("category")},
        "POI_归属方式": poi.归属方式.value_counts().to_dict(),
        "餐饮": rate(food),
        "餐饮_归属方式": food.归属方式.value_counts().to_dict(),
        "轨道公交": rate(transit),
        "轨道公交_分类": {k: rate(g) for k, g in transit.groupby("kind")},
        "地铁站": {**rate(stations, "在静安"), "在静安翻转": flips[["中文名", "在静安_原", "在静安"]].to_dict("records")},
        "建筑": {"原始": len(bld_raw), "去重后": len(bld), "界内": len(bld_in), "界外裁掉": len(bld) - len(bld_in),
               "界内%": round(len(bld_in) / len(bld) * 100, 2), "归属方式": bld_in.归属方式.value_counts().to_dict()},
        "人口栅格": {"原始像元": len(pop_raw), "界内像元": len(pop), "裁掉像元": len(pop_raw) - len(pop),
                 "界内%": round(len(pop) / len(pop_raw) * 100, 2),
                 "GHSL原合计": round(float(pop_raw.人口.sum())), "GHSL界内合计": round(float(pop.人口_GHSL.sum())),
                 "原校准系数": round(census / float(pop_raw.人口.sum()), 4), "新校准系数": round(factor, 4),
                 "校准后合计": round(float(pop.人口_七普校准.sum()))},
        "网格": {"总数": len(grid), "面积_km2": len(grid) / 100, "缝隙取最近": int((grid.归属方式 == "最近").sum()),
               "有人口格": int(grid.有人口像元.sum()), "无人口格": int((~grid.有人口像元).sum())},
        "各街镇": by_town.reset_index(names="街镇").to_dict("records"),
    })
    (OUT / "准备报告.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=int), encoding="utf-8")

    print("\n" + json.dumps({k: v for k, v in report.items() if k != "各街镇"}, ensure_ascii=False, indent=1, default=int))
    print(by_town.to_string())
    print(f"\n产物写到 {OUT}")


def _pairs(transit, poi_wgs):
    m = transit.merge(poi_wgs, on="osmid", suffixes=("", "_扩"))
    return m.lon.values, m.lat.values, m.lon_扩.values, m.lat_扩.values


if __name__ == "__main__":
    main()
