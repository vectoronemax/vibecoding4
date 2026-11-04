#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
班级进度汇总（讲师用，不进学员包）

  python3 资料/带教智能体/汇总进度.py <文件夹> [--out 班级进度.md]

<文件夹> 里放学员交上来的 学习进度.json（文件名随意，比如群里下载下来的 学习进度(3).json）。
输出一份 Markdown：
  一、总览          每人在哪一关、验收几次、用了几次提示和存档点
  二、卡在哪        每关人数；正卡着的人最近没过的是什么
  三、口径分歧      每道决策题，全班各自怎么定的（中场讨论用）
  四、合格线与评测  谁定了多高的线、教学单元和变体单元各检出多少（收尾用）
"""
import argparse
import difflib
import json
import re
import sys
from pathlib import Path

sys.dont_write_bytecode = True
for _流 in (sys.stdout, sys.stderr):
    try:
        _流.reconfigure(encoding="utf-8")
    except Exception:
        pass

源 = Path(__file__).resolve().parent
关卡顺序 = ["L0", "L1", "L2", "L3", "L4", "L5", "L6"]


def 读教案():
    try:
        import yaml
    except ImportError:
        return {}
    数据 = yaml.safe_load((源 / "关卡.yaml").read_text(encoding="utf-8"))
    return {段["id"]: 段 for 段 in 数据.get("关卡") or []}


def 读学员(文件夹):
    学员们, 跳过 = [], []
    for 路径 in sorted(Path(文件夹).glob("*.json")):
        try:
            数据 = json.loads(路径.read_text(encoding="utf-8-sig"))
        except Exception as e:
            跳过.append(路径.name + "（读不了：" + str(e)[:40] + "）")
            continue
        if not isinstance(数据, dict) or "学员" not in 数据 or "关卡" not in 数据:
            跳过.append(路径.name + "（不是 学习进度.json）")
            continue
        数据["_文件"] = 路径.name
        学员们.append(数据)
    return 学员们, 跳过


def 单元格(文字):
    return str(文字).replace("|", "／").replace("\n", " ")


def 归类(问题, 题目们):
    """把学员记录里的问题对到教案的第几道决策题；对不上返回 None。"""
    规则号 = set(re.findall(r"Q\d{2}", 问题))
    最好, 分 = None, 0.0
    for i, 题 in enumerate(题目们):
        r = difflib.SequenceMatcher(None, 问题, 题).ratio()
        if 规则号 and 规则号 & set(re.findall(r"Q\d{2}", 题)):
            r += 0.5
        if r > 分:
            最好, 分 = i, r
    return 最好 if 分 >= 0.45 else None


def 没过项摘要(文字):
    文字 = re.sub(r"[「（(].*$", "", str(文字)).strip()
    return 文字[:24]


def main():
    ap = argparse.ArgumentParser(description="班级进度汇总（说明见文件开头）")
    ap.add_argument("文件夹")
    ap.add_argument("--out", default="班级进度.md")
    args = ap.parse_args()
    教案 = 读教案()
    学员们, 跳过 = 读学员(args.文件夹)
    if not 学员们:
        print("文件夹里没有能读的 学习进度.json：" + args.文件夹)
        return 1
    学员们.sort(key=lambda p: (关卡顺序.index(p["当前关"]) if p.get("当前关") in 关卡顺序 else 99, p["学员"]))

    行 = ["# 班级进度（" + str(len(学员们)) + " 人）", ""]
    if 跳过:
        行 += ["> 没读进来的文件：" + "；".join(跳过), ""]

    # ---- 一、总览 ----
    行 += ["## 一、总览", "", "| 学员 | 路线 | 当前 | 已过 | 验收次数 | 提示 | 存档点 | 最近一次没过的 |", "|---|---|---|---|---|---|---|---|"]
    for p in 学员们:
        关卡 = p["关卡"]
        已过 = [k for k in 关卡顺序 if 关卡.get(k, {}).get("状态") == "已通过"]
        当前 = p.get("当前关", "?")
        当前 = "全部通过" if 当前 == "完成" else 当前
        次数 = sum(int(关卡.get(k, {}).get("验收次数") or 0) for k in 关卡顺序)
        提示 = sum(len([x for x in 关卡.get(k, {}).get("提示") or [] if x != 4]) for k in 关卡顺序)
        存档 = " ".join(k for k in 关卡顺序 if 关卡.get(k, {}).get("存档点")) or "—"
        最近 = (关卡.get(p.get("当前关"), {}) or {}).get("最近验收") or {}
        没过 = (最近.get("没过") or [""])[0] if 最近.get("结果") == "未通过" else ""
        行.append("| " + " | ".join(单元格(x) for x in (p["学员"], p.get("路线", ""), 当前, " ".join(已过) or "—",
                                                    次数, 提示, 存档, 没过 or "—")) + " |")
    行.append("")

    # ---- 二、卡在哪 ----
    行 += ["## 二、卡在哪", ""]
    人数 = {k: sum(1 for p in 学员们 if p.get("当前关") == k) for k in 关卡顺序}
    完成 = sum(1 for p in 学员们 if p.get("当前关") == "完成")
    行.append("每关人数：" + " · ".join(k + " " + str(人数[k]) + " 人" for k in 关卡顺序 if 人数[k])
             + ("" if not 完成 else " · 全部通过 " + str(完成) + " 人"))
    行.append("")
    行 += ["| 关 | 已通过的人平均验收次数 | 用过存档点 | 正卡着的人最常见的没过项 |", "|---|---|---|---|"]
    for k in 关卡顺序:
        通过的 = [int(p["关卡"][k].get("验收次数") or 0) for p in 学员们 if p["关卡"].get(k, {}).get("状态") == "已通过"]
        平均 = format(sum(通过的) / len(通过的), ".1f") if 通过的 else "—"
        存档 = sum(1 for p in 学员们 if p["关卡"].get(k, {}).get("存档点"))
        计数 = {}
        for p in 学员们:
            最近 = p["关卡"].get(k, {}).get("最近验收") or {}
            if p.get("当前关") == k and 最近.get("结果") == "未通过":
                for x in 最近.get("没过") or []:
                    计数[没过项摘要(x)] = 计数.get(没过项摘要(x), 0) + 1
        常见 = "；".join(t + "（" + str(n) + " 人）" for t, n in sorted(计数.items(), key=lambda kv: -kv[1])[:3]) or "—"
        行.append("| " + " | ".join(单元格(x) for x in (k, 平均, 存档 or "—", 常见)) + " |")
    行.append("")

    # ---- 三、口径分歧 ----
    行 += ["## 三、口径分歧（每道决策题，全班怎么定的）", ""]
    for k in 关卡顺序:
        题目们 = list((教案.get(k) or {}).get("决策题") or [])
        分组 = {}
        for p in 学员们:
            for d in p.get("决策") or []:
                if d.get("关") != k:
                    continue
                i = 归类(str(d.get("问题", "")), 题目们)
                分组.setdefault(i, []).append((p["学员"], str(d.get("回答", "")), str(d.get("问题", ""))))
        if not 分组:
            continue
        行 += ["### " + k + " " + str((教案.get(k) or {}).get("名称", "")), ""]
        for i in sorted(分组, key=lambda x: (x is None, x if x is not None else 0)):
            标题 = 题目们[i] if i is not None else "其他（对不上教案的问题）"
            行.append("**" + 单元格(标题) + "**")
            for 名, 回答, 原问题 in 分组[i]:
                行.append("- " + 名 + "：" + 单元格(回答) + ("" if i is not None else "　〔问：" + 单元格(原问题) + "〕"))
            行.append("")

    # ---- 四、合格线与评测 ----
    有评测 = [p for p in 学员们 if (p.get("记录") or {}).get("评测结果")]
    行 += ["## 四、合格线与评测", ""]
    if not 有评测:
        行 += ["还没有人通过 L4。", ""]
    else:
        def 键(p):
            变 = p["记录"]["评测结果"].get("变体单元", {})
            return (-float(变.get("检出率", 0)), int(变.get("误报", 0)), p["学员"])
        行 += ["| 学员 | 合格线 | 教学单元 检出 / 误报 | 变体单元 检出 / 误报 | 合格线改过 |", "|---|---|---|---|---|"]
        for p in sorted(有评测, key=键):
            线 = p.get("合格线") or {}
            结 = p["记录"]["评测结果"]
            def 格(单元):
                x = 结.get(单元) or {}
                return str(x.get("检出", "?")) + "/" + str(x.get("应检出", "?")) + " · " + str(x.get("误报", "?"))
            改过 = len(线.get("历史") or [])
            行.append("| " + " | ".join(单元格(x) for x in (
                p["学员"], ("≥ " + format(线.get("检出率", 0), ".0%") + "，误报 ≤ " + str(线.get("误报上限"))) if 线 else "—",
                格("教学单元"), 格("变体单元"), (str(改过) + " 次") if 改过 else "—")) + " |")
        行.append("")

    输出 = Path(args.out)
    输出.write_text("\n".join(行).rstrip() + "\n", encoding="utf-8")
    print("已汇总 " + str(len(学员们)) + " 人 → " + str(输出) + ("（跳过 " + str(len(跳过)) + " 个文件）" if 跳过 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
