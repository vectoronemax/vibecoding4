#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PreToolUse 钩子：讲师文件只读。拦的是 Edit / Write / MultiEdit / NotebookEdit 对下面这些路径的写入：
  带教/  data/  资料/  存档点/  .claude/skills/coach/  .claude/settings.json  学习进度.json
再加上学员自己在 qc_agent/只读清单.txt 里登记的路径（一行一个，# 开头是注释）。
退出码 2 = 拦下这次写入，stderr 里的话会回给模型；其他情况退出码 0（放行）。
注意：钩子拦不住 Bash 里的 sed / 重定向——所以每个验收脚本开头还会核对讲师文件的哈希。
"""
import json
import os
import sys

讲师文件 = ["带教/", "data/", "资料/", "存档点/", ".claude/skills/coach/", ".claude/settings.json", "学习进度.json"]


def _命中(相对, 规则):
    规则 = 规则.strip().replace("\\", "/")
    while 规则.startswith("./"):
        规则 = 规则[2:]
    if not 规则:
        return False
    if 规则.endswith("/"):
        return 相对 == 规则.rstrip("/") or 相对.startswith(规则)
    return 相对 == 规则


def main():
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        输入 = json.load(sys.stdin)
    except Exception:
        return 0
    工具输入 = 输入.get("tool_input") or {}
    路径 = 工具输入.get("file_path") or 工具输入.get("notebook_path") or ""
    if not 路径:
        return 0
    根 = os.path.abspath(os.environ.get("CLAUDE_PROJECT_DIR") or 输入.get("cwd") or os.getcwd())
    绝对 = os.path.abspath(os.path.join(根, 路径))
    相对 = os.path.relpath(绝对, 根).replace("\\", "/")
    if 相对.startswith("../") or 相对 == "..":
        return 0
    for 规则 in 讲师文件:
        if _命中(相对, 规则):
            print(相对 + " 是讲师文件，只读：期望值和教案只由讲师改。学员的作品写到 qc_agent/。"
                  "不要用 Bash 绕过去——验收脚本会核对讲师文件的哈希。", file=sys.stderr)
            return 2
    清单 = os.path.join(根, "qc_agent", "只读清单.txt")
    if os.path.isfile(清单):
        try:
            with open(清单, encoding="utf-8-sig") as f:
                登记 = [行.split("#", 1)[0].strip() for 行 in f]
        except Exception:
            登记 = []
        for 规则 in 登记:
            if 规则 and _命中(相对, 规则):
                print(相对 + " 已登记在 qc_agent/只读清单.txt 里（冻结）。要改：先请审定人签字同意，"
                      "由学员自己把这一行从只读清单里删掉，并在决策记录里写明理由。", file=sys.stderr)
                return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
