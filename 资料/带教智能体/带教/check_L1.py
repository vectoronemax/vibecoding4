#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L1 从条文抽规则 · 验收：qc_agent/规则库.yaml 里必做规则齐全、字段不空、原文逐字可查、用词与严重度对得上、已签字。"""
import sys

sys.dont_write_bytecode = True

import re
import unicodedata

import common as c

强 = ["必须", "严禁", "不应", "不得", "应"]    # → 错误
弱 = ["不宜", "宜"]                           # → 提示


def 规范(文字):
    文字 = unicodedata.normalize("NFKC", str(文字))
    文字 = 文字.replace("*", "")
    文字 = re.sub(r"[–—―−~～-]+", "-", 文字)
    return re.sub(r"\s+", "", 文字)


v = c.验收("L1")
进度 = v.前置()
定义 = c.关卡定义("L1")
规则定义 = 定义.get("规则") or {}
if c.课时版本() == "压缩":
    必做 = list(规则定义.get("压缩版只做") or [])
else:
    必做 = [r["id"] for r in 规则定义.get("必做") or []]
挑战 = [r["id"] for r in 规则定义.get("挑战（技术路线）") or []]
字段 = list(定义.get("字段") or ["id", "名称", "类别", "依据", "原文", "用词", "严重度", "适用", "口径", "检查"])

文件 = c.作品目录 / "规则库.yaml"
if not 文件.is_file():
    v.坏("没有 qc_agent/规则库.yaml")
    v.结束()
try:
    规则库 = c.读yaml(文件)
except Exception as e:
    v.坏("规则库读不了（YAML 格式有错）：" + str(e).splitlines()[0])
    v.结束()
if not isinstance(规则库, dict) or not isinstance(规则库.get("规则"), list):
    v.坏("规则库里要有「规则:」列表（参照 规则库 的格式：规则: 下面一条一个 - id: ...）")
    v.结束()
v.好("规则库能解析")

规则们 = {str(r.get("id")).strip(): r for r in 规则库["规则"] if isinstance(r, dict) and r.get("id")}
缺 = [x for x in 必做 if x not in 规则们]
if 缺:
    v.坏("必做规则还缺：" + " ".join(缺))
else:
    v.好("必做规则齐全：" + " ".join(必做))

摘录 = 规范(c.读文本(c.根目录 / "资料" / "质检智能体" / "上海控规质检_条文摘录.md"))
要查 = [x for x in 必做 + 挑战 if x in 规则们]
for 编号 in 要查:
    r = 规则们[编号]
    空字段 = [k for k in 字段 if k not in r or r[k] is None or str(r[k]).strip() == ""]
    if 空字段:
        v.坏(编号 + " 这些字段是空的：" + "、".join(空字段))
        continue
    片段 = [s for s in re.split(r"……|\.\.\.", str(r["原文"])) if 规范(s)]
    找不到 = [s.strip() for s in 片段 if 规范(s) not in 摘录]
    if 找不到:
        v.坏(编号 + "「原文」在条文摘录里找不到（逐字比对，省略的地方用 …… 断开）：「" + 找不到[0][:30] + "……」")
    用词, 严重度 = str(r["用词"]), str(r["严重度"])
    有强 = [w for w in 强 if w in 用词]
    有弱 = [w for w in 弱 if w in 用词]
    if 有强 and "错误" not in 严重度:
        v.坏(编号 + " 用词是「" + 有强[0] + "」，按准则附录五应该判「错误」，严重度里没有")
    elif 有弱 and not 有强 and "错误" in 严重度:
        v.坏(编号 + " 用词是「" + 有弱[0] + "」，按附录五只能给「提示」，不能判「错误」")
    elif 有弱 and "提示" not in 严重度:
        v.坏(编号 + " 用词是「" + 有弱[0] + "」，严重度里应该有「提示」")
    if not str(r["检查"]).strip().isidentifier():
        v.坏(编号 + "「检查」要写成一个函数名（字母、数字、下划线，例如 check_plaza_size），现在是「" + str(r["检查"]) + "」")
    if not any(问题.startswith(编号) for 问题 in v.失败项):
        v.好(编号 + " 字段齐全，原文逐字可查，用词与严重度对得上")

审定人 = str(规则库.get("审定人") or "").strip()
if not 审定人 or "签字" in 审定人 or 审定人.startswith("（"):
    v.坏("规则库的「审定人」还没签：写上学员自己的名字（谁签字谁负责口径）")
else:
    v.好("审定人：" + 审定人)

v.记录("我的规则", [x for x in 必做 + 挑战 if x in 规则们])
v.记录("规则库哈希_L1", c.文件哈希(文件))
v.结束()
