#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qc_tools.py —— 控规成果质检工具（框架）

框架只做三件事：读成果数据、调用检查函数、写 findings.json。
「判定」全部在检查函数里：
  参考检查.py   讲师的参考实现（L2 过关后由 progress.py merge 并入）
  我的检查.py   你自己写的；和参考检查同名的函数，优先用你的

用法
  python3 qc_agent/qc_tools.py --data data/qc --out qc_agent/报告/findings.json
  python3 qc_agent/qc_tools.py --data data/qc --rules Q03,Q08 --out qc_agent/临时/findings.json
  python3 qc_agent/qc_tools.py --list

选项
  --data      成果目录：*_地块.geojson、*_街坊.geojson、*_单元边界.geojson、*_成果信息.json
              （必需），*_说明书.md、*_轨交站点.csv（可选）
  --out       findings.json 写到哪
  --rules     要跑哪些规则，逗号分隔；默认 all = 规则库里全部
  --rulebook  规则库，默认和本文件同目录的 规则库.yaml
  --claims    模型从说明书读出的数字（Q21 用）；默认 --out 同目录的 claims.json
  --只用我的   只加载 我的检查.py（L2 验收用）
  --list      列出每条规则由哪个函数实现，然后退出

退出码：0 正常；2 参数或数据有错；3 有检查函数出错（结果照样写出，出错的规则记在「未检查」里）

检查函数怎么写：看 我的检查.py 开头的说明。
"""
import argparse
import datetime
import importlib.util
import json
import math
import os
import re
import sys
import traceback
from pathlib import Path

sys.dont_write_bytecode = True
for _流 in (sys.stdout, sys.stderr):
    try:
        _流.reconfigure(encoding="utf-8")
    except Exception:
        pass

框架版本 = "1.0"
本目录 = Path(__file__).resolve().parent
严重度顺序 = ["错误", "待确认", "提示", "无法检查"]
量算坐标系 = 32651  # UTM 51N，单位米


# ============================================================
# 给检查函数用的工具
# ============================================================

class 不适用(Exception):
    """检查函数里 raise 不适用("原因")：这条规则对这份成果不适用，记进「未检查」。"""


class 参数缺失(Exception):
    """规则库里这条规则的「参数」缺了某个键。"""


class 数据错误(Exception):
    """成果目录缺文件、文件读不了。"""


def 空(值):
    """None、空字符串、只有空格的字符串都算空。0 不算空。"""
    return 值 is None or (isinstance(值, str) and 值.strip() == "")


def _整理(值):
    if isinstance(值, float):
        if math.isnan(值) or math.isinf(值):
            return str(值)
        return round(值, 2)
    return 值


def 问题(rule, 对象, 严重度, 实际值=None, 限值=None, 说明=""):
    """生成一条问题（finding）。严重度：错误 / 待确认 / 提示 / 无法检查。"""
    if 严重度 not in 严重度顺序:
        raise ValueError("严重度只能是：" + "、".join(严重度顺序) + "，收到：" + str(严重度))
    return {
        "规则": rule["id"],
        "对象": str(对象),
        "严重度": 严重度,
        "实际值": _整理(实际值),
        "限值": _整理(限值),
        "说明": str(说明 or ""),
    }


def 无法检查(rule, 对象, 说明):
    """数据缺了或判断不了：不是「通过」，也不是 0。"""
    return 问题(rule, 对象, "无法检查", 说明=说明)


def 取参数(rule, 键):
    """从规则库里这条规则的「参数」取值。阈值一律这样取，不要写死在代码里。"""
    参数表 = rule.get("参数") or {}
    if not isinstance(参数表, dict) or 键 not in 参数表:
        raise 参数缺失("规则库里 " + str(rule.get("id")) + " 的「参数」缺少「" + 键 + "」")
    return 参数表[键]


def 地块对象(p):
    """这块地在报告里的名字：地块编号；没有编号时是「要素#序号」。"""
    编号 = p.get("地块编号")
    if 空(编号):
        return "要素#" + str(p["_序号"] + 1)
    return str(编号).strip()


def 街坊对象(编号):
    return "街坊" + str(编号).strip()


def 成对对象(a, b):
    return "&".join(sorted([str(a), str(b)]))


def 代码前缀命中(代码, 前缀们):
    """代码是否以其中某个前缀开头（区分大小写）。前缀们可以是字符串或列表。"""
    if isinstance(前缀们, str):
        前缀们 = [前缀们]
    return any(str(代码).startswith(str(前缀)) for 前缀 in 前缀们)


def 量算面积(p):
    """返回 (面积_m2, 备注)。几何有效：量算面积；几何无效但属性有面积：属性面积 + 备注；都没有：(None, 原因)。"""
    if p.get("_有效"):
        return p["_面积"], None
    属性 = p.get("用地面积_m2")
    if not 空(属性):
        try:
            return float(属性), 地块对象(p) + " 几何无效，按属性面积计"
        except (TypeError, ValueError):
            pass
    return None, 地块对象(p) + " 几何无效且没有用地面积"


def 用地成分(p):
    """[(代码, 占比)]。单一用地占比 1.0；混合用地按混合比例；混合用地没填比例时占比为 None。"""
    if p.get("_比例"):
        return [(代码, 百分比 / 100.0) for 代码, 百分比 in p["_比例"].items()]
    if len(p["_代码"]) == 1:
        return [(p["_代码"][0], 1.0)]
    return [(代码, None) for 代码 in p["_代码"]]


def 解析混合比例(文字):
    """'C2:50;C8:50' → ({'C2': 50.0, 'C8': 50.0}, None)；看不懂 → (None, 原因)；没填 → (None, None)。"""
    if 空(文字):
        return None, None
    结果 = {}
    for 段 in re.split(r"[;；,，]", str(文字)):
        段 = 段.strip()
        if not 段:
            continue
        m = re.fullmatch(r"([A-Za-z][A-Za-z0-9]*)\s*[:：]\s*([0-9]+(?:\.[0-9]+)?)\s*%?", 段)
        if not m:
            return None, "混合比例「" + str(文字) + "」看不懂（应写成 C2:50;C8:50）"
        结果[m.group(1)] = float(m.group(2))
    return (结果 or None), (None if 结果 else "混合比例「" + str(文字) + "」是空的")


# ============================================================
# 读成果数据
# ============================================================

_转换器 = None


def 投影(几何):
    """经纬度（EPSG:4326）→ EPSG:32651（米）。"""
    global _转换器
    import numpy as np
    import shapely
    from pyproj import Transformer
    if _转换器 is None:
        _转换器 = Transformer.from_crs(4326, 量算坐标系, always_xy=True)

    def _变换(xy):
        x, y = _转换器.transform(xy[:, 0], xy[:, 1])
        return np.column_stack([x, y])

    return shapely.transform(几何, _变换)


def _几何问题说明(几何):
    from shapely.validation import explain_validity
    原文 = explain_validity(几何)
    for 英, 中 in (("Ring Self-intersection", "环自相交"), ("Self-intersection", "自相交"),
                  ("Too few points", "点太少"), ("Hole lies outside shell", "洞在外环外面"),
                  ("Nested shells", "外环嵌套"), ("Interior is disconnected", "内部不连通")):
        if 原文.startswith(英):
            return 中 + "（" + 原文 + "）"
    return 原文


def _读json(路径):
    try:
        with open(路径, encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception as e:
        raise 数据错误("读不了 " + str(路径) + "：" + str(e))


def _找文件(目录, 后缀, 必需=True):
    命中 = sorted(p for p in 目录.glob("*" + 后缀) if p.is_file())
    if not 命中:
        if 必需:
            raise 数据错误(str(目录) + " 里没有 *" + 后缀)
        return None
    if len(命中) > 1:
        raise 数据错误(str(目录) + " 里有多个 *" + 后缀 + "：" + "、".join(p.name for p in 命中))
    return 命中[0]


def _要素几何(要素):
    from shapely.geometry import shape
    g = 要素.get("geometry")
    if not g:
        return None, "空几何"
    try:
        几何 = shape(g)
    except Exception as e:
        return None, "几何读不了：" + str(e)
    if 几何.is_empty:
        return None, "空几何"
    几何 = 投影(几何)
    if not 几何.is_valid:
        return 几何, _几何问题说明(几何)
    return 几何, None


class 成果数据:
    """一份控规成果。检查函数通过它拿数据（见 我的检查.py 开头的说明）。"""

    def __init__(self, 目录, 声明路径=None):
        self.目录 = Path(目录)
        if not self.目录.is_dir():
            raise 数据错误("成果目录不存在：" + str(目录))
        self.文件 = {}
        self.地块 = self._读地块(_找文件(self.目录, "_地块.geojson"))
        self.街坊 = self._读街坊(_找文件(self.目录, "_街坊.geojson"))
        self.单元 = self._读单元(_找文件(self.目录, "_单元边界.geojson"))
        路径 = _找文件(self.目录, "_成果信息.json")
        self.文件["成果信息"] = 路径
        self.成果信息 = _读json(路径)
        路径 = _找文件(self.目录, "_说明书.md", 必需=False)
        self.文件["说明书"] = 路径
        self.说明书 = 路径.read_text(encoding="utf-8-sig") if 路径 else None
        路径 = _找文件(self.目录, "_轨交站点.csv", 必需=False)
        self.文件["轨交站点"] = 路径
        self.站点 = self._读站点(路径) if 路径 else []
        self.声明 = None          # claims.json 的内容（dict）
        self.声明问题 = None      # claims.json 读不了的原因
        self.声明路径 = None
        if 声明路径 is not None and Path(声明路径).is_file():
            self.声明路径 = Path(声明路径)
            try:
                self.声明 = _读json(声明路径)
            except 数据错误 as e:
                self.声明问题 = str(e)

    def _读地块(self, 路径):
        self.文件["地块"] = 路径
        数据 = _读json(路径)
        地块 = []
        for 序号, 要素 in enumerate(数据.get("features") or []):
            p = dict(要素.get("properties") or {})
            几何, 几何问题 = _要素几何(要素)
            代码 = p.get("用地代码")
            p["_序号"] = 序号
            p["_几何"] = 几何
            p["_有效"] = 几何 is not None and 几何问题 is None
            p["_几何问题"] = 几何问题
            p["_面积"] = 几何.area if p["_有效"] else None
            p["_代码"] = [] if 空(代码) else [c.strip() for c in re.split(r"[/／]", str(代码)) if c.strip()]
            p["_比例"], p["_比例问题"] = 解析混合比例(p.get("混合比例"))
            地块.append(p)
        return 地块

    def _读街坊(self, 路径):
        self.文件["街坊"] = 路径
        结果 = {}
        for 要素 in _读json(路径).get("features") or []:
            p = dict(要素.get("properties") or {})
            几何, 几何问题 = _要素几何(要素)
            p["_几何"] = 几何
            p["_有效"] = 几何 is not None and 几何问题 is None
            p["_面积"] = 几何.area if p["_有效"] else None
            编号 = p.get("街坊编号")
            if not 空(编号):
                结果[str(编号).strip()] = p
        return 结果

    def _读单元(self, 路径):
        self.文件["单元边界"] = 路径
        要素们 = _读json(路径).get("features") or []
        if not 要素们:
            return None
        p = dict(要素们[0].get("properties") or {})
        几何, 几何问题 = _要素几何(要素们[0])
        p["_几何"] = 几何
        p["_有效"] = 几何 is not None and 几何问题 is None
        p["_面积"] = 几何.area if p["_有效"] else None
        return p

    def _读站点(self, 路径):
        import csv
        from shapely.geometry import Point
        站点 = []
        with open(路径, encoding="utf-8-sig", newline="") as f:
            for 行 in csv.DictReader(f):
                行 = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in 行.items() if k}
                try:
                    行["_点"] = 投影(Point(float(行["lon"]), float(行["lat"])))
                except Exception:
                    行["_点"] = None
                站点.append(行)
        return 站点


# ============================================================
# 加载规则库和检查函数
# ============================================================

def 读规则库(路径):
    try:
        import yaml
    except ImportError:
        raise 数据错误("缺 PyYAML：先运行 python3 -m pip install pyyaml")
    try:
        with open(路径, encoding="utf-8-sig") as f:
            规则库 = yaml.safe_load(f)
    except FileNotFoundError:
        raise 数据错误("找不到规则库：" + str(路径))
    except Exception as e:
        raise 数据错误("规则库读不了（YAML 格式有错？）：" + str(e))
    if not isinstance(规则库, dict) or not isinstance(规则库.get("规则"), list):
        raise 数据错误("规则库里要有「规则」列表：" + str(路径))
    for i, 规则 in enumerate(规则库["规则"]):
        if not isinstance(规则, dict) or 空(规则.get("id")):
            raise 数据错误("规则库第 " + str(i + 1) + " 条规则没有 id")
        规则["id"] = str(规则["id"]).strip()
    return 规则库


def _加载模块(路径, 名字):
    if not 路径.is_file():
        return None
    规格 = importlib.util.spec_from_file_location(名字, str(路径))
    模块 = importlib.util.module_from_spec(规格)
    规格.loader.exec_module(模块)
    return 模块


def 加载检查函数(只用我的=False):
    """返回 (参考模块, 我的模块)。导入出错直接抛出，交给调用方报告。"""
    sys.modules.setdefault("qc_tools", sys.modules[__name__])
    if str(本目录) not in sys.path:
        sys.path.insert(0, str(本目录))
    参考 = None if 只用我的 else _加载模块(本目录 / "参考检查.py", "参考检查")
    我的 = _加载模块(本目录 / "我的检查.py", "我的检查")
    return 参考, 我的


def 找函数(名字, 参考, 我的):
    if 空(名字):
        return None, "规则没写「检查」函数名"
    名字 = str(名字).strip()
    if 我的 is not None and callable(getattr(我的, 名字, None)):
        return getattr(我的, 名字), "我的"
    if 参考 is not None and callable(getattr(参考, 名字, None)):
        return getattr(参考, 名字), "参考"
    return None, "没有检查函数 " + 名字


# ============================================================
# 运行
# ============================================================

def _自然排序键(文字):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", str(文字))]


def _相对(路径):
    try:
        return os.path.relpath(str(路径)).replace("\\", "/")
    except ValueError:
        return str(路径).replace("\\", "/")


def 运行(规则库路径, 数据目录, 规则选择="all", 声明路径=None, 只用我的=False):
    """跑检查，返回 (结果 dict, 是否有函数出错)。"""
    规则库 = 读规则库(规则库路径)
    规则们 = 规则库["规则"]
    if 规则选择 and str(规则选择).strip().lower() != "all":
        要的 = [x.strip() for x in str(规则选择).split(",") if x.strip()]
        已有 = {r["id"] for r in 规则们}
        没有 = [x for x in 要的 if x not in 已有]
        if 没有:
            raise 数据错误("规则库里没有这些规则：" + "、".join(没有))
        规则们 = [r for r in 规则们 if r["id"] in 要的]
    参考, 我的 = 加载检查函数(只用我的)
    数据 = 成果数据(数据目录, 声明路径)

    问题们, 未检查, 来源, 出错 = [], [], {}, False
    for 规则 in 规则们:
        函数, 出处 = 找函数(规则.get("检查"), 参考, 我的)
        if 函数 is None:
            未检查.append({"规则": 规则["id"], "原因": 出处})
            来源[规则["id"]] = "缺"
            continue
        来源[规则["id"]] = 出处
        try:
            结果 = list(函数(数据, 规则) or [])
        except 不适用 as e:
            未检查.append({"规则": 规则["id"], "原因": "不适用：" + str(e)})
            continue
        except 参数缺失 as e:
            未检查.append({"规则": 规则["id"], "原因": str(e)})
            出错 = True
            continue
        except Exception as e:
            未检查.append({"规则": 规则["id"], "原因": "检查函数出错：" + type(e).__name__ + ": " + str(e)})
            print("—— " + 规则["id"] + " 的检查函数出错 ——", file=sys.stderr)
            traceback.print_exc()
            出错 = True
            continue
        for 条 in 结果:
            if not isinstance(条, dict) or "对象" not in 条 or 条.get("严重度") not in 严重度顺序:
                未检查.append({"规则": 规则["id"], "原因": "检查函数返回的不是 问题()/无法检查() 生成的结果：" + repr(条)[:120]})
                出错 = True
                break
            条 = dict(条)
            条["规则"] = 规则["id"]
            问题们.append(条)

    for 条文 in 规则库.get("不适用") or []:
        if isinstance(条文, dict):
            未检查.append({"条文": 条文.get("条文"), "原因": "不适用：" + str(条文.get("为什么不查") or "")})

    顺序 = {r["id"]: i for i, r in enumerate(规则库["规则"])}
    去重, 见过 = [], set()
    for 条 in 问题们:
        键 = (条["规则"], 条["对象"], 条["严重度"], 条["说明"])
        if 键 not in 见过:
            见过.add(键)
            去重.append(条)
    去重.sort(key=lambda 条: (顺序.get(条["规则"], 999), 严重度顺序.index(条["严重度"]),
                             _自然排序键(条["对象"]), 条["说明"]))
    带编号 = []
    for i, 条 in enumerate(去重, 1):
        带编号.append(dict([("编号", "F%03d" % i)] + list(条.items())))

    自由文本 = [{"对象": 地块对象(p), "字段": "备注", "文本": str(p.get("备注")).strip()}
              for p in 数据.地块 if not 空(p.get("备注"))]
    统计 = {k: sum(1 for 条 in 带编号 if 条["严重度"] == k) for k in 严重度顺序}
    结果 = {
        "运行信息": {
            "工具": "qc_tools.py",
            "框架版本": 框架版本,
            "规则库": _相对(规则库路径),
            "规则库版本": 规则库.get("版本"),
            "审定人": 规则库.get("审定人"),
            "数据目录": _相对(数据目录),
            "单元名称": 数据.成果信息.get("单元名称"),
            "运行时间": datetime.datetime.now().isoformat(timespec="seconds"),
            "检查规则": [r["id"] for r in 规则们],
            "函数来源": 来源,
            "说明书数字": _相对(数据.声明路径) if 数据.声明路径 else None,
            "只用我的": bool(只用我的),
        },
        "统计": 统计,
        "findings": 带编号,
        "未检查": 未检查,
        "自由文本": 自由文本,
    }
    return 结果, 出错


def _打印摘要(结果, 输出路径):
    统计 = 结果["统计"]
    print("质检完成：" + " · ".join(k + " " + str(统计[k]) for k in 严重度顺序) + " → " + _相对(输出路径))
    for 条 in 结果["findings"]:
        print("  " + 条["编号"] + " " + 条["规则"] + " " + 条["对象"] + " " + 条["严重度"] + " —— " + 条["说明"])
    规则级 = [x for x in 结果["未检查"] if "规则" in x]
    if 规则级:
        print("未检查的规则：")
        for x in 规则级:
            print("  " + x["规则"] + "：" + x["原因"])
    条文级 = [x for x in 结果["未检查"] if "条文" in x]
    if 条文级:
        print("规则库写明不查的条文：" + str(len(条文级)) + " 条（见 findings.json 的「未检查」）")


def main(argv=None):
    ap = argparse.ArgumentParser(description="控规成果质检工具（框架）。说明见文件开头。")
    ap.add_argument("--data", help="成果目录，例如 data/qc")
    ap.add_argument("--out", help="findings.json 的路径")
    ap.add_argument("--rules", default="all", help="规则，逗号分隔；默认 all")
    ap.add_argument("--rulebook", default=str(本目录 / "规则库.yaml"), help="规则库路径")
    ap.add_argument("--claims", default=None, help="claims.json 路径（Q21 用）")
    ap.add_argument("--只用我的", dest="只用我的", action="store_true", help="只加载 我的检查.py")
    ap.add_argument("--list", action="store_true", help="列出每条规则由哪个函数实现")
    args = ap.parse_args(argv)

    try:
        if args.list:
            规则库 = 读规则库(args.rulebook)
            参考, 我的 = 加载检查函数(args.只用我的)
            for 规则 in 规则库["规则"]:
                函数, 出处 = 找函数(规则.get("检查"), 参考, 我的)
                print(规则["id"] + "  " + str(规则.get("名称", "")) + "  " + str(规则.get("检查")) + "  ← " + 出处)
            return 0
        if not args.data or not args.out:
            ap.error("要给 --data 和 --out（或者用 --list）")
        输出 = Path(args.out)
        声明 = Path(args.claims) if args.claims else 输出.parent / "claims.json"
        结果, 出错 = 运行(args.rulebook, args.data, args.rules, 声明, args.只用我的)
    except 数据错误 as e:
        print("出错：" + str(e), file=sys.stderr)
        return 2
    except SyntaxError as e:
        print("检查函数文件有语法错误：" + str(e), file=sys.stderr)
        return 2
    except Exception as e:
        print("出错：" + type(e).__name__ + ": " + str(e), file=sys.stderr)
        traceback.print_exc()
        return 2

    输出.parent.mkdir(parents=True, exist_ok=True)
    with open(输出, "w", encoding="utf-8") as f:
        json.dump(结果, f, ensure_ascii=False, indent=1)
        f.write("\n")
    try:
        _打印摘要(结果, 输出)
    except BrokenPipeError:   # 输出被 head 之类截断了：结果文件已经写好，不算错
        try:
            sys.stdout = open(os.devnull, "w")
        except Exception:
            pass
    return 3 if 出错 else 0


if __name__ == "__main__":
    sys.exit(main())
