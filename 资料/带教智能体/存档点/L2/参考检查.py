# -*- coding: utf-8 -*-
"""
参考检查.py —— 规则库 21 条规则的参考实现（讲师版，存档点 L2）

每个函数：def 函数名(数据, rule)，用 问题() / 无法检查() 产出结果。
- 阈值、代码表一律从规则库的「参数」读（取参数），代码里不写数值。
- 缺数据报「无法检查」，不当成通过，也不当成 0。
- 面积一律用几何量算（EPSG:32651）；几何无效的地块不做 Q12/Q15/Q18/Q19，
  汇总类计算（Q07/Q14/Q16/Q21）退回用属性面积，并在说明里写明。
"""
import math

from qc_tools import (问题, 无法检查, 不适用, 取参数, 空, 地块对象, 街坊对象, 成对对象,
                      代码前缀命中, 量算面积, 用地成分)


# ---------------- 小工具 ----------------

def _要求整单元(数据):
    类型 = str(数据.成果信息.get("编制类型") or "")
    if "整单元" not in 类型:
        raise 不适用("编制类型是「" + 类型 + "」，这条只查整单元控规")


def _数(值):
    return float(值)


def _人口(数据):
    值 = 数据.成果信息.get("规划人口_万人")
    if 空(值):
        return None
    try:
        return float(值)
    except (TypeError, ValueError):
        return None


def _区位档(区位):
    区位 = str(区位 or "")
    if "内环内" in 区位:
        return "内环内"
    if "新城" in 区位 or "新市镇" in 区位:
        return "新城新市镇"
    if "主城区" in 区位:
        return "主城区内环外"
    return None


def _单一代码(p):
    return p["_代码"][0] if len(p["_代码"]) == 1 else None


def _面积合计(地块们):
    """返回 (合计, 备注列表, 缺面积的地块列表)。"""
    合计, 备注, 缺 = 0.0, [], []
    for p in 地块们:
        面积, 注 = 量算面积(p)
        if 面积 is None:
            缺.append(地块对象(p))
            continue
        合计 += 面积
        if 注:
            备注.append(注)
    return 合计, 备注, 缺


def _附注(备注):
    return ("；" + "；".join(备注)) if 备注 else ""


# ---------------- Q01 必填字段齐全 ----------------

def check_required(数据, rule):
    必填 = 取参数(rule, "必填字段")
    可建必填 = 取参数(rule, "可建设用地必填")
    可建前缀 = 取参数(rule, "可建设用地代码前缀")
    for p in 数据.地块:
        缺 = [k for k in 必填 if 空(p.get(k))]
        if p["_代码"] and any(代码前缀命中(c, 可建前缀) for c in p["_代码"]):
            缺 += [k for k in 可建必填 if 空(p.get(k)) and k not in 缺]
        if 缺:
            yield 问题(rule, 地块对象(p), "错误", 实际值="空", 限值="必填",
                     说明="缺：" + "、".join(缺))


# ---------------- Q02 地块编号唯一且格式统一 ----------------

def check_code(数据, rule):
    import re
    格式 = re.compile(str(取参数(rule, "编号格式")))
    次数 = {}
    for p in 数据.地块:
        编号 = p.get("地块编号")
        if 空(编号):
            yield 无法检查(rule, 地块对象(p), "地块编号为空")
            continue
        编号 = str(编号).strip()
        次数[编号] = 次数.get(编号, 0) + 1
        街坊 = "" if 空(p.get("街坊编号")) else str(p.get("街坊编号")).strip()
        if not 格式.fullmatch(编号):
            yield 问题(rule, 编号, "错误", 实际值=编号, 限值="街坊两位-地块两位，如 03-02",
                     说明="编号格式不对")
        elif 街坊 and 编号[:2] != 街坊:
            yield 问题(rule, 编号, "错误", 实际值=编号, 限值="前两位 = 街坊编号 " + 街坊,
                     说明="编号前两位和所在街坊不一致")
    for 编号 in sorted(次数):
        if 次数[编号] > 1:
            yield 问题(rule, 编号, "错误", 实际值=str(次数[编号]) + " 块", 限值="单元内唯一",
                     说明="编号 " + 编号 + " 出现了 " + str(次数[编号]) + " 次")


# ---------------- Q03 用地代码在分类表中 ----------------

def check_landuse_code(数据, rule):
    代码表 = set(str(c) for c in 取参数(rule, "代码表"))
    for p in 数据.地块:
        if not p["_代码"]:
            yield 无法检查(rule, 地块对象(p), "用地代码为空")
            continue
        不在表 = [c for c in p["_代码"] if c not in 代码表]
        if 不在表:
            yield 问题(rule, 地块对象(p), "错误", 实际值="、".join(不在表),
                     限值="表3-1/表3-2 中的代码（区分大小写）",
                     说明="用地代码 " + "、".join(不在表) + " 不在分类表中")


# ---------------- Q04 用地分类深度 ----------------

def check_landuse_depth(数据, rule):
    必须小类 = set(取参数(rule, "必须分至小类"))
    只到大类 = set(取参数(rule, "只写大类给提示"))
    for p in 数据.地块:
        if not p["_代码"]:
            yield 无法检查(rule, 地块对象(p), "用地代码为空")
            continue
        for c in p["_代码"]:
            if c in 必须小类:
                yield 问题(rule, 地块对象(p), "错误", 实际值=c, 限值="居住用地必须分至小类（如 Rr3、Rs4）",
                         说明=c + " 没有分到小类")
            elif c in 只到大类:
                yield 问题(rule, 地块对象(p), "提示", 实际值=c, 限值="一般分至中类",
                         说明=c + " 只写到大类")


# ---------------- Q05 混合用地比例 ----------------

def check_mix_ratio(数据, rule):
    下限 = _数(取参数(rule, "单类占比下限_pct"))
    合计要求 = _数(取参数(rule, "合计_pct"))
    for p in 数据.地块:
        对象 = 地块对象(p)
        if 空(p.get("混合比例")):
            if len(p["_代码"]) > 1:
                yield 无法检查(rule, 对象, "混合用地没填混合比例")
            continue
        比例 = p["_比例"]
        if 比例 is None:
            yield 无法检查(rule, 对象, p["_比例问题"] or "混合比例看不懂")
            continue
        太小 = [k + " " + format(v, "g") + "%" for k, v in 比例.items() if v <= 下限 + 1e-9]
        if 太小:
            yield 问题(rule, 对象, "错误", 实际值="、".join(太小), 限值="每类 > " + format(下限, "g") + "%",
                     说明="占比不超过 " + format(下限, "g") + "%，不构成混合用地（某类超过 "
                          + format(100 - 下限, "g") + "% 应按单一性质填报）")
        合计 = sum(比例.values())
        if abs(合计 - 合计要求) > 0.01:
            yield 问题(rule, 对象, "错误", 实际值=format(合计, "g") + "%", 限值="= " + format(合计要求, "g") + "%",
                     说明="各类占比合计不等于 " + format(合计要求, "g") + "%")


# ---------------- Q06 禁止混合的用地 ----------------

def check_mix_forbidden(数据, rule):
    任何都不行 = 取参数(rule, "不得与任何用地混合")
    不得互混 = 取参数(rule, "不得互相混合")
    for p in 数据.地块:
        代码们 = p["_代码"]
        if len(代码们) < 2:
            continue
        对象 = 地块对象(p)
        写法 = "/".join(代码们)
        for c in 代码们:
            if 代码前缀命中(c, 任何都不行):
                yield 问题(rule, 对象, "错误", 实际值=写法, 限值=c + " 不得与其他用地混合",
                         说明="准则 3.4.4 严禁 " + c + " 与其他用地混合")
                break
        for 一对 in 不得互混:
            甲, 乙 = str(一对[0]), str(一对[1])
            if any(c.startswith(甲) for c in 代码们) and any(c.startswith(乙) and not c.startswith(甲) for c in 代码们):
                yield 问题(rule, 对象, "错误", 实际值=写法, 限值=甲 + " 不得与 " + 乙 + "* 混合",
                         说明="准则 3.4.4 严禁 " + 甲 + " 与 " + 乙 + "* 混合")


# ---------------- Q07 街坊开发强度 ----------------

def _强度区档(值):
    文字 = str(值 or "").strip()
    return 文字[:-1] if 文字.endswith("级") else 文字


def _上限说明(值):
    return "不设上限" if (值 is None or isinstance(值, str)) else format(float(值), ".1f")


def check_intensity(数据, rule):
    适用区位 = str(取参数(rule, "适用区位"))
    区位 = str(数据.成果信息.get("区位") or "")
    if 适用区位 not in 区位:
        raise 不适用("区位是「" + 区位 + "」，表4-1 只用于" + 适用区位)
    表 = {"住宅": 取参数(rule, "住宅"), "商办": 取参数(rule, "商办")}
    住宅代码 = set(取参数(rule, "住宅代码"))
    商办前缀 = 取参数(rule, "商办代码前缀")
    半径 = _数(取参数(rule, "站点服务半径_m"))
    占比下限 = _数(取参数(rule, "特定强度用地占比下限"))
    计入状态 = set(取参数(rule, "计入的站点状态"))

    from shapely.ops import unary_union
    站点 = [s for s in 数据.站点 if s.get("状态") in 计入状态 and s.get("_点") is not None]
    服务区 = unary_union([s["_点"].buffer(半径, 64) for s in 站点]) if 站点 else None
    没有站点文件 = 数据.文件.get("轨交站点") is None

    判别 = {"住宅": lambda c: c in 住宅代码, "商办": lambda c: 代码前缀命中(c, 商办前缀)}
    按街坊 = {}
    for p in 数据.地块:
        if not 空(p.get("街坊编号")):
            按街坊.setdefault(str(p["街坊编号"]).strip(), []).append(p)

    for 编号 in sorted(按街坊):
        对象 = 街坊对象(编号)
        街坊 = 数据.街坊.get(编号)
        for 类 in ("住宅", "商办"):
            地, 建, 缺, 备注 = 0.0, 0.0, [], []
            for p in 按街坊[编号]:
                相关 = [(c, 份) for c, 份 in 用地成分(p) if 判别[类](c)]
                if not 相关:
                    continue
                if any(份 is None for c, 份 in 相关):
                    缺.append(地块对象(p) + " 是混合用地但没填混合比例")
                    continue
                面积, 注 = 量算面积(p)
                if 面积 is None:
                    缺.append(注)
                    continue
                if 空(p.get("容积率")):
                    缺.append(地块对象(p) + " 缺容积率")
                    continue
                if 注:
                    备注.append(注)
                for c, 份 in 相关:
                    地 += 面积 * 份
                    建 += 面积 * 份 * float(p["容积率"])
            if 地 == 0 and not 缺:
                continue
            if 街坊 is None:
                yield 无法检查(rule, 对象, 类 + "：街坊表里没有街坊 " + 编号)
                continue
            if 缺:
                yield 无法检查(rule, 对象, 类 + "：" + "；".join(缺))
                continue
            档 = _强度区档(街坊.get("强度区"))
            if 档 not in 表[类]:
                yield 无法检查(rule, 对象, 类 + "：强度区「" + str(街坊.get("强度区")) + "」不认识")
                continue
            一档 = list(表[类][档])
            基本下, 基本上, 特定上 = 一档[0], 一档[1], 一档[2]
            不含上限 = len(一档) > 3 and "不含" in str(一档[3])
            if 服务区 is not None and 街坊.get("_有效"):
                占比 = 街坊["_几何"].intersection(服务区).area / 街坊["_面积"]
            else:
                占比 = 0.0
            均 = 建 / 地
            用特定 = 占比 >= 占比下限 - 1e-9 and 特定上 is not None
            if 用特定:
                上限 = None if isinstance(特定上, str) else float(特定上)
                排他 = False
                档说明 = 档 + "级特定强度；站点 " + format(半径, "g") + " 米范围占街坊 " + format(占比, ".0%")
            else:
                上限 = None if (基本上 is None or isinstance(基本上, str)) else float(基本上)
                排他 = 不含上限
                档说明 = 档 + "级基本强度；站点 " + format(半径, "g") + " 米范围占街坊 " + format(占比, ".0%")
            超 = 上限 is not None and ((均 >= 上限 - 1e-9) if 排他 else (均 > 上限 + 1e-9))
            if 超 and 没有站点文件 and 特定上 is not None and not 用特定:
                yield 无法检查(rule, 对象, 类 + "：平均容积率 " + format(均, ".2f") + " 超过基本强度，但没有轨交站点文件，判断不了能否用特定强度")
                continue
            if 超:
                yield 问题(rule, 对象, "错误", 实际值=round(均, 2),
                         限值=("< " if 排他 else "≤ ") + _上限说明(上限) + "（" + 档说明 + "）",
                         说明=类 + "用地平均容积率 " + format(均, ".2f") + " 超过上限" + _附注(备注))
            elif 基本下 is not None and not isinstance(基本下, str) and 均 < float(基本下) - 1e-9:
                yield 问题(rule, 对象, "提示", 实际值=round(均, 2), 限值="≥ " + format(float(基本下), ".1f"),
                         说明=类 + "用地平均容积率低于 " + 档 + "级基本强度下限" + _附注(备注))


# ---------------- Q08 不得建设超高层住宅 ----------------

def check_residential_height(数据, rule):
    前缀 = 取参数(rule, "住宅代码前缀")
    上限 = _数(取参数(rule, "高度上限_m"))
    for p in 数据.地块:
        if not any(代码前缀命中(c, 前缀) for c in p["_代码"]):
            continue
        高 = p.get("建筑高度_m")
        if 空(高):
            yield 无法检查(rule, 地块对象(p), "住宅地块没填建筑高度_m")
            continue
        if float(高) > 上限 + 1e-9:
            yield 问题(rule, 地块对象(p), "错误", 实际值=float(高), 限值="≤ " + format(上限, "g") + " 米",
                     说明="住宅建筑高度 " + format(float(高), "g") + " 米，超过 " + format(上限, "g") + " 米即超高层")


# ---------------- Q09 高度分区 ----------------

def check_height_zone(数据, rule):
    上限表 = 取参数(rule, "分区上限_m")
    for p in 数据.地块:
        高 = p.get("建筑高度_m")
        if 空(高):
            continue  # 适用：填了建筑高度的地块
        编号 = "" if 空(p.get("街坊编号")) else str(p.get("街坊编号")).strip()
        街坊 = 数据.街坊.get(编号)
        if 街坊 is None:
            yield 无法检查(rule, 地块对象(p), "街坊编号「" + 编号 + "」在街坊表里找不到，不知道高度分区")
            continue
        分区 = str(街坊.get("高度分区") or "").strip()
        if 分区 not in 上限表:
            yield 无法检查(rule, 地块对象(p), "街坊 " + 编号 + " 的高度分区「" + 分区 + "」不认识")
            continue
        上限 = 上限表[分区]
        if 上限 is None:
            continue
        if float(高) > float(上限) + 1e-9:
            yield 问题(rule, 地块对象(p), "错误", 实际值=float(高), 限值="≤ " + format(float(上限), "g") + " 米（" + 分区 + "）",
                     说明="建筑高度超过所在街坊 " + 编号 + " 的" + 分区 + "高度分区上限")


# ---------------- Q10 工业用地容积率 ----------------

def check_industrial_far(数据, rule):
    工业 = set(取参数(rule, "工业代码"))
    下限 = _数(取参数(rule, "容积率下限"))
    例外 = str(取参数(rule, "例外关键词"))
    for p in 数据.地块:
        代码 = _单一代码(p)
        if 代码 not in 工业:
            continue
        容积率 = p.get("容积率")
        if 空(容积率):
            yield 无法检查(rule, 地块对象(p), "工业地块没填容积率")
            continue
        if float(容积率) < 下限 - 1e-9 and 例外 not in str(p.get("备注") or ""):
            yield 问题(rule, 地块对象(p), "提示", 实际值=float(容积率), 限值="≥ " + format(下限, "g"),
                     说明="工业用地容积率不宜低于 " + format(下限, "g") + "（备注没写「" + 例外 + "」）")


# ---------------- Q11 基础教育设施数量 ----------------

def check_school_count(数据, rule):
    _要求整单元(数据)
    人口 = _人口(数据)
    if 人口 is None:
        yield 无法检查(rule, "单元", "成果信息里没有规划人口_万人")
        return
    门槛 = 取参数(rule, "每所服务人口_万人")
    计数表 = 取参数(rule, "代码计数")
    已有 = {类: 0 for 类 in 门槛}
    for p in 数据.地块:
        for c in p["_代码"]:
            for 类 in 计数表.get(c, []) or []:
                已有[类] = 已有.get(类, 0) + 1
    for 类, 每所 in 门槛.items():
        需要 = math.ceil(round(人口 / float(每所), 9))
        if 已有.get(类, 0) < 需要:
            yield 问题(rule, "单元/" + 类, "错误", 实际值=str(已有.get(类, 0)) + " 所", 限值="≥ " + str(需要) + " 所",
                     说明="规划人口 " + format(人口, "g") + " 万人，每 " + format(float(每所), "g") + " 万人应配一所" + 类)


# ---------------- Q12 新建中小学南北向长度 ----------------

def check_school_ns_length(数据, rule):
    最小 = 取参数(rule, "南北向最小长度_m")
    状态 = str(取参数(rule, "适用状态"))
    for p in 数据.地块:
        if str(p.get("规划状态") or "").strip() != 状态:
            continue
        相关 = [c for c in p["_代码"] if c in 最小]
        if not 相关:
            continue
        if not p["_有效"]:
            yield 无法检查(rule, 地块对象(p), "几何无效或为空（见 Q20），量不了南北向长度")
            continue
        需要 = max(float(最小[c]) for c in 相关)
        minx, miny, maxx, maxy = p["_几何"].bounds
        长度 = maxy - miny
        if 长度 < 需要 - 1e-9:
            yield 问题(rule, 地块对象(p), "错误", 实际值=round(长度, 1), 限值="≥ " + format(需要, "g") + " 米",
                     说明="新建 " + "/".join(相关) + " 南北向最大长度 " + format(长度, ".1f") + " 米，不足 " + format(需要, "g") + " 米")


# ---------------- Q13 需独立用地的社区设施 ----------------

def check_independent_facility(数据, rule):
    _要求整单元(数据)
    for 设施 in 取参数(rule, "设施"):
        名称, 代码 = str(设施["名称"]), str(设施["代码"])
        独立 = [p for p in 数据.地块 if 代码 in p["_代码"] and 名称 in str(p.get("配套设施") or "")]
        if 独立:
            continue
        别处 = [地块对象(p) for p in 数据.地块 if 名称 in str(p.get("配套设施") or "")]
        说明 = "没有写明" + 名称 + "的 " + 代码 + " 地块"
        if 别处:
            说明 += "；只写在 " + "、".join(别处) + " 的配套设施里 = 未独立用地"
        yield 问题(rule, "单元/" + 名称, "错误", 实际值=("、".join(别处) or "无"),
                 限值="一块 " + 代码 + " 地块，配套设施写明" + 名称, 说明=说明)


# ---------------- Q14 独立用地的小型公共空间比例 ----------------

def check_small_public_space(数据, rule):
    _要求整单元(数据)
    信息 = 数据.成果信息
    if 数据.单元 is None or not 数据.单元.get("_有效"):
        yield 无法检查(rule, "单元", "单元边界缺失或无效，算不出单元总用地")
        return
    总 = 数据.单元["_面积"]
    绿码 = set(取参数(rule, "公共绿地代码"))
    绿上限 = _数(取参数(rule, "公共绿地面积上限_m2"))
    场码 = set(取参数(rule, "广场代码"))
    场上限 = _数(取参数(rule, "广场面积上限_m2"))
    分子, 备注 = 0.0, []
    for p in 数据.地块:
        代码 = _单一代码(p)
        if 代码 not in 绿码 and 代码 not in 场码:
            continue
        面积, 注 = 量算面积(p)
        if 面积 is None:
            yield 无法检查(rule, "单元", 注)
            return
        if 注:
            备注.append(注)
        if (代码 in 绿码 and 面积 < 绿上限) or (代码 in 场码 and 面积 < 场上限):
            分子 += 面积
    比例 = 分子 / 总 * 100
    区位 = _区位档(信息.get("区位"))
    功能 = str(信息.get("功能区域") or "")
    if 区位 is None:
        yield 无法检查(rule, "单元", "成果信息的区位「" + str(信息.get("区位")) + "」对不上表5-5")
        return
    if "居住社区" in 功能:
        人口 = _人口(数据)
        if 人口 is None:
            yield 无法检查(rule, "单元", "缺规划人口，算不出居住人口密度")
            return
        密度 = 人口 / (总 / 1e6)
        档位 = 0 if 密度 > _数(取参数(rule, "人口密度分界_万人每平方公里")) else 1
        标准 = float(取参数(rule, "居住社区")[区位][档位])
        档说明 = "居住社区·" + 区位 + "·人口密度 " + format(密度, ".2f") + " 万人/km²"
    elif "公共活动中心" in 功能:
        标准 = float(取参数(rule, "公共活动中心区")[区位])
        档说明 = "公共活动中心区·" + 区位
    else:
        yield 无法检查(rule, "单元", "功能区域「" + 功能 + "」对不上表5-5")
        return
    if 比例 >= 标准 - 1e-9:
        return
    折减后 = 标准 * _数(取参数(rule, "折减系数"))
    地区类型 = str(信息.get("地区类型") or "")
    实际 = format(比例, ".2f") + "%"
    if "建成区" in 地区类型 and 比例 >= 折减后 - 1e-9:
        yield 问题(rule, "单元", "待确认", 实际值=实际,
                 限值="≥ " + format(标准, "g") + "%（确有困难的建成区可按 " + format(折减后, "g") + "%）",
                 说明=档说明 + "；落在折减区间，要人判断是否属于「确有困难的建成区」，不足部分须由地块内公共开放空间补足" + _附注(备注))
    else:
        yield 问题(rule, "单元", "错误", 实际值=实际, 限值="≥ " + format(标准, "g") + "%",
                 说明=档说明 + "；独立用地的小型公共空间比例不足" + _附注(备注))


# ---------------- Q15 单个广场面积 ----------------

def check_plaza_size(数据, rule):
    广场码 = set(取参数(rule, "广场代码"))
    上限 = _数(取参数(rule, "面积上限_m2"))
    例外 = str(取参数(rule, "例外关键词"))
    for p in 数据.地块:
        if not any(c in 广场码 for c in p["_代码"]):
            continue
        if not p["_有效"]:
            yield 无法检查(rule, 地块对象(p), "几何无效或为空（见 Q20），量不了面积")
            continue
        面积 = p["_面积"]
        if 面积 <= 上限 + 1e-9:
            continue
        if 例外 in str(p.get("备注") or ""):
            yield 问题(rule, 地块对象(p), "提示", 实际值=round(面积), 限值="≤ " + format(上限, "g") + " m²",
                     说明="备注写了「" + 例外 + "」，按例外处理，请人核实")
        else:
            yield 问题(rule, 地块对象(p), "错误", 实际值=round(面积), 限值="≤ " + format(上限, "g") + " m²",
                     说明="单个广场几何面积 " + format(面积, ".0f") + " m²，超过 2 公顷")


# ---------------- Q16 人均公共绿地 ----------------

def check_green_per_capita(数据, rule):
    _要求整单元(数据)
    人口 = _人口(数据)
    if 人口 is None:
        yield 无法检查(rule, "单元", "成果信息里没有规划人口_万人")
        return
    绿码 = set(取参数(rule, "公共绿地代码"))
    下限 = _数(取参数(rule, "人均下限_m2"))
    合计, 备注, 缺 = _面积合计([p for p in 数据.地块 if _单一代码(p) in 绿码])
    if 缺:
        yield 无法检查(rule, "单元", "这些公共绿地没有面积：" + "、".join(缺))
        return
    人均 = 合计 / (人口 * 1e4)
    if 人均 >= 下限 - 1e-9:
        return
    地区类型 = str(数据.成果信息.get("地区类型") or "")
    实际 = format(人均, ".2f") + " m²/人"
    if "新建" in 地区类型:
        yield 问题(rule, "单元", "错误", 实际值=实际, 限值="≥ " + format(下限, "g") + " m²/人",
                 说明="新建地区人均社区级及以下公共绿地不得低于 " + format(下限, "g") + " m²" + _附注(备注))
    elif "建成区" in 地区类型:
        yield 问题(rule, "单元", "提示", 实际值=实际, 限值="≥ " + format(下限, "g") + " m²/人",
                 说明="建成区不强制，应结合城市更新增加公共绿地" + _附注(备注))
    else:
        yield 无法检查(rule, "单元", "地区类型「" + 地区类型 + "」看不出是新建地区还是建成区")


# ---------------- Q17 地块绿地率 ----------------

def check_green_ratio(数据, rule):
    住宅前缀 = 取参数(rule, "住宅代码前缀")
    住宅下限 = 取参数(rule, "住宅下限_pct")
    公建前缀 = 取参数(rule, "公建代码前缀")
    公建下限 = _数(取参数(rule, "公建新建下限_pct"))
    for p in 数据.地块:
        状态 = str(p.get("规划状态") or "").strip()
        if not 状态 or 状态 == "保留":
            continue
        限值, 类 = None, ""
        if any(代码前缀命中(c, 住宅前缀) for c in p["_代码"]) and 状态 in 住宅下限:
            限值, 类 = float(住宅下限[状态]), 状态 + "住宅组团用地"
        elif 状态 == "新建" and any(代码前缀命中(c, 公建前缀) for c in p["_代码"]):
            限值, 类 = 公建下限, "新建学校/医院/文化设施"
        if 限值 is None:
            continue
        绿 = p.get("绿地率_pct")
        if 空(绿):
            yield 无法检查(rule, 地块对象(p), 类 + "没填绿地率_pct")
            continue
        if float(绿) < 限值 - 1e-9:
            yield 问题(rule, 地块对象(p), "错误", 实际值=format(float(绿), "g") + "%", 限值="≥ " + format(限值, "g") + "%",
                     说明=类 + "绿地率不得低于 " + format(限值, "g") + "%")


# ---------------- Q18 用地面积与几何面积一致 ----------------

def check_area_consistency(数据, rule):
    上限 = _数(取参数(rule, "相对误差上限_pct"))
    for p in 数据.地块:
        if not p["_有效"]:
            yield 无法检查(rule, 地块对象(p), "几何无效或为空（见 Q20），先修几何")
            continue
        if 空(p.get("用地面积_m2")):
            yield 无法检查(rule, 地块对象(p), "用地面积_m2 为空")
            continue
        属性 = float(p["用地面积_m2"])
        if 属性 <= 0:
            yield 问题(rule, 地块对象(p), "错误", 实际值=属性, 限值="> 0", 说明="用地面积不是正数")
            continue
        差 = (p["_面积"] - 属性) / 属性 * 100
        if abs(差) > 上限 + 1e-9:
            yield 问题(rule, 地块对象(p), "错误", 实际值="量算 " + format(p["_面积"], ".0f") + " m²",
                     限值="属性 " + format(属性, "g") + " m² ±" + format(上限, "g") + "%",
                     说明="相差 " + format(差, "+.1f") + "%")


# ---------------- Q19 地块之间不重叠 ----------------

def check_overlap(数据, rule):
    from shapely import STRtree
    下限 = _数(取参数(rule, "重叠面积下限_m2"))
    有效 = [p for p in 数据.地块 if p["_有效"]]
    for p in 数据.地块:
        if not p["_有效"]:
            yield 无法检查(rule, 地块对象(p), "几何无效或为空（见 Q20），没参加重叠检查")
    几何们 = [p["_几何"] for p in 有效]
    if not 几何们:
        return
    树 = STRtree(几何们)
    for i, 几何 in enumerate(几何们):
        for j in sorted(int(x) for x in 树.query(几何)):
            if j <= i:
                continue
            面积 = 几何.intersection(几何们[j]).area
            if 面积 > 下限:
                yield 问题(rule, 成对对象(地块对象(有效[i]), 地块对象(有效[j])), "错误",
                         实际值=format(面积, ".1f") + " m²", 限值="≤ " + format(下限, "g") + " m²",
                         说明=地块对象(有效[i]) + " 和 " + 地块对象(有效[j]) + " 重叠 " + format(面积, ".0f") + " m²")


# ---------------- Q20 几何有效 ----------------

def check_geometry_valid(数据, rule):
    for p in 数据.地块:
        if p["_有效"]:
            continue
        yield 问题(rule, 地块对象(p), "错误", 实际值=p["_几何问题"] or "几何无效", 限值="有效的面",
                 说明="几何无效，先退回修正；这块地不做 Q12、Q15、Q18、Q19")


# ---------------- Q21 说明书与指标表一致 ----------------

def _表里的值(数据, 项目, 单位, 学校代码, 绿码):
    """返回 (指标表算出的值, 备注) 或 (None, 原因)。"""
    if 项目 == "规划人口":
        值 = _人口(数据)
        return (值, "") if 值 is not None else (None, "成果信息里没有规划人口_万人")
    if 项目 == "总用地":
        if 数据.单元 is None or not 数据.单元.get("_有效"):
            return None, "单元边界缺失或无效"
        return 数据.单元["_面积"] / 1e4, ""
    if 项目 == "公共绿地":
        合计, 备注, 缺 = _面积合计([p for p in 数据.地块 if _单一代码(p) in 绿码])
        if 缺:
            return None, "这些公共绿地没有面积：" + "、".join(缺)
        return 合计 / 1e4, _附注(备注)
    if 项目 == "总建筑面积":
        合计, 备注, 缺容积率 = 0.0, [], []
        for p in 数据.地块:
            if 空(p.get("容积率")):
                if not 空(p.get("建筑高度_m")):   # 有建筑、没容积率：这块地的建筑面积算不进来
                    缺容积率.append(地块对象(p))
                continue
            面积, 注 = 量算面积(p)
            if 面积 is None:
                return None, 注
            if 注:
                备注.append(注)
            合计 += 面积 * float(p["容积率"])
        if 缺容积率:
            备注.append("、".join(缺容积率) + " 缺容积率，没计入")
        return 合计 / 1e4, _附注(备注)
    if 项目 in 学校代码:
        代码 = str(学校代码[项目])
        return float(sum(1 for p in 数据.地块 if 代码 in p["_代码"])), ""
    return None, "不认识的项目"


def compare_claims(数据, rule):
    if 数据.说明书 is None:
        raise 不适用("成果里没有说明书")
    if 数据.声明问题:
        yield 无法检查(rule, "说明书", 数据.声明问题)
        return
    if 数据.声明 is None:
        yield 无法检查(rule, "说明书", "没有 claims.json：说明书里的数字要先由模型读出来写进 claims.json")
        return
    容差 = _数(取参数(rule, "面积容差_pct"))
    比对项 = 取参数(rule, "比对项")
    学校代码 = 取参数(rule, "学校代码")
    绿码 = set(取参数(rule, "公共绿地代码"))
    条目们 = 数据.声明.get("数字") if isinstance(数据.声明, dict) else None
    if not isinstance(条目们, list) or not 条目们:
        yield 无法检查(rule, "说明书", "claims.json 里没有「数字」列表")
        return
    for 条 in 条目们:
        项目 = str((条 or {}).get("项目") or "").strip()
        对象 = "说明书/" + (项目 or "?")
        if 项目 not in 比对项:
            yield 无法检查(rule, 对象, "不认识的比对项「" + 项目 + "」；认识的：" + "、".join(比对项))
            continue
        单位 = str(条.get("单位") or "").strip()
        应为 = str(比对项[项目])
        if 单位 != 应为:
            yield 无法检查(rule, 对象, "单位应为「" + 应为 + "」，claims.json 里写的是「" + 单位 + "」")
            continue
        try:
            说明书值 = float(条.get("值"))
        except (TypeError, ValueError):
            yield 无法检查(rule, 对象, "值「" + str(条.get("值")) + "」不是数字")
            continue
        表值, 备注 = _表里的值(数据, 项目, 单位, 学校代码, 绿码)
        if 表值 is None:
            yield 无法检查(rule, 对象, 备注)
            continue
        if 应为 == "所":
            不符 = round(说明书值) != round(表值)
            差说明 = "数量要相等"
        else:
            差 = (说明书值 - 表值) / 表值 * 100 if 表值 else float("inf")
            不符 = abs(差) > 容差 + 1e-9
            差说明 = "相差 " + format(差, "+.1f") + "%，超过 " + format(容差, "g") + "%"
        if 不符:
            yield 问题(rule, 对象, "错误", 实际值="指标表 " + format(表值, ".4g") + " " + 单位,
                     限值="说明书 " + format(说明书值, "g") + " " + 单位,
                     说明="说明书与指标表不一致：" + 差说明 + 备注)
