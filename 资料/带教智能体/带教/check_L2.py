#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L2 写工具 · 验收
  1. 学员规则的「检查」函数都写在 qc_agent/我的检查.py 里，规则都有「参数」
  2. 小样本：违规例报出、合规例不报、缺值例报「无法检查」
  3. 改阈值测试：把规则库「参数」里的数值放大 / 缩小、代码表清空，结果必须跟着变（阈值没写死在代码里）
合并参考规则以后（progress.py merge）再跑，会用小样本核对规则库里的全部规则。
"""
import sys

sys.dont_write_bytecode = True

import ast
import atexit
import copy
import shutil
import tempfile
from pathlib import Path

import common as c

yaml = c.需要yaml()
v = c.验收("L2")
进度 = v.前置()
规则库文件 = c.作品目录 / "规则库.yaml"
我的文件 = c.作品目录 / "我的检查.py"
for 文件 in (c.作品目录 / "qc_tools.py", 规则库文件, 我的文件):
    if not 文件.is_file():
        v.坏("没有 " + c.相对(文件))
if v.失败项:
    v.结束()

try:
    规则库 = c.读yaml(规则库文件)
    规则们 = {str(r["id"]): r for r in 规则库["规则"]}
except Exception as e:
    v.坏("规则库读不了：" + str(e).splitlines()[0])
    v.结束()
try:
    我的函数 = {n.name for n in ast.parse(c.读文本(我的文件)).body if isinstance(n, ast.FunctionDef)}
except SyntaxError as e:
    v.坏("我的检查.py 有语法错误：第 " + str(e.lineno) + " 行 " + str(e.msg))
    v.结束()

已合并 = (c.作品目录 / "参考检查.py").is_file()
用了存档点 = bool(进度["关卡"]["L2"].get("存档点"))
我的规则 = [x for x in (进度.get("记录", {}).get("我的规则") or []) if x in 规则们]
if not 我的规则:
    我的规则 = list(规则们)

# ---- 1. 函数和参数 ----
for 编号 in 我的规则:
    r = 规则们[编号]
    名 = str(r.get("检查") or "")
    if 名 in 我的函数:
        v.好(编号 + " 的检查函数 " + 名 + " 在 我的检查.py 里")
    elif 用了存档点 and 已合并:
        v.说(编号 + " 用的是存档点里的参考函数（" + 名 + "）")
    else:
        v.坏(编号 + " 的检查函数 " + 名 + " 不在 qc_agent/我的检查.py 里（函数名要和规则库「检查」字段一致）")
    if not isinstance(r.get("参数"), dict) or not r.get("参数"):
        v.坏(编号 + " 没有「参数」：阈值、代码表要写进规则库的「参数」，函数里用 取参数(rule, \"键\") 读")
if v.失败项:
    v.结束()

# ---- 2. 小样本 ----
样本目录 = c.带教目录 / "小样本"
要核对 = list(规则们) if 已合并 else 我的规则
只用我的 = not 已合并
基线 = {}
临时根 = Path(tempfile.mkdtemp(prefix="qc_L2_"))
atexit.register(shutil.rmtree, str(临时根), True)


def 跑(规则, 数据集, 序号, 规则库路径=None, 标签="基线"):
    目录 = c.落盘(数据集, 临时根 / (规则 + "_" + str(序号) + "_" + 标签))
    声明 = 目录 / "claims.json" if "claims.json" in 数据集["文件"] else None
    return c.运行qc(目录, 目录 / "out" / "findings.json", 规则, 规则库=规则库路径 or 规则库文件,
                   声明=声明, 只用我的=只用我的)


for 编号 in 要核对:
    样本文件 = 样本目录 / (编号 + ".json")
    if not 样本文件.is_file():
        v.说(编号 + " 没有小样本，跳过")
        continue
    样本 = c.读json(样本文件)
    没对上 = []
    for i, 数据集 in enumerate(样本["数据集"]):
        码, 文字, 结果 = 跑(编号, 数据集, i)
        if 结果 is None or 码 not in (0,):
            尾巴 = [行 for 行 in 文字.strip().splitlines() if 行.strip()][-3:]
            没对上.append("「" + 数据集["名称"] + "」qc_tools.py 出错（退出码 " + str(码) + "）：" + " / ".join(尾巴))
            continue
        问题们 = c.对照期望(结果["findings"], 编号, 数据集["期望"])
        没对上 += ["「" + 数据集["名称"] + "」" + x for x in 问题们]
        基线[(编号, i)] = c.实际结果(结果["findings"], 编号)
    if 没对上:
        for x in 没对上[:6]:
            v.坏(编号 + " 小样本" + x)
    else:
        v.好(编号 + " 小样本 " + str(len(样本["数据集"])) + " 份全部对上")


# ---- 3. 改阈值测试（只测学员自己写的函数）----
def 扰动(值, 方式):
    if isinstance(值, bool):
        return 值
    if isinstance(值, (int, float)):
        return 值 * 10 if 方式 == "放大" else (值 / 10 if 方式 == "缩小" else 值)
    if isinstance(值, list):
        if 方式 == "清空" and all(isinstance(x, str) for x in 值):
            return []
        return [扰动(x, 方式) for x in 值]
    if isinstance(值, dict):
        return {k: 扰动(x, 方式) for k, x in 值.items()}
    return 值


def 有数值(值):
    if isinstance(值, bool):
        return False
    if isinstance(值, (int, float)):
        return True
    if isinstance(值, dict):
        return any(有数值(x) for x in 值.values())
    if isinstance(值, list):
        return any(有数值(x) for x in 值)
    return False


def 有代码表(值):
    if isinstance(值, list):
        return (bool(值) and all(isinstance(x, str) for x in 值)) or any(有代码表(x) for x in 值)
    if isinstance(值, dict):
        return any(有代码表(x) for x in 值.values())
    return False


for 编号 in 我的规则:
    if str(规则们[编号].get("检查")) not in 我的函数:
        continue
    样本文件 = 样本目录 / (编号 + ".json")
    if not 样本文件.is_file():
        continue
    样本 = c.读json(样本文件)
    候选 = [i for i, d in enumerate(样本["数据集"]) if d.get("改阈值") and (编号, i) in 基线]
    if not 候选:
        continue
    i = 候选[0]
    参数 = 规则们[编号].get("参数")
    要求 = []
    if 有数值(参数):
        要求.append(("数值阈值", ("放大", "缩小"), "把「参数」里的数值放大 10 倍、缩小 10 倍，结果都没变——数值阈值是不是写死在代码里了？"))
    if 有代码表(参数):
        要求.append(("代码表", ("清空",), "把「参数」里的代码表清空，结果没变——代码表是不是写死在代码里了？"))
    if not 要求:
        v.说(编号 + " 的「参数」里没有数值和代码表，跳过改阈值测试")
        continue
    变了 = []
    for 方式 in sorted({m for _, 方式们, _ in 要求 for m in 方式们}, key=["放大", "缩小", "清空"].index):
        改后 = copy.deepcopy(规则库)
        for r in 改后["规则"]:
            if str(r.get("id")) == 编号:
                r["参数"] = 扰动(r.get("参数"), 方式)
        路径 = 临时根 / (编号 + "_" + 方式 + "_规则库.yaml")
        with open(路径, "w", encoding="utf-8") as f:
            yaml.safe_dump(改后, f, allow_unicode=True, sort_keys=False)
        码, 文字, 结果 = 跑(编号, 样本["数据集"][i], i, 路径, 方式)
        if 结果 is not None and c.实际结果(结果["findings"], 编号) != 基线[(编号, i)]:
            变了.append(方式)
        elif 结果 is None and 码 != 0:
            变了.append(方式)   # 改了参数函数就报错，说明它确实在读参数
    没反应 = [说法 for 名, 方式们, 说法 in 要求 if not set(方式们) & set(变了)]
    if 没反应:
        for 说法 in 没反应:
            v.坏(编号 + " 改阈值测试：" + 说法)
    else:
        v.好(编号 + " 改阈值测试：" + "、".join(名 for 名, _, _ in 要求) + "改了，结果都跟着变")

if not v.失败项:
    v.记录("规则库哈希_L2", c.文件哈希(规则库文件))
    if not 已合并:
        v.说("通过以后运行 python3 带教/progress.py merge，并入其余规则，再跑一次本验收")
v.结束()
