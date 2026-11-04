#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
打包学员包：把带教智能体、教案、验收脚本、练习数据、存档点装进一个文件夹（可选 zip）。

  python3 资料/带教智能体/打包.py                       → dist/质检智能体工坊/
  python3 资料/带教智能体/打包.py --压缩 --zip           半天版，并打 zip
  python3 资料/带教智能体/打包.py --out 某个目录

打包时会用参考实现核对三件事，任何一件对不上就停（先查为什么，不要改期望值去迁就）：
  1. 21 条规则的小样本全部对上
  2. 教学单元、变体单元的结果和 出题/答案键.yaml 一模一样
  3. 红队 R1、R3 的结果符合预期
答案键只以加盐哈希进学员包；讲师目录（出题/、本脚本）不进学员包。
"""
import argparse
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.dont_write_bytecode = True
for _流 in (sys.stdout, sys.stderr):
    try:
        _流.reconfigure(encoding="utf-8")
    except Exception:
        pass

源 = Path(__file__).resolve().parent                 # 资料/带教智能体
仓库 = 源.parent.parent
标记名 = ".由打包生成"
sys.path.insert(0, str(源 / "出题"))
sys.path.insert(0, str(源 / "带教"))


def 停(文字):
    print("✗ " + 文字, file=sys.stderr)
    sys.exit(1)


def 依赖():
    缺 = []
    for 名 in ("yaml", "shapely", "pyproj"):
        try:
            __import__(名)
        except ImportError:
            缺.append(名)
    if 缺:
        停("缺 " + "、".join(缺) + "：python3 -m pip install pyyaml shapely pyproj")


def 拷(甲, 乙):
    乙 = Path(乙)
    乙.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(甲), str(乙))


def 写json(数据, 路径):
    路径 = Path(路径)
    路径.parent.mkdir(parents=True, exist_ok=True)
    with open(路径, "w", encoding="utf-8") as f:
        json.dump(数据, f, ensure_ascii=False, indent=1)
        f.write("\n")


def 关键集合(结果):
    return {(f["规则"], f["对象"], f["严重度"]) for f in 结果["findings"] if f["严重度"] in ("错误", "待确认")}


def 参考跑(包, 数据目录, 输出, 规则="all", 声明=None):
    """用包里 存档点/L2/ 的参考实现跑一遍。"""
    命令 = [sys.executable, "-X", "utf8", str(包 / "存档点" / "L2" / "qc_tools.py"),
          "--rulebook", str(包 / "存档点" / "L2" / "规则库_完整.yaml"),
          "--data", str(数据目录), "--out", str(输出), "--rules", 规则]
    if 声明:
        命令 += ["--claims", str(声明)]
    环境 = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    r = subprocess.run(命令, capture_output=True, text=True, encoding="utf-8", errors="replace", env=环境, cwd=str(包))
    if r.returncode != 0 or not Path(输出).is_file():
        停("参考实现跑不通（" + str(数据目录) + "）：\n" + r.stdout[-800:] + r.stderr[-800:])
    with open(输出, encoding="utf-8") as f:
        return json.load(f)


def 生成L1存档点(参考, 必做):
    yaml = __import__("yaml")
    规则们 = []
    for r in 参考["规则"]:
        if r["id"] in 必做:
            r = dict(r)
            r.pop("参数", None)          # 参数是 L2 的事：存档点 L1 不替学员决定「阈值写在哪」
            规则们.append(r)
    数据 = {"版本": "存档点 L1（参考规则库里的 " + str(len(规则们)) + " 条）", "审定人": "（学员签字）",
          "说明": "这是存档点：先和你自己写的对比差在哪，核对无误后在「审定人」签上你的名字。",
          "用词与严重度": 参考.get("用词与严重度"), "规则": 规则们}
    return "# 规则库 · 存档点 L1\n" + yaml.safe_dump(数据, allow_unicode=True, sort_keys=False, width=1000, default_flow_style=None)


def main():
    ap = argparse.ArgumentParser(description="打包学员包（说明见文件开头）")
    ap.add_argument("--out", default=str(仓库 / "dist" / "质检智能体工坊"))
    ap.add_argument("--压缩", dest="压缩", action="store_true", help="半天版：L1 只做 3 条，L5 只做 R1")
    ap.add_argument("--zip", action="store_true", help="另外打一个 zip")
    args = ap.parse_args()
    依赖()
    import yaml
    import common
    import 小样本
    import 变体与红队 as 变体

    包 = Path(args.out).resolve()
    if 包.exists():
        if not (包 / 标记名).is_file():
            停(str(包) + " 已存在且不是打包生成的目录，换一个 --out")
        shutil.rmtree(str(包))
    包.mkdir(parents=True)
    print("打包到 " + str(包))

    # ---------- 1. 拷文件 ----------
    拷(源 / "学员包" / "CLAUDE.md", 包 / "CLAUDE.md")
    先读我 = (源 / "学员包" / "先读我.md").read_text(encoding="utf-8")
    if args.压缩:
        先读我 = 先读我.replace("亲手抽 5 条规则", "亲手抽 3 条规则").replace("给这 5 条写检查函数", "给这 3 条写检查函数")
    (包 / "先读我.md").write_text(先读我, encoding="utf-8")
    拷(源 / "学员包" / "settings.json", 包 / ".claude" / "settings.json")
    拷(源 / "coach" / "SKILL.md", 包 / ".claude" / "skills" / "coach" / "SKILL.md")
    for p in sorted((源 / "带教").glob("*.py")):
        拷(p, 包 / "带教" / p.name)
    教案 = (源 / "关卡.yaml").read_text(encoding="utf-8")
    版本行 = "课时版本: " + ("压缩" if args.压缩 else "完整")
    if "\n课时版本:" in 教案:
        教案 = "\n".join(版本行 if 行.startswith("课时版本:") else 行 for 行 in 教案.split("\n"))
    else:
        教案 = 教案.replace("\n版本:", "\n" + 版本行 + "\n版本:", 1)
    (包 / "带教" / "关卡.yaml").write_text(教案, encoding="utf-8")
    for p in sorted((仓库 / "data" / "qc").iterdir()):
        if p.is_file():
            拷(p, 包 / "data" / "qc" / p.name)
    for p in sorted((仓库 / "资料" / "质检智能体").iterdir()):
        if p.is_file():
            拷(p, 包 / "资料" / "质检智能体" / p.name)
    拷(源 / "学员包" / "迁移卡示例.md", 包 / "资料" / "迁移卡示例.md")
    拷(源 / "qc_agent" / "qc_tools.py", 包 / "qc_agent" / "qc_tools.py")
    拷(源 / "qc_agent" / "我的检查.py", 包 / "qc_agent" / "我的检查.py")
    拷(源 / "qc_agent" / "qc_tools.py", 包 / "存档点" / "L2" / "qc_tools.py")
    拷(源 / "存档点" / "L2" / "参考检查.py", 包 / "存档点" / "L2" / "参考检查.py")
    拷(仓库 / "资料" / "质检智能体" / "规则库_参考.yaml", 包 / "存档点" / "L2" / "规则库_完整.yaml")
    拷(源 / "存档点" / "L3" / "SKILL.md", 包 / "存档点" / "L3" / "SKILL.md")
    参考 = yaml.safe_load((仓库 / "资料" / "质检智能体" / "规则库_参考.yaml").read_text(encoding="utf-8"))
    L1 = yaml.safe_load(教案)["关卡"][1]["规则"]
    必做 = L1["压缩版只做"] if args.压缩 else [r["id"] for r in L1["必做"]]
    (包 / "存档点" / "L1").mkdir(parents=True, exist_ok=True)
    (包 / "存档点" / "L1" / "规则库.yaml").write_text(生成L1存档点(参考, 必做), encoding="utf-8")

    # ---------- 2. 生成小样本、变体单元、红队 ----------
    样本 = 小样本.生成()
    for 规则, 内容 in 样本.items():
        写json(内容, 包 / "带教" / "小样本" / (规则 + ".json"))
    变体文件, 变体数字 = 变体.生成变体(仓库 / "data" / "qc")
    变体.写出(变体文件, 包 / "带教" / "变体单元")
    for 名, 文件 in 变体.生成红队(仓库 / "data" / "qc").items():
        变体.写出(文件, 包 / "带教" / "红队" / 名)
    print("✓ 小样本 " + str(len(样本)) + " 份、变体单元、红队 R1/R3 已生成")

    # ---------- 3. 用参考实现核对 ----------
    临时 = Path(tempfile.mkdtemp(prefix="打包核对_"))
    try:
        坏 = []
        份数 = 0
        for 规则, 内容 in 样本.items():
            for i, 数据集 in enumerate(内容["数据集"]):
                目录 = common.落盘(数据集, 临时 / ("样本_" + 规则 + "_" + str(i)))
                声明 = 目录 / "claims.json" if "claims.json" in 数据集["文件"] else None
                结果 = 参考跑(包, 目录, 目录 / "out" / "findings.json", 规则, 声明)
                坏 += [规则 + "「" + 数据集["名称"] + "」" + x for x in common.对照期望(结果["findings"], 规则, 数据集["期望"])]
                份数 += 1
        if 坏:
            停("参考实现和小样本的期望对不上：\n  " + "\n  ".join(坏))
        print("✓ 小样本 " + str(份数) + " 份：参考实现全部对上")

        答案 = yaml.safe_load((源 / "出题" / "答案键.yaml").read_text(encoding="utf-8"))
        写json(变体.教学单元说明书数字(), 临时 / "教学.json")
        写json(变体数字, 临时 / "变体.json")
        实际 = {
            "教学单元": 参考跑(包, 包 / "data" / "qc", 临时 / "教学" / "findings.json", 声明=临时 / "教学.json"),
            "变体单元": 参考跑(包, 包 / "带教" / "变体单元", 临时 / "变体" / "findings.json", 声明=临时 / "变体.json"),
        }
        for 单元 in ("教学单元", "变体单元"):
            期望 = {tuple(x[:3]) for x in 答案[单元]}
            有 = 关键集合(实际[单元])
            if 有 != 期望:
                停(单元 + "：参考实现的结果和答案键对不上。\n  答案键有、实际没有：" + str(sorted(期望 - 有))
                   + "\n  实际有、答案键没有：" + str(sorted(有 - 期望)) + "\n先查为什么，不要改答案键去迁就实现。")
            print("✓ " + 单元 + "：参考实现报出的 " + str(len(有)) + " 条错误/待确认和答案键一模一样")
        import 核对表
        核对文字 = 核对表.生成(实际, {"教学单元": 包 / "data" / "qc", "变体单元": 包 / "带教" / "变体单元"}, 参考, 答案)
        核对文件 = 源 / "出题" / "答案键_核对表.md"
        if 核对文件.is_file():
            旧文字 = 核对文件.read_text(encoding="utf-8")
            核对文字 = 核对表.保留勾选(旧文字, 核对文字)
            if 旧文字 != 核对文字:
                核对文件.write_text(核对文字, encoding="utf-8")
        else:
            核对文件.write_text(核对文字, encoding="utf-8")
        已勾 = 核对文字.count("- [x] 认可")
        if 已勾:
            print("  核对表已勾 " + str(已勾) + " / " + str(已勾 + 核对文字.count("- [ ] 认可")) + " 条")
        print("✓ 答案键核对表：资料/带教智能体/出题/答案键_核对表.md（讲师逐条打勾用）")
        for 名 in ("R1", "R3"):
            结果 = 参考跑(包, 包 / "带教" / "红队" / 名, 临时 / 名 / "findings.json", 声明=临时 / "教学.json")
            if 关键集合(结果) != 关键集合(实际["教学单元"]):
                停("红队 " + 名 + "：错误/待确认应该和教学单元一样")
            if 名 == "R1" and not any(x["对象"] == "21-02" and "跳过" in x["文本"] for x in 结果["自由文本"]):
                停("红队 R1：21-02 的注入备注没出现在自由文本里")
            if 名 == "R3" and not any(f["规则"] == "Q17" and f["对象"] == "14-01" and f["严重度"] == "无法检查" for f in 结果["findings"]):
                停("红队 R3：14-01 应该是 Q17 无法检查")
        print("✓ 红队 R1、R3：结果符合预期")
    finally:
        shutil.rmtree(str(临时), ignore_errors=True)

    # ---------- 4. 答案键（加盐哈希）----------
    盐 = secrets.token_hex(8)
    键 = {"说明": "只存哈希：sha256(盐|规则|对象)。只算错误和待确认。", "盐": 盐}
    for 单元 in ("教学单元", "变体单元"):
        按规则 = {}
        for 规则, 对象, _ in sorted(tuple(x[:3]) for x in 答案[单元]):
            按规则.setdefault(规则, []).append(hashlib.sha256((盐 + "|" + 规则 + "|" + 对象).encode("utf-8")).hexdigest())
        键[单元] = 按规则
    写json(键, 包 / "带教" / "答案键.json")

    # ---------- 5. 讲师文件清单 ----------
    清单 = []
    for 目录 in ("带教", "data", "资料", "存档点"):
        for p in sorted((包 / 目录).rglob("*")):
            if p.is_file() and p.name != "manifest.sha256" and "__pycache__" not in p.parts:
                清单.append(common.文件哈希(p) + "  " + p.relative_to(包).as_posix())
    for 名 in (".claude/settings.json", ".claude/skills/coach/SKILL.md"):
        清单.append(common.文件哈希(包 / 名) + "  " + 名)
    (包 / "带教" / "manifest.sha256").write_text("# 讲师文件哈希：验收脚本开头会核对\n" + "\n".join(清单) + "\n", encoding="utf-8")
    (包 / 标记名).write_text("由 资料/带教智能体/打包.py 生成；重新打包会整个删掉重建。\n", encoding="utf-8")

    文件数 = sum(1 for p in 包.rglob("*") if p.is_file())
    print("✓ 讲师文件清单 " + str(len(清单)) + " 个；学员包共 " + str(文件数) + " 个文件；课时版本：" + ("压缩" if args.压缩 else "完整"))
    if args.zip:
        压缩包 = 包.with_suffix(".zip")
        with zipfile.ZipFile(str(压缩包), "w", zipfile.ZIP_DEFLATED) as z:
            for p in sorted(包.rglob("*")):
                if p.is_file() and p.name != 标记名:
                    z.write(str(p), (Path(包.name) / p.relative_to(包)).as_posix())
        print("✓ " + str(压缩包) + "（" + format(压缩包.stat().st_size / 1024, ".0f") + " KB）")
    if str(答案.get("状态")) != "已核对" or "待" in str(答案.get("审定人")):
        print("⚠ 答案键还没经讲师核对签字（出题/答案键.yaml）：发给学员之前先核对。")


if __name__ == "__main__":
    main()
