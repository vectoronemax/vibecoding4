#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
学习进度 —— 带教智能体用它读写 学习进度.json（这个文件只能用本脚本和验收脚本改）。

  python3 带教/progress.py show                          看进度（每次开场先跑）
  python3 带教/progress.py stage [关]                    打印这一关的教案（默认当前关）
  python3 带教/progress.py init --name 姓名 --route 业务|技术
  python3 带教/progress.py route 业务|技术               换路线
  python3 带教/progress.py decide 关 "问题" "学员原话"    记一条学员的决定
  python3 带教/progress.py hint 关 级                    记用了第几级提示（1–3；第 4 级用 checkpoint）
  python3 带教/progress.py checkpoint 关                 复制存档点（L1、L2、L3），先备份学员自己的文件
  python3 带教/progress.py merge                         L2 过关后：并入其余规则和参考检查函数
  python3 带教/progress.py redline --recall 0.9 --fp 3 [--reason 理由]   定 / 改合格线（L4）
  python3 带教/progress.py card                          一行进度码（贴到班级群）

没有「标记通过」的命令：关卡只能由 带教/check_Lx.py 验收通过。
"""
import sys

sys.dont_write_bytecode = True

import argparse
import shutil
from pathlib import Path

import common as c

路线们 = ["业务", "技术"]


def _要档案():
    进度 = c.读进度()
    if 进度 is None:
        print("还没有档案。先做诊断三问，再运行：")
        print("  python3 带教/progress.py init --name <姓名> --route <业务|技术>")
        sys.exit(1)
    return 进度


def _检查关(关):
    if 关 not in c.关卡顺序:
        print("关卡写错了：" + str(关) + "（只能是 " + " ".join(c.关卡顺序) + "）")
        sys.exit(2)


def _备份(路径):
    路径 = Path(路径)
    if not 路径.exists():
        return None
    目标 = c.作品目录 / "_备份" / c.现在().replace(":", "")
    目标.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(路径), str(目标 / 路径.name))
    return 目标 / 路径.name


# ------------------------------------------------------------ show / card / stage

def 命令_show(参数):
    进度 = c.读进度()
    if 进度 is None:
        print("状态：还没建档")
        print("下一步：做诊断三问，然后 python3 带教/progress.py init --name <姓名> --route <业务|技术>")
        return
    当前 = 进度.get("当前关")
    print("学员：" + 进度["学员"] + "　路线：" + 进度["路线"] + "　课时版本：" + c.课时版本())
    标记 = {"已通过": "✓", "进行中": "…", "未开始": "·"}
    print("关卡：" + "  ".join(关 + 标记.get(进度["关卡"][关]["状态"], "?") for 关 in c.关卡顺序))
    if 当前 == "完成":
        print("七关已全部通过。")
        return
    段 = 进度["关卡"][当前]
    定义 = c.关卡定义(当前)
    print("当前：" + 当前 + " " + c.关卡名[当前] + "（" + 段["状态"] + "，已验收 " + str(段.get("验收次数") or 0) + " 次）")
    if 定义.get("目标"):
        print("目标：" + str(定义["目标"]))
    最近 = 段.get("最近验收")
    if 最近:
        print("最近一次验收：" + 最近["结果"] + "（" + 最近["时间"] + "）")
        for 项 in 最近.get("没过", [])[:6]:
            print("  ✗ " + 项)
    决策 = c.本关决策(进度, 当前)
    最少 = int(定义.get("最少决策数") or 0)
    print("本关已记的决定：" + str(len(决策)) + " 条（至少 " + str(最少) + " 条）")
    for d in 决策:
        print("  - " + d["问题"] + " → " + d["回答"])
    if 段.get("提示"):
        print("本关用过的提示：" + "、".join(str(x) + " 级" for x in 段["提示"]))
    if 段.get("存档点"):
        print("本关用过存档点")
    if 进度.get("记录", {}).get("我的规则"):
        print("学员亲手写的规则：" + " ".join(进度["记录"]["我的规则"]))
    if 进度.get("合格线"):
        线 = 进度["合格线"]
        print("合格线：检出率 ≥ " + format(线["检出率"], ".0%") + "，误报 ≤ " + str(线["误报上限"]) + " 条（" + 线["时间"] + "）")
    if len(决策) < 最少:
        建议 = "问决策题（本关还差 " + str(最少 - len(决策)) + " 条决定），一次只问一题"
    elif not 最近:
        建议 = "动手；做完运行 python3 带教/check_" + 当前 + ".py"
    elif 最近["结果"] == "未通过":
        建议 = "看上面没过的项，按提示阶梯帮学员改，改完再验收"
    else:
        建议 = "复盘，然后进入下一关"
    print("下一步：" + 建议)


def 命令_card(参数):
    进度 = _要档案()
    已过 = [关 for 关 in c.关卡顺序 if c.已通过(进度, 关)]
    提示 = sum(len(进度["关卡"][关].get("提示") or []) for 关 in c.关卡顺序)
    存档 = sum(1 for 关 in c.关卡顺序 if 进度["关卡"][关].get("存档点"))
    当前 = 进度.get("当前关")
    print("｜".join([进度["学员"], 进度["路线"], (当前 + " 进行中") if 当前 != "完成" else "全部通过",
                    "已过 " + (" ".join(已过) or "无"), "提示 " + str(提示) + " 次", "存档点 " + str(存档) + " 次",
                    "决定 " + str(len(进度.get("决策", []))) + " 条"]))


def 命令_stage(参数):
    yaml = c.需要yaml()
    进度 = c.读进度()
    关 = 参数.关 or (进度 or {}).get("当前关") or "L0"
    if 关 == "完成":
        print("七关已全部通过。")
        return
    _检查关(关)
    定义 = c.关卡定义(关)
    print("# " + 关 + " " + c.关卡名[关] + "（课时版本：" + c.课时版本() + "；「追问要点」给你判断用，不要整段念给学员）")
    print(yaml.safe_dump(定义, allow_unicode=True, sort_keys=False, width=1000).rstrip())


# ------------------------------------------------------------ init / route / decide / hint

def 命令_init(参数):
    if c.读进度() is not None:
        print("已经有档案了（学习进度.json）。要看进度用 show；换路线用 route。")
        sys.exit(1)
    if 参数.route not in 路线们:
        print("路线只能是：业务 或 技术")
        sys.exit(2)
    进度 = c.新进度(参数.name.strip(), 参数.route)
    c.写进度(进度)
    print("建档完成：" + 参数.name + "，" + 参数.route + "路线。当前关：L0 岗位说明书")
    try:
        import check_env
        问题们 = check_env.检查环境()
    except Exception as e:
        问题们 = ["环境检查没跑成：" + str(e)]
    if 问题们:
        print("环境还有问题：")
        for 问题 in 问题们:
            print("  ✗ " + 问题)
    else:
        print("环境检查：Python、PyYAML、shapely、pyproj 都齐了。")


def 命令_route(参数):
    进度 = _要档案()
    if 参数.路线 not in 路线们:
        print("路线只能是：业务 或 技术")
        sys.exit(2)
    旧 = 进度["路线"]
    进度["路线"] = 参数.路线
    c.记日志(进度, "换路线", 从=旧, 到=参数.路线)
    c.写进度(进度)
    print("路线：" + 旧 + " → " + 参数.路线)


def 命令_decide(参数):
    进度 = _要档案()
    _检查关(参数.关)
    问题, 回答 = 参数.问题.strip(), 参数.回答.strip()
    if not 问题 or not 回答:
        print("问题和学员原话都不能空")
        sys.exit(2)
    进度.setdefault("决策", []).append({"关": 参数.关, "问题": 问题, "回答": 回答, "时间": c.现在()})
    c.记日志(进度, "决定", 关=参数.关)
    c.写进度(进度)
    print("记下了（" + 参数.关 + " 第 " + str(len(c.本关决策(进度, 参数.关))) + " 条）：" + 问题 + " → " + 回答)


def 命令_hint(参数):
    进度 = _要档案()
    _检查关(参数.关)
    if 参数.级 not in (1, 2, 3):
        print("这里只记 1–3 级；第 4 级（存档点）用：python3 带教/progress.py checkpoint " + 参数.关)
        sys.exit(2)
    进度["关卡"][参数.关].setdefault("提示", []).append(参数.级)
    c.记日志(进度, "提示", 关=参数.关, 级=参数.级)
    c.写进度(进度)
    print("记下了：" + 参数.关 + " 用了第 " + str(参数.级) + " 级提示")


# ------------------------------------------------------------ 规则库合并

def _读规则库(路径):
    return c.读yaml(路径) or {}


def _写规则库(数据, 路径):
    yaml = c.需要yaml()
    with open(路径, "w", encoding="utf-8") as f:
        f.write("# 规则库（由 progress.py 合并生成；原文件备份在 qc_agent/_备份/）\n")
        yaml.safe_dump(数据, f, allow_unicode=True, sort_keys=False, width=1000, default_flow_style=None)


def _合并规则库(补参数=False):
    """把参考规则库里学员还没有的规则并进 qc_agent/规则库.yaml。返回 (新增的 id 列表, 备份路径)。"""
    参考路径 = c.存档点目录 / "L2" / "规则库_完整.yaml"
    参考 = _读规则库(参考路径)
    我的路径 = c.作品目录 / "规则库.yaml"
    if not 我的路径.is_file():
        print("还没有 qc_agent/规则库.yaml —— 先过 L1")
        sys.exit(1)
    我的 = _读规则库(我的路径)
    我的规则 = {str(r.get("id")): r for r in (我的.get("规则") or []) if isinstance(r, dict)}
    参考规则 = 参考.get("规则") or []
    参考函数 = set()
    参考文件 = c.作品目录 / "参考检查.py"
    if 参考文件.is_file():
        import ast
        参考函数 = {n.name for n in ast.parse(c.读文本(参考文件)).body if isinstance(n, ast.FunctionDef)}
    新增, 合并后 = [], []
    for r in 参考规则:
        if r["id"] in 我的规则:
            mine = 我的规则.pop(r["id"])
            if 补参数:
                if not mine.get("参数"):
                    mine["参数"] = r.get("参数")
                我的函数 = _我的函数名()
                if mine.get("检查") not in 我的函数 and mine.get("检查") not in 参考函数:
                    mine["检查"] = r.get("检查")
            合并后.append(mine)
        else:
            合并后.append(r)
            新增.append(r["id"])
    合并后 += list(我的规则.values())   # 学员自创的规则放最后
    我的["规则"] = 合并后
    for 键 in ("用词与严重度", "依据文件", "不适用"):
        if 键 not in 我的 and 键 in 参考:
            我的[键] = 参考[键]
    备份 = _备份(我的路径)
    _写规则库(我的, 我的路径)
    return 新增, 备份


def _我的函数名():
    import ast
    路径 = c.作品目录 / "我的检查.py"
    if not 路径.is_file():
        return set()
    try:
        return {n.name for n in ast.parse(c.读文本(路径)).body if isinstance(n, ast.FunctionDef)}
    except SyntaxError:
        return set()


def _复制参考检查():
    源 = c.存档点目录 / "L2" / "参考检查.py"
    shutil.copy2(str(源), str(c.作品目录 / "参考检查.py"))


def 命令_merge(参数):
    进度 = _要档案()
    if not c.已通过(进度, "L2") and not 进度["关卡"]["L2"].get("存档点"):
        print("L2 还没通过。先让学员自己的规则过了验收，再合并。")
        sys.exit(1)
    _复制参考检查()
    新增, 备份 = _合并规则库()
    c.记日志(进度, "合并", 新增=新增)
    进度.setdefault("记录", {})["已合并"] = True
    c.写进度(进度)
    print("已并入参考检查函数（qc_agent/参考检查.py）和 " + str(len(新增)) + " 条规则：" + " ".join(新增))
    if 备份:
        print("原规则库备份在：" + c.相对(备份))
    print("学员自己的规则保留原样。现在再跑一次：python3 带教/check_L2.py（会用小样本核对全部规则）")


# ------------------------------------------------------------ checkpoint

def 命令_checkpoint(参数):
    进度 = _要档案()
    关 = 参数.关
    _检查关(关)
    if 关 == "L1":
        源 = c.存档点目录 / "L1" / "规则库.yaml"
        备份 = _备份(c.作品目录 / "规则库.yaml")
        c.作品目录.mkdir(exist_ok=True)
        shutil.copy2(str(源), str(c.作品目录 / "规则库.yaml"))
        说明 = "已复制存档点 L1 → qc_agent/规则库.yaml（参考库里这几条规则）。审定人还空着：学员核对后签上自己的名字。"
    elif 关 == "L2":
        _复制参考检查()
        新增, 备份 = _合并规则库(补参数=True)
        说明 = ("已复制参考检查函数 → qc_agent/参考检查.py，并入 " + str(len(新增)) + " 条规则；学员自己的规则缺「参数」的补上了参考值。"
              "学员写好的函数仍然优先；对比一下自己的和参考的差在哪。")
        进度.setdefault("记录", {})["已合并"] = True
    elif 关 == "L3":
        目标 = c.根目录 / ".claude" / "skills" / "qc" / "SKILL.md"
        备份 = _备份(目标)
        目标.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(c.存档点目录 / "L3" / "SKILL.md"), str(目标))
        说明 = "已复制存档点 L3 → .claude/skills/qc/SKILL.md（参考 qc skill）。开一个新会话才能用 /qc。"
    else:
        print(关 + " 没有存档点（只有 L1、L2、L3 有）。按提示阶梯帮学员。")
        sys.exit(1)
    段 = 进度["关卡"][关]
    段["存档点"] = True
    段.setdefault("提示", []).append(4)
    c.记日志(进度, "存档点", 关=关)
    c.写进度(进度)
    print(说明)
    if 备份:
        print("学员原来的文件备份在：" + c.相对(备份) + "（留着，对比差在哪）")


# ------------------------------------------------------------ redline

def 命令_redline(参数):
    进度 = _要档案()
    检出率 = 参数.recall / 100.0 if 参数.recall > 1 else 参数.recall
    if not (0 < 检出率 <= 1) or 参数.fp < 0:
        print("检出率要在 0–1 之间（或 1–100 的百分数），误报上限要 ≥ 0")
        sys.exit(2)
    旧 = 进度.get("合格线")
    if 旧 and not (参数.reason or "").strip():
        print("合格线已经定过了（检出率 ≥ " + format(旧["检出率"], ".0%") + "，误报 ≤ " + str(旧["误报上限"]) + "）。"
              "要改，必须用 --reason 写清楚为什么改——期望值只由人改，而且要留下理由。")
        sys.exit(1)
    新 = {"检出率": 检出率, "误报上限": 参数.fp, "理由": (参数.reason or "").strip(), "时间": c.现在(),
          "历史": ((旧.get("历史") or []) + [{k: 旧[k] for k in ("检出率", "误报上限", "理由", "时间")}]) if 旧 else []}
    进度["合格线"] = 新
    c.记日志(进度, "合格线", 检出率=检出率, 误报上限=参数.fp)
    c.写进度(进度)
    print("合格线：检出率 ≥ " + format(检出率, ".0%") + "，误报 ≤ " + str(参数.fp) + " 条（" + 新["时间"] + "）")
    if 旧:
        print("注意：改了合格线以后，评测要重跑——验收只认合格线之后跑出来的结果。")


def main():
    c.设置输出()
    ap = argparse.ArgumentParser(description="学习进度（说明见文件开头）")
    子 = ap.add_subparsers(dest="命令")
    子.add_parser("show")
    子.add_parser("card")
    p = 子.add_parser("stage"); p.add_argument("关", nargs="?")
    p = 子.add_parser("init"); p.add_argument("--name", required=True); p.add_argument("--route", required=True)
    p = 子.add_parser("route"); p.add_argument("路线")
    p = 子.add_parser("decide"); p.add_argument("关"); p.add_argument("问题"); p.add_argument("回答")
    p = 子.add_parser("hint"); p.add_argument("关"); p.add_argument("级", type=int)
    p = 子.add_parser("checkpoint"); p.add_argument("关")
    子.add_parser("merge")
    p = 子.add_parser("redline"); p.add_argument("--recall", type=float, required=True)
    p.add_argument("--fp", type=int, required=True); p.add_argument("--reason", default="")
    参数 = ap.parse_args()
    if not 参数.命令:
        ap.print_help()
        return
    globals()["命令_" + 参数.命令](参数)


if __name__ == "__main__":
    main()
