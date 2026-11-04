#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L4 评测 · 验收
  合格线（progress.py redline）要早于这三次评测：
    qc_agent/评测/运行1/  /qc data/qc qc_agent/评测/运行1
    qc_agent/评测/运行2/  /qc data/qc qc_agent/评测/运行2
    qc_agent/评测/变体/   /qc 带教/变体单元 qc_agent/评测/变体
  运行1 与 运行2 结果一致；教学单元、变体单元的检出率和误报都达到合格线；评测记录.md 四节齐全。
只算「错误」「待确认」；答案键只存哈希，反馈只说到规则这一级。
"""
import sys

sys.dont_write_bytecode = True

import datetime
import hashlib

import common as c

v = c.验收("L4")
进度 = v.前置()
线 = 进度.get("合格线")
if not 线:
    v.坏("还没定合格线：先让学员定，再运行 python3 带教/progress.py redline --recall <检出率> --fp <误报上限>")
    v.结束()
v.好("合格线：检出率 ≥ " + format(线["检出率"], ".0%") + "，误报 ≤ " + str(线["误报上限"]) + " 条（" + 线["时间"] + "）")

评测目录 = c.作品目录 / "评测"
运行们 = {"运行1": "data/qc", "运行2": "data/qc", "变体": "带教/变体单元"}
结果们 = {}
for 名, 数据 in 运行们.items():
    文件 = 评测目录 / 名 / "findings.json"
    if not 文件.is_file():
        v.坏("没有 " + c.相对(文件) + "：开新会话运行 /qc " + 数据 + " qc_agent/评测/" + 名)
        continue
    结果 = c.读json(文件)
    信息 = 结果.get("运行信息") or {}
    if str(信息.get("数据目录", "")).rstrip("/") != 数据:
        v.坏(名 + " 的数据目录是「" + str(信息.get("数据目录")) + "」，应该是 " + 数据)
        continue
    结果们[名] = 结果
if v.失败项:
    v.结束()

定线 = datetime.datetime.fromisoformat(线["时间"])
早 = [名 for 名, r in 结果们.items() if datetime.datetime.fromisoformat(r["运行信息"]["运行时间"]) < 定线]
if 早:
    v.坏("这些评测比合格线跑得早：" + "、".join(早) + "——先定合格线，再看结果。删掉它们，在新会话里重跑")
else:
    v.好("三次评测都在定合格线之后")


def 集合(结果, 只要关键=True):
    return {(f["规则"], f["对象"], f["严重度"]) for f in 结果["findings"]
            if not 只要关键 or f["严重度"] in ("错误", "待确认")}


甲, 乙 = 集合(结果们["运行1"], False), 集合(结果们["运行2"], False)
if 甲 != 乙:
    差 = sorted(甲 ^ 乙)
    v.坏("运行1 和 运行2 结果不一样（" + str(len(差)) + " 处），例如：" + "；".join(" ".join(x) for x in 差[:4])
         + "——找出哪一步是模型做的，那一步就是不稳定的来源")
else:
    v.好("运行1 和 运行2 结果完全一致（" + str(len(甲)) + " 条）")

键 = c.读json(c.带教目录 / "答案键.json")
盐 = 键["盐"]


def 哈希(规则, 对象):
    return hashlib.sha256((盐 + "|" + 规则 + "|" + 对象).encode("utf-8")).hexdigest()


汇总 = {}
for 单元, 名 in (("教学单元", "运行1"), ("变体单元", "变体")):
    答案 = 键[单元]
    全部哈希 = {h for hs in 答案.values() for h in hs}
    我的 = {(规则, 对象) for 规则, 对象, _ in 集合(结果们[名])}
    我的哈希 = {哈希(规则, 对象): (规则, 对象) for 规则, 对象 in 我的}
    检出 = len(全部哈希 & set(我的哈希))
    检出率 = 检出 / len(全部哈希)
    漏 = {规则: sum(1 for h in hs if h not in 我的哈希) for 规则, hs in 答案.items()}
    漏 = {k: n for k, n in 漏.items() if n}
    误报 = sorted(我的哈希[h] for h in 我的哈希 if h not in 全部哈希)
    汇总[单元] = {"检出": 检出, "应检出": len(全部哈希), "检出率": round(检出率, 4), "误报": len(误报)}
    行 = 单元 + "：检出 " + str(检出) + "/" + str(len(全部哈希)) + "（" + format(检出率, ".0%") + "），误报 " + str(len(误报)) + " 条"
    if 漏:
        行 += "；漏报：" + "、".join(k + " " + str(n) + " 处" for k, n in sorted(漏.items()))
    if 误报:
        行 += "；误报：" + "、".join(规则 + " " + 对象 for 规则, 对象 in 误报[:6])
    if 检出率 + 1e-9 >= 线["检出率"] and len(误报) <= 线["误报上限"]:
        v.好(行)
    else:
        v.坏(行 + "——没达到合格线")

记录文件 = 评测目录 / "评测记录.md"
if not 记录文件.is_file():
    v.坏("没有 qc_agent/评测/评测记录.md")
else:
    文字 = c.读文本(记录文件)
    for 节, 关键词 in (("合格线", ("合格线",)), ("稳定性", ("稳定", "两次")), ("变体单元", ("变体",)), ("口径差异", ("口径",))):
        if c.节文字(文字, *关键词) is None:
            v.坏("评测记录.md 缺「" + 节 + "」一节")
    if not any(x.startswith("评测记录") for x in v.失败项):
        v.好("评测记录.md 四节齐全")

v.记录("评测结果", 汇总)
v.记录("规则库哈希_L4", c.文件哈希(c.作品目录 / "规则库.yaml"))
v.结束()
