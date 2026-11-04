# -*- coding: utf-8 -*-
"""
带教脚本的公用部分：路径、输出编码、学习进度、讲师文件清单、跑 qc_tools、对照小样本、验收输出。
只用标准库；读 YAML 的地方才需要 PyYAML。这是讲师文件，只读。
"""
import sys

sys.dont_write_bytecode = True

import datetime
import hashlib
import json
import os
import subprocess
from pathlib import Path

根目录 = Path(__file__).resolve().parent.parent
带教目录 = 根目录 / "带教"
进度文件 = 根目录 / "学习进度.json"
关卡文件 = 带教目录 / "关卡.yaml"
清单文件 = 带教目录 / "manifest.sha256"
作品目录 = 根目录 / "qc_agent"
存档点目录 = 根目录 / "存档点"
关卡顺序 = ["L0", "L1", "L2", "L3", "L4", "L5", "L6"]
关卡名 = {"L0": "岗位说明书", "L1": "从条文抽规则", "L2": "写工具", "L3": "编排成智能体",
        "L4": "评测", "L5": "护栏与红队", "L6": "复盘与迁移"}
严重度们 = ["错误", "待确认", "提示", "无法检查"]


def 设置输出():
    for 流 in (sys.stdout, sys.stderr):
        try:
            流.reconfigure(encoding="utf-8")
        except Exception:
            pass


def 现在():
    return datetime.datetime.now().isoformat(timespec="seconds")


def 相对(路径):
    try:
        return Path(路径).resolve().relative_to(根目录).as_posix()
    except ValueError:
        return str(路径).replace("\\", "/")


def 读文本(路径):
    return Path(路径).read_text(encoding="utf-8-sig")


def 读json(路径):
    with open(路径, encoding="utf-8-sig") as f:
        return json.load(f)


# ------------------------------------------------------------ YAML

def 需要yaml():
    try:
        import yaml
        return yaml
    except ImportError:
        print("缺 PyYAML。先运行：python3 -m pip install pyyaml shapely pyproj", file=sys.stderr)
        sys.exit(2)


def 读yaml(路径):
    yaml = 需要yaml()
    with open(路径, encoding="utf-8-sig") as f:
        return yaml.safe_load(f)


def 教案():
    return 读yaml(关卡文件)


def 关卡定义(关):
    for 段 in 教案().get("关卡") or []:
        if 段.get("id") == 关:
            return 段
    return {}


def 课时版本():
    return str(教案().get("课时版本") or "完整")


# ------------------------------------------------------------ 学习进度

def 读进度():
    if not 进度文件.is_file():
        return None
    return 读json(进度文件)


def 写进度(进度):
    临时 = 进度文件.with_name(进度文件.name + ".tmp")
    with open(临时, "w", encoding="utf-8") as f:
        json.dump(进度, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(临时, 进度文件)


def 新进度(姓名, 路线):
    时间 = 现在()
    return {
        "格式": 1,
        "学员": 姓名,
        "路线": 路线,
        "建档时间": 时间,
        "当前关": "L0",
        "关卡": {关: {"状态": "进行中" if 关 == "L0" else "未开始",
                    "开始": 时间 if 关 == "L0" else None,
                    "通过": None, "验收次数": 0, "最近验收": None,
                    "提示": [], "存档点": False} for 关 in 关卡顺序},
        "决策": [],
        "合格线": None,
        "记录": {},
        "日志": [{"时间": 时间, "事件": "建档", "路线": 路线}],
    }


def 记日志(进度, 事件, **内容):
    条 = {"时间": 现在(), "事件": 事件}
    条.update(内容)
    进度.setdefault("日志", []).append(条)


def 本关决策(进度, 关):
    return [d for d in (进度 or {}).get("决策", []) if d.get("关") == 关]


def 已通过(进度, 关):
    return bool(进度) and 进度["关卡"].get(关, {}).get("状态") == "已通过"


def 下一关(关):
    i = 关卡顺序.index(关)
    return 关卡顺序[i + 1] if i + 1 < len(关卡顺序) else None


# ------------------------------------------------------------ 讲师文件清单

def 文件哈希(路径):
    h = hashlib.sha256()
    with open(路径, "rb") as f:
        for 块 in iter(lambda: f.read(1 << 16), b""):
            h.update(块)
    return h.hexdigest()


def 校验清单():
    """返回问题列表；空列表 = 讲师文件都没动过。"""
    if not 清单文件.is_file():
        return ["缺少 带教/manifest.sha256（学员包不完整，找讲师要一份）"]
    问题们 = []
    for 行 in 读文本(清单文件).splitlines():
        行 = 行.strip()
        if not 行 or 行.startswith("#"):
            continue
        哈希, _, 路径 = 行.partition("  ")
        文件 = 根目录 / 路径
        if not 文件.is_file():
            问题们.append("讲师文件不见了：" + 路径)
        elif 文件哈希(文件) != 哈希:
            问题们.append("讲师文件被改过：" + 路径)
    return 问题们


# ------------------------------------------------------------ 跑 qc_tools

def 运行qc(数据目录, 输出json, 规则="all", 规则库=None, 声明=None, 只用我的=False, 超时=180):
    """在项目根目录跑 qc_agent/qc_tools.py。返回 (退出码, 输出文字, 结果 dict 或 None)。"""
    命令 = [sys.executable, "-X", "utf8", str(作品目录 / "qc_tools.py"),
          "--data", str(数据目录), "--out", str(输出json), "--rules", 规则]
    if 规则库:
        命令 += ["--rulebook", str(规则库)]
    if 声明:
        命令 += ["--claims", str(声明)]
    if 只用我的:
        命令.append("--只用我的")
    环境 = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    try:
        结果 = subprocess.run(命令, cwd=str(根目录), capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=超时, env=环境)
    except subprocess.TimeoutExpired:
        return 124, "qc_tools.py 跑了 " + str(超时) + " 秒还没完", None
    文字 = (结果.stdout or "") + (结果.stderr or "")
    数据 = None
    if Path(输出json).is_file():
        try:
            数据 = 读json(输出json)
        except Exception as e:
            文字 += "\nfindings.json 读不了：" + str(e)
    return 结果.returncode, 文字, 数据


# ------------------------------------------------------------ 小样本

def 落盘(数据集, 目录):
    """把小样本里的一份迷你成果写到目录里。"""
    目录 = Path(目录)
    目录.mkdir(parents=True, exist_ok=True)
    for 名字, 内容 in 数据集["文件"].items():
        路径 = 目录 / 名字
        if isinstance(内容, str):
            路径.write_text(内容, encoding="utf-8")
        else:
            with open(路径, "w", encoding="utf-8") as f:
                json.dump(内容, f, ensure_ascii=False)
    return 目录


def 实际结果(findings, 规则):
    """{对象: set(严重度)}，只看这条规则。"""
    结果 = {}
    for 条 in findings or []:
        if 条.get("规则") == 规则:
            结果.setdefault(str(条.get("对象")), set()).add(条.get("严重度"))
    return 结果


def 对照期望(findings, 规则, 期望):
    """期望：{对象: [可接受的结果]}，结果 ∈ 错误/提示/待确认/无法检查/不报；"*" 管其余所有对象。
    返回没对上的说明列表。"""
    实际 = 实际结果(findings, 规则)
    问题们 = []
    for 对象, 可接受 in 期望.items():
        if 对象 == "*":
            continue
        有 = 实际.get(对象, set())
        if not 有:
            if "不报" not in 可接受:
                问题们.append(对象 + "：应该报「" + "/".join(可接受) + "」，你的函数没报")
        elif not 有 <= set(可接受):
            多 = "、".join(sorted(有 - set(可接受)))
            if 可接受 == ["不报"]:
                问题们.append(对象 + "：不该报，你的函数报了「" + 多 + "」")
            else:
                问题们.append(对象 + "：应该报「" + "/".join(可接受) + "」，你的函数报的是「" + "、".join(sorted(有)) + "」")
    if "*" in 期望:
        for 对象 in sorted(实际):
            if 对象 not in 期望 and not 实际[对象] <= set(x for x in 期望["*"] if x != "不报"):
                问题们.append(对象 + "：不该出现，你的函数报了「" + "、".join(sorted(实际[对象])) + "」")
    return 问题们


# ------------------------------------------------------------ Markdown

def 标题们(文字):
    """[(行号, 级别, 标题)]；代码块里的 # 不算标题。"""
    import re
    结果, 代码块 = [], False
    for 行号, 行 in enumerate(文字.splitlines()):
        if 行.strip().startswith("```"):
            代码块 = not 代码块
            continue
        if 代码块:
            continue
        m = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", 行)
        if m:
            结果.append((行号, len(m.group(1)), m.group(2).strip()))
    return 结果


def 节文字(文字, *关键词):
    """第一个标题含任一关键词的那一节（连同它下面的小节）；没有返回 None。"""
    行们 = 文字.splitlines()
    标 = 标题们(文字)
    for i, (行号, 级, 题) in enumerate(标):
        if any(k in 题 for k in 关键词):
            结束 = next((n for n, l, _ in 标[i + 1:] if l <= 级), len(行们))
            return "\n".join(行们[行号 + 1:结束]).strip()
    return None


def 列表项数(文字):
    import re
    return sum(1 for 行 in (文字 or "").splitlines() if re.match(r"^\s*(?:[-*+]|\d+[.、)）])\s+\S", 行))


# ------------------------------------------------------------ 验收输出

class 验收:
    """用法：v = 验收("L1"); 进度 = v.前置(); ... v.好()/v.坏(); v.结束()"""

    def __init__(self, 关):
        设置输出()
        self.关 = 关
        self.失败项 = []
        self.记录项 = {}
        self.进度 = None
        print("== " + 关 + " " + 关卡名[关] + " · 验收 ==")

    def 好(self, 文字):
        print("✓ " + 文字)

    def 坏(self, 文字):
        print("✗ " + 文字)
        self.失败项.append(文字)

    def 说(self, 文字):
        print("  " + 文字)

    def 记录(self, 键, 值):
        self.记录项[键] = 值

    def 前置(self, 最少决策=None):
        问题们 = 校验清单()
        if 问题们:
            for 问题 in 问题们[:10]:
                self.坏(问题)
            self.说("讲师文件不能改。从学员包里把原文件拷回来，或者找讲师。")
            self.结束()
        self.好("讲师文件没有被改动")
        self.进度 = 读进度()
        if self.进度 is None:
            self.坏("还没建档：先让带教智能体运行 python3 带教/progress.py init --name <姓名> --route <业务|技术>")
            self.结束()
        i = 关卡顺序.index(self.关)
        if i > 0:
            上一关 = 关卡顺序[i - 1]
            if not 已通过(self.进度, 上一关):
                self.坏("上一关 " + 上一关 + " " + 关卡名[上一关] + " 还没通过，先过那一关")
                self.结束()
        if 最少决策 is None:
            最少决策 = int(关卡定义(self.关).get("最少决策数") or 0)
        已记 = len(本关决策(self.进度, self.关))
        if 已记 < 最少决策:
            self.坏("本关决策记录只有 " + str(已记) + " 条，至少要 " + str(最少决策)
                   + " 条：决策题要学员亲口回答，再用 progress.py decide 记下")
        else:
            self.好("本关决策记录 " + str(已记) + " 条")
        return self.进度

    def 结束(self):
        通过 = not self.失败项
        进度 = self.进度 if self.进度 is not None else 读进度()
        if 进度 is not None:
            段 = 进度["关卡"][self.关]
            段["验收次数"] = int(段.get("验收次数") or 0) + 1
            段["最近验收"] = {"时间": 现在(), "结果": "通过" if 通过 else "未通过", "没过": self.失败项[:20]}
            if 通过:
                进度.setdefault("记录", {}).update(self.记录项)
                if 段.get("状态") != "已通过":
                    段["状态"] = "已通过"
                    段["通过"] = 现在()
                    后 = 下一关(self.关)
                    if 后:
                        进度["当前关"] = 后
                        if 进度["关卡"][后].get("状态") == "未开始":
                            进度["关卡"][后]["状态"] = "进行中"
                            进度["关卡"][后]["开始"] = 现在()
                    else:
                        进度["当前关"] = "完成"
                记日志(进度, "验收", 关=self.关, 结果="通过")
            else:
                记日志(进度, "验收", 关=self.关, 结果="未通过", 没过=len(self.失败项))
            写进度(进度)
        print()
        if 通过:
            后 = 下一关(self.关)
            print("结果：通过 ✓ —— 已记入学习进度。" + ("下一关：" + 后 + " " + 关卡名[后] if 后 else "七关全部完成。"))
            sys.exit(0)
        print("结果：未通过（" + str(len(self.失败项)) + " 项没过）")
        sys.exit(1)
