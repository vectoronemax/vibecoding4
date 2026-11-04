#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
L3 编排成智能体 · 验收（看的是 /qc 在 data/qc 上跑出来的东西）
  .claude/skills/qc/SKILL.md 存在；qc_agent/报告/ 下有 findings.json、claims.json、质检报告.md
  报告里每个 F 编号都能在 findings.json 里找到；findings.json 的每条「错误」「待确认」都写进了报告
  claims.json 的数字带「原文」，原文能在说明书里找到；报告头写了规则库版本和审定人；有「未检查」一节
"""
import sys

sys.dont_write_bytecode = True

import re

import common as c

v = c.验收("L3")
进度 = v.前置()
技能 = c.根目录 / ".claude" / "skills" / "qc" / "SKILL.md"
报告目录 = c.作品目录 / "报告"
findings文件, 声明文件, 报告文件 = 报告目录 / "findings.json", 报告目录 / "claims.json", 报告目录 / "质检报告.md"

if not 技能.is_file() or len(c.读文本(技能).strip()) < 200:
    v.坏("没有 .claude/skills/qc/SKILL.md（或者内容太少）")
for 文件 in (findings文件, 声明文件, 报告文件):
    if not 文件.is_file():
        v.坏("没有 " + c.相对(文件) + "：开一个新会话，运行 /qc data/qc qc_agent/报告")
if v.失败项:
    v.结束()
v.好("SKILL.md、findings.json、claims.json、质检报告.md 都在")

结果 = c.读json(findings文件)
信息 = 结果.get("运行信息") or {}
if str(信息.get("数据目录", "")).rstrip("/") != "data/qc":
    v.坏("findings.json 的数据目录是「" + str(信息.get("数据目录")) + "」，要在 data/qc 上跑")
if str(信息.get("规则库", "")) != "qc_agent/规则库.yaml":
    v.坏("findings.json 用的规则库是「" + str(信息.get("规则库")) + "」，应该是 qc_agent/规则库.yaml")
if 信息.get("只用我的"):
    v.坏("这份 findings.json 是用 --只用我的 跑的：/qc 要用完整的工具（我的 + 参考）")
if 技能.stat().st_mtime > findings文件.stat().st_mtime + 1:
    v.坏("SKILL.md 比 findings.json 新：改完 SKILL.md 要在新会话里重新跑一次 /qc")
if findings文件.stat().st_mtime > 报告文件.stat().st_mtime + 1:
    v.坏("质检报告.md 比 findings.json 旧：报告要根据最新的 findings.json 写")

规则库 = c.读yaml(c.作品目录 / "规则库.yaml")
全部规则 = [str(r["id"]) for r in 规则库.get("规则") or []]
跑了 = set(信息.get("检查规则") or [])
报告 = c.读文本(报告文件)
未检查节 = c.节文字(报告, "未检查")
没跑 = [x for x in 全部规则 if x not in 跑了]
if 没跑:
    没解释 = [x for x in 没跑 if not 未检查节 or x not in 未检查节]
    if 没解释:
        v.坏("这些规则没跑，报告「未检查」里也没写原因：" + " ".join(没解释))
    else:
        v.好("没跑的规则在「未检查」里写了原因：" + " ".join(没跑))
else:
    v.好("规则库里 " + str(len(全部规则)) + " 条规则都跑了")

# claims.json：数字是模型从说明书读的，要带原文
声明 = c.读json(声明文件)
数字 = 声明.get("数字") if isinstance(声明, dict) else None
说明书路径 = next((c.根目录 / "data" / "qc").glob("*_说明书.md"))
说明书 = re.sub(r"\s+", "", c.读文本(说明书路径))
if not isinstance(数字, list) or len(数字) < 5:
    v.坏("claims.json 的「数字」少于 5 项：规划人口、总用地、总建筑面积、各类学校、公共绿地都要读出来")
else:
    没原文 = [str(x.get("项目")) for x in 数字 if not str(x.get("原文") or "").strip()]
    查得到 = [x for x in 数字 if str(x.get("原文") or "").strip() and re.sub(r"\s+", "", str(x["原文"])) in 说明书]
    if 没原文:
        v.坏("claims.json 这些项没写「原文」：" + "、".join(没原文))
    elif len(查得到) < 0.6 * len(数字):
        v.坏("claims.json 的「原文」大多在说明书里找不到（" + str(len(查得到)) + "/" + str(len(数字)) + "）：要逐字摘，不要改写")
    else:
        v.好("claims.json 读出 " + str(len(数字)) + " 项数字，原文能在说明书里找到 " + str(len(查得到)) + " 项")
    if not any(f.get("规则") == "Q21" for f in 结果.get("findings", [])) and "Q21" in 跑了:
        v.说("（Q21 这次一条问题都没报——确认一下说明书数字读对了）")

# 报告和 findings.json 对得上
编号们 = {f["编号"]: f for f in 结果.get("findings", [])}
报告里 = set(re.findall(r"F\d{3,}", 报告))
多出来 = sorted(x for x in 报告里 if x not in 编号们)
if 多出来:
    v.坏("报告里这些编号在 findings.json 里找不到（结论必须来自工具）：" + " ".join(多出来[:10]))
漏掉 = [f["编号"] + " " + f["规则"] + " " + f["对象"] for f in 编号们.values()
      if f["严重度"] in ("错误", "待确认") and f["编号"] not in 报告里]
if 漏掉:
    v.坏("findings.json 里这些「错误/待确认」没写进报告（不许静默漏掉）：" + "；".join(漏掉[:8]))
if not 多出来 and not 漏掉:
    v.好("报告里 " + str(len(报告里)) + " 个编号都能追溯到 findings.json，错误和待确认一条不漏")
if any(f["严重度"] == "待确认" for f in 编号们.values()) and c.节文字(报告, "待确认") is None:
    v.坏("有「待确认」的问题，报告里要单独一节「待确认」交给人判断")

开头 = "\n".join(报告.splitlines()[:20])
for 键 in ("规则库版本", "审定人"):
    值 = str(信息.get(键) or "")
    if 值 and 值 not in 开头:
        v.坏("报告开头（前 20 行）要写" + 键 + "：「" + 值 + "」")
if 未检查节 is None:
    v.坏("报告要有「未检查」一节：不适用的条文、无法检查的地块")
elif not v.失败项:
    v.好("报告开头写了规则库版本和审定人，有「未检查」一节")
v.结束()
