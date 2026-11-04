# -*- coding: utf-8 -*-
"""自测用：一个「学员」写的 5 条检查函数（Q03、Q04、Q08、Q09、Q15），按 我的检查.py 模板的写法。"""
from qc_tools import 问题, 无法检查, 取参数, 空, 地块对象


def check_landuse_code(数据, rule):
    表 = set(取参数(rule, "代码表"))
    for p in 数据.地块:
        if not p["_代码"]:
            yield 无法检查(rule, 地块对象(p), "用地代码为空")
            continue
        for c in p["_代码"]:
            if c not in 表:
                yield 问题(rule, 地块对象(p), "错误", 实际值=c, 限值="分类表中的代码", 说明=c + " 不在分类表")


def check_landuse_depth(数据, rule):
    错 = set(取参数(rule, "必须分至小类"))
    示 = set(取参数(rule, "只写大类给提示"))
    for p in 数据.地块:
        if not p["_代码"]:
            yield 无法检查(rule, 地块对象(p), "用地代码为空")
            continue
        for c in p["_代码"]:
            if c in 错:
                yield 问题(rule, 地块对象(p), "错误", 实际值=c, 说明="居住用地没分到小类")
            elif c in 示:
                yield 问题(rule, 地块对象(p), "提示", 实际值=c, 说明="只写到大类")


def check_residential_height(数据, rule):
    上限 = 取参数(rule, "高度上限_m")
    前缀 = 取参数(rule, "住宅代码前缀")
    for p in 数据.地块:
        if not any(c.startswith(tuple(前缀)) for c in p["_代码"]):
            continue
        if 空(p.get("建筑高度_m")):
            yield 无法检查(rule, 地块对象(p), "没填建筑高度")
        elif float(p["建筑高度_m"]) > 上限:
            yield 问题(rule, 地块对象(p), "错误", 实际值=p["建筑高度_m"], 限值=上限, 说明="超高层住宅")


def check_height_zone(数据, rule):
    上限表 = 取参数(rule, "分区上限_m")
    for p in 数据.地块:
        if 空(p.get("建筑高度_m")):
            continue
        街坊 = 数据.街坊.get(str(p.get("街坊编号")))
        if 街坊 is None:
            yield 无法检查(rule, 地块对象(p), "街坊表里找不到这个街坊")
            continue
        上限 = 上限表.get(街坊.get("高度分区"))
        if 上限 is not None and float(p["建筑高度_m"]) > 上限:
            yield 问题(rule, 地块对象(p), "错误", 实际值=p["建筑高度_m"], 限值=上限, 说明="超过高度分区上限")


def check_plaza_size(数据, rule):
    上限 = 取参数(rule, "面积上限_m2")
    for p in 数据.地块:
        if not any(c in 取参数(rule, "广场代码") for c in p["_代码"]):
            continue
        if not p["_有效"]:
            yield 无法检查(rule, 地块对象(p), "几何无效")
            continue
        面积 = p["_面积"]
        if 面积 > 上限:
            严重度 = "提示" if 取参数(rule, "例外关键词") in str(p.get("备注") or "") else "错误"
            yield 问题(rule, 地块对象(p), 严重度, 实际值=round(面积), 限值=上限, 说明="广场超过 2 公顷")
