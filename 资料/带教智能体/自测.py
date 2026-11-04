#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自测：打一个学员包到临时目录，扮演学员从 L0 走到 L6；每关先做反向测试（该拦的拦住），再做正向测试。

  python3 资料/带教智能体/自测.py            跑完删掉临时目录
  python3 资料/带教智能体/自测.py --保留      留着学员包，方便看

/qc 用「模拟 qc」代替真模型：读标准说明书数字 → 调 qc_tools.py → 按模板写报告。
所以这里验证的是验收脚本、进度、钩子和工具链；真模型的试跑见 01_讲师手册.md「试跑」。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.dont_write_bytecode = True
for _流 in (sys.stdout, sys.stderr):
    try:
        _流.reconfigure(encoding="utf-8")
    except Exception:
        pass

源 = Path(__file__).resolve().parent
仓库 = 源.parent.parent
样例 = 源 / "出题" / "自测样例"
sys.path.insert(0, str(源 / "出题"))
import 变体与红队 as 变体  # noqa: E402

记录 = []


def 记(名称, 成立, 细节=""):
    记录.append((名称, bool(成立)))
    print(("  ✓ " if 成立 else "  ✗ ") + 名称)
    if not 成立 and 细节:
        print("     " + "\n     ".join(str(细节).strip().splitlines()[-25:]))


def 跑(包, *命令, 环境=None, 输入=None):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    env.update(环境 or {})
    r = subprocess.run([sys.executable, "-X", "utf8"] + [str(x) for x in 命令], cwd=str(包), capture_output=True,
                       text=True, encoding="utf-8", errors="replace", env=env, input=输入)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def 检(包, 关, 期望通过, 名称, 必含=None):
    码, 文 = 跑(包, "带教/check_" + 关 + ".py")
    成立 = (码 == 0) == 期望通过 and (必含 is None or 必含 in 文)
    记(名称, 成立, 文)
    return 文


def 定(包, 关, n):
    for i in range(n):
        跑(包, "带教/progress.py", "decide", 关, "自测问题 " + str(i + 1), "自测学员的回答 " + str(i + 1))


def 写(路径, 文字):
    路径 = Path(路径)
    路径.parent.mkdir(parents=True, exist_ok=True)
    路径.write_text(文字, encoding="utf-8")


def 写json(路径, 数据):
    写(路径, json.dumps(数据, ensure_ascii=False, indent=1))


# ------------------------------------------------------------ 模拟 qc

def 写报告(包, 结果, 数据目录, 路径, 漏写=None, 多写=None, 不写声明节=False):
    信息, 统计 = 结果["运行信息"], 结果["统计"]
    if 漏写 == "首条错误":
        漏写 = next(f["编号"] for f in 结果["findings"] if f["严重度"] == "错误")
    行 = ["# 质检报告 · " + str(信息["单元名称"]), "",
         "- 数据目录：" + 信息["数据目录"],
         "- 规则库：" + 信息["规则库"] + "（版本 " + str(信息["规则库版本"]) + "，审定人 " + str(信息["审定人"]) + "）",
         "- 工具：qc_tools.py " + 信息["框架版本"] + "，运行时间 " + 信息["运行时间"],
         "- 结果：" + " · ".join(k + " " + str(统计[k]) + " 条" for k in ("错误", "待确认", "提示", "无法检查")), ""]

    def 列(严重度):
        条们 = ["- [" + f["编号"] + "] " + f["规则"] + " · " + f["对象"] + " —— 实际 " + str(f["实际值"]) + " / 限值 "
              + str(f["限值"]) + " —— " + f["说明"] for f in 结果["findings"] if f["严重度"] == 严重度 and f["编号"] != 漏写]
        return 条们 or ["- 无"]

    行 += ["## 一、错误"] + 列("错误") + ["", "## 二、待确认（需要人判断）"] + 列("待确认") + ["", "## 三、提示"] + 列("提示") + [""]
    if not 不写声明节:
        关键词 = ("跳过", "同意", "无需", "审定")
        声明 = ["- " + x["对象"] + "（备注）：「" + x["文本"] + "」 —— 未照此执行，已照常检查"
              for x in 结果["自由文本"] if any(k in x["文本"] for k in 关键词)]
        说明书 = next((包 / 数据目录).glob("*_说明书.md")).read_text(encoding="utf-8")
        声明 += ["- 说明书：「" + 句.strip("> ").strip() + "」 —— 未照此执行，已照常比对"
               for 句 in 说明书.splitlines() if any(k in 句 for k in ("跳过", "无需"))]
        行 += ["## 四、需人工核实的声明"] + (声明 or ["- 无"]) + [""]
    行 += ["## 五、未检查及原因"]
    行 += ["- [" + f["编号"] + "] " + f["规则"] + " · " + f["对象"] + "：无法检查 —— " + f["说明"]
          for f in 结果["findings"] if f["严重度"] == "无法检查"]
    行 += ["- " + str(x.get("条文") or x.get("规则")) + "：" + x["原因"] for x in 结果["未检查"]]
    if 多写:
        行 += ["", "## 补充", "- [" + 多写 + "] 模型自己补的结论"]
    行 += ["", "## 六、说明", "- 说明书数字由模型读取（见 claims.json），比对、判定全部由 qc_tools.py 完成。"]
    写(路径, "\n".join(行) + "\n")


def 模拟qc(包, 数据目录, 输出目录, 声明, **报告参数):
    输出 = 包 / 输出目录
    写json(输出 / "claims.json", 声明)
    码, 文 = 跑(包, "qc_agent/qc_tools.py", "--data", 数据目录, "--claims", 输出目录 + "/claims.json",
              "--out", 输出目录 + "/findings.json")
    if 码 != 0:
        raise RuntimeError("模拟 qc 跑不通：" + 文)
    结果 = json.loads((输出 / "findings.json").read_text(encoding="utf-8"))
    写报告(包, 结果, 数据目录, 输出 / "质检报告.md", **报告参数)
    return 结果


def 钩子(包, 路径, 根=None):
    码, _ = 跑(包, "带教/guard.py", 环境={"CLAUDE_PROJECT_DIR": str(根 or 包)},
             输入=json.dumps({"tool_name": "Write", "tool_input": {"file_path": str(路径)}}))
    return 码


# ------------------------------------------------------------ 走一遍

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--保留", dest="保留", action="store_true")
    ap.add_argument("--压缩", dest="压缩", action="store_true", help="测半天版：L1 只做 3 条，L5 只做 R1")
    args = ap.parse_args()
    我的规则 = ["Q03", "Q08", "Q15"] if args.压缩 else ["Q03", "Q04", "Q08", "Q09", "Q15"]
    临时 = Path(tempfile.mkdtemp(prefix="带教自测_"))
    包 = 临时 / "质检智能体工坊"
    try:
        print("【打包】")
        码, 文 = 跑(仓库, 源 / "打包.py", "--out", 包, *(["--压缩"] if args.压缩 else []))
        记("打包成功，参考实现核对通过", 码 == 0, 文)
        if 码 != 0:
            return 1
        教学数字 = 变体.教学单元说明书数字()
        _, 变体数字 = 变体.生成变体(仓库 / "data" / "qc")

        print("【建档与钩子】")
        码, 文 = 跑(包, "带教/progress.py", "show")
        记("没建档时 show 提示先建档", "还没建档" in 文, 文)
        检(包, "L0", False, "没建档不能验收", "还没建档")
        码, 文 = 跑(包, "带教/check_env.py")
        记("环境检查通过", 码 == 0, 文)
        码, 文 = 跑(包, "带教/progress.py", "init", "--name", "自测学员", "--route", "业务")
        记("建档", 码 == 0, 文)
        码, 文 = 跑(包, "带教/progress.py", "init", "--name", "又一个", "--route", "技术")
        记("不能重复建档", 码 != 0, 文)
        for 路径 in ("带教/关卡.yaml", "data/qc/教学单元_地块.geojson", "资料/质检智能体/规则库_参考.yaml",
                   "存档点/L2/参考检查.py", "学习进度.json", ".claude/settings.json", ".claude/skills/coach/SKILL.md"):
            记("钩子拦下写入 " + 路径, 钩子(包, 包 / 路径) == 2)
        记("钩子拦下相对路径 带教/check_L4.py", 钩子(包, "带教/check_L4.py") == 2)
        for 路径 in ("qc_agent/我的检查.py", ".claude/skills/qc/SKILL.md", "qc_agent/报告/质检报告.md"):
            记("钩子放行 " + 路径, 钩子(包, 包 / 路径) == 0)
        码, 文 = 跑(包, "带教/progress.py", "hint", "L0", "4")
        记("hint 不收第 4 级（要用 checkpoint）", 码 != 0, 文)

        print("【L0 岗位说明书】")
        检(包, "L0", False, "没交说明书不过", "没有 qc_agent/岗位说明书.md")
        好说明书 = (样例 / "岗位说明书.md").read_text(encoding="utf-8")
        写(包 / "qc_agent/岗位说明书.md", 好说明书)
        检(包, "L0", False, "决策记录不够不过", "决策记录只有 0 条")
        定(包, "L0", 3)
        写(包 / "qc_agent/岗位说明书.md", re.sub(r"## 不做\n\n(?:- .*\n)+", "## 不做\n\n- 不改规则\n- 不心算\n", 好说明书))
        检(包, "L0", False, "「不做」少于 3 条不过", "「不做」只列了 2 条")
        写(包 / "qc_agent/岗位说明书.md", 好说明书)
        检(包, "L0", True, "L0 通过")

        print("【L1 从条文抽规则】")
        检(包, "L1", False, "没有规则库不过", "没有 qc_agent/规则库.yaml")
        定(包, "L1", 5)
        存档 = (包 / "存档点/L1/规则库.yaml").read_text(encoding="utf-8")
        写(包 / "qc_agent/规则库.yaml", 存档)
        检(包, "L1", False, "没签字不过", "审定人")
        已签 = 存档.replace("审定人: （学员签字）", "审定人: 自测学员")
        写(包 / "qc_agent/规则库.yaml", 已签.replace("不得建设超高层（100米以上）住宅建筑。", "不得建设 100 米以上的超高层住宅。"))
        检(包, "L1", False, "原文被改写不过", "Q08「原文」在条文摘录里找不到")
        import yaml
        坏 = yaml.safe_load(已签)
        for r in 坏["规则"]:
            if r["id"] == "Q15":
                r["用词"] = "宜"
        写(包 / "qc_agent/规则库.yaml", yaml.safe_dump(坏, allow_unicode=True, sort_keys=False))
        检(包, "L1", False, "「宜」判成错误不过", "Q15 用词是「宜」")
        写(包 / "qc_agent/规则库.yaml", 已签)
        检(包, "L1", True, "L1 通过")
        进度 = json.loads((包 / "学习进度.json").read_text(encoding="utf-8"))
        记("记下了学员亲手写的 " + str(len(我的规则)) + " 条规则", 进度["记录"].get("我的规则") == 我的规则, 进度["记录"])

        print("【L2 写工具】")
        定(包, "L2", 3)
        参考 = yaml.safe_load((包 / "资料/质检智能体/规则库_参考.yaml").read_text(encoding="utf-8"))
        参考参数 = {r["id"]: r.get("参数") for r in 参考["规则"]}
        我的库 = yaml.safe_load(已签)
        for r in 我的库["规则"]:
            r["参数"] = 参考参数[r["id"]]
        带参数 = yaml.safe_dump(我的库, allow_unicode=True, sort_keys=False)
        好函数 = (样例 / "我的检查.py").read_text(encoding="utf-8")
        写(包 / "qc_agent/规则库.yaml", 带参数)
        检(包, "L2", False, "函数还没写不过", "不在 qc_agent/我的检查.py 里")
        写(包 / "qc_agent/我的检查.py", 好函数.replace('上限 = 取参数(rule, "高度上限_m")', "上限 = 100"))
        检(包, "L2", False, "阈值写死在代码里：改阈值测试拦住", "Q08 改阈值测试")
        写(包 / "qc_agent/我的检查.py", 好函数.replace('前缀 = 取参数(rule, "住宅代码前缀")', '前缀 = ["Rr"]'))
        检(包, "L2", False, "代码前缀写死在代码里：改阈值测试拦住", "代码表是不是写死")
        写(包 / "qc_agent/我的检查.py", 好函数.replace('面积 = p["_面积"]', '面积 = float(p["用地面积_m2"])'))
        检(包, "L2", False, "用属性面积判广场：小样本拦住", "Q15 小样本")
        写(包 / "qc_agent/我的检查.py", 好函数.replace("if c not in 表:", "if c.upper() not in {x.upper() for x in 表}:"))
        检(包, "L2", False, "大小写被 upper() 洗掉：小样本拦住", "Q03 小样本")
        写(包 / "qc_agent/我的检查.py", 好函数.replace('yield 无法检查(rule, 地块对象(p), "没填建筑高度")', "pass"))
        检(包, "L2", False, "缺值当通过：小样本拦住", "Q08 小样本")
        写(包 / "qc_agent/我的检查.py", 好函数)
        写(包 / "qc_agent/规则库.yaml", 带参数.replace("高度上限_m:", "高度上限备用:"))
        检(包, "L2", False, "规则库缺参数键：函数报错被拦住", "Q08")
        写(包 / "qc_agent/规则库.yaml", 带参数)
        检(包, "L2", True, "L2 通过（学员 " + str(len(我的规则)) + " 条：小样本 + 改阈值）")
        码, 文 = 跑(包, "带教/progress.py", "merge")
        记("合并参考规则和检查函数", 码 == 0 and (str(21 - len(我的规则)) + " 条规则") in 文, 文)
        检(包, "L2", True, "合并后 21 条规则全部对上小样本")

        print("【L3 编排成智能体】")
        定(包, "L3", 3)
        检(包, "L3", False, "还没写 skill 不过", "SKILL.md")
        shutil.copy2(str(包 / "存档点/L3/SKILL.md"), str(写入路径(包 / ".claude/skills/qc/SKILL.md")))
        time.sleep(1.2)
        模拟qc(包, "data/qc", "qc_agent/报告", 教学数字, 漏写="首条错误")
        检(包, "L3", False, "报告漏写一条错误不过", "没写进报告")
        模拟qc(包, "data/qc", "qc_agent/报告", 教学数字, 多写="F999")
        检(包, "L3", False, "报告里出现工具没给的编号不过", "F999")
        改写 = json.loads(json.dumps(教学数字))
        for x in 改写["数字"]:
            x["原文"] = "说明书提到" + x["项目"] + "大约是" + str(x["值"])
        模拟qc(包, "data/qc", "qc_agent/报告", 改写)
        检(包, "L3", False, "claims.json 原文是改写的不过", "原文」大多在说明书里找不到")
        模拟qc(包, "data/qc", "qc_agent/报告", 教学数字)
        检(包, "L3", True, "L3 通过")

        print("【L4 评测】")
        定(包, "L4", 2)
        模拟qc(包, "data/qc", "qc_agent/评测/运行1", 教学数字)
        time.sleep(1.2)
        码, 文 = 跑(包, "带教/progress.py", "redline", "--recall", "0.9", "--fp", "2")
        记("定合格线", 码 == 0, 文)
        码, 文 = 跑(包, "带教/progress.py", "redline", "--recall", "0.8", "--fp", "5")
        记("改合格线不写理由被拒", 码 != 0 and "--reason" in 文, 文)
        time.sleep(1.2)
        模拟qc(包, "data/qc", "qc_agent/评测/运行2", 教学数字)
        模拟qc(包, "带教/变体单元", "qc_agent/评测/变体", 变体数字)
        写(包 / "qc_agent/评测/评测记录.md", "# 评测记录\n\n## 合格线\n检出率 ≥ 90%，误报 ≤ 2：漏报代价大。\n\n## 稳定性\n两次结果一致。\n\n"
                                         "## 变体单元\n变体单元检出 24/24。\n\n## 口径差异\nQ08 学员定为 > 100 米，与参考一致。\n")
        检(包, "L4", False, "先看结果后定合格线不过", "比合格线跑得早")
        模拟qc(包, "data/qc", "qc_agent/评测/运行1", 教学数字)
        检(包, "L4", True, "L4 通过")
        进度 = json.loads((包 / "学习进度.json").read_text(encoding="utf-8"))
        汇总 = 进度["记录"].get("评测结果", {})
        记("评测：教学单元 26/26、变体单元 24/24、误报 0",
           汇总.get("教学单元", {}).get("检出") == 26 and 汇总.get("变体单元", {}).get("检出") == 24
           and 汇总["教学单元"]["误报"] == 0 and 汇总["变体单元"]["误报"] == 0, 汇总)

        print("【L5 护栏与红队】")
        定(包, "L5", 1)
        模拟qc(包, "带教/红队/R1", "qc_agent/红队/R1", 教学数字, 不写声明节=True)
        模拟qc(包, "带教/红队/R3", "qc_agent/红队/R3", 教学数字)
        写(包 / "qc_agent/红队记录.md", "# 红队记录\n\n" + "\n".join(
            "## " + 名 + "\n- 输入：……\n- 智能体原话：……\n- 守住没有：守住\n- 改了什么：……\n" for 名 in ("R1", "R2", "R3")))
        文 = 检(包, "L5", False, "R1 报告没有「需人工核实的声明」不过", "需人工核实的声明")
        if not args.压缩:
            记("没登记只读清单也会被指出", "只读清单" in 文, 文)
        模拟qc(包, "带教/红队/R1", "qc_agent/红队/R1", 教学数字)
        写(包 / "qc_agent/只读清单.txt", "# 冻结的文件\nqc_agent/规则库.yaml\n")
        记("只读清单登记后，钩子拦下写规则库", 钩子(包, 包 / "qc_agent/规则库.yaml") == 2)
        检(包, "L5", True, "L5 通过")

        print("【L6 复盘与迁移】")
        定(包, "L6", 1)
        写(包 / "qc_agent/迁移卡.md", "# 迁移卡\n\n## 带教智能体拆解\n| 五件套 | 文件 |\n|---|---|\n| 岗位说明书 | SKILL.md 你是谁、铁律 |\n"
                                 "| 规则 | 关卡.yaml |\n| 工具 | check_L*.py、progress.py |\n| 编排 | SKILL.md 五步 |\n| 评测与护栏 | guard.py、manifest |\n\n"
                                 "## 我的智能体：设计方案指标核查\n- 岗位说明书：……\n- 规则：……\n- 工具：……\n- 编排：……\n- 评测：……\n\n## 第一步\n先找技术规定，写三条规则。\n")
        检(包, "L6", True, "L6 通过")
        码, 文 = 跑(包, "带教/progress.py", "show")
        记("七关全部通过", "七关已全部通过" in 文, 文)
        码, 文 = 跑(包, "带教/progress.py", "card")
        记("进度码", "全部通过" in 文 and "自测学员" in 文, 文)

        print("【讲师文件防改与存档点】")
        教案 = 包 / "带教" / "关卡.yaml"
        原教案 = 教案.read_bytes()
        教案.write_bytes(原教案 + b"\n# \xe6\x94\xb9\xe4\xb8\x80\xe4\xb8\x8b\n")
        检(包, "L6", False, "讲师文件被改：验收失败", "讲师文件被改过：带教/关卡.yaml")
        教案.write_bytes(原教案)
        检(包, "L6", True, "恢复后验收恢复")
        码, 文 = 跑(包, "带教/progress.py", "stage", "L2")
        记("stage 能打印教案", 码 == 0 and "追问要点" in 文 and "改阈值测试" in 文, 文)
        码, 文 = 跑(包, "带教/progress.py", "checkpoint", "L3")
        记("存档点 L3：先备份再复制", 码 == 0 and any((包 / "qc_agent/_备份").rglob("SKILL.md")), 文)
        码, 文 = 跑(包, "带教/progress.py", "checkpoint", "L5")
        记("L5 没有存档点", 码 != 0, 文)
    finally:
        if args.保留:
            print("\n学员包留在：" + str(包))
        else:
            shutil.rmtree(str(临时), ignore_errors=True)

    坏 = [名 for 名, ok in 记录 if not ok]
    print("\n自测：" + str(len(记录) - len(坏)) + "/" + str(len(记录)) + " 项通过")
    for 名 in 坏:
        print("  ✗ " + 名)
    return 1 if 坏 else 0


def 写入路径(路径):
    Path(路径).parent.mkdir(parents=True, exist_ok=True)
    return 路径


if __name__ == "__main__":
    sys.exit(main())
