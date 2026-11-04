#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""L6 复盘与迁移 · 验收：qc_agent/迁移卡.md 有「带教智能体拆解」（五件套各在哪），以及迁移到自己工作的五件套 + 第一步。"""
import sys

sys.dont_write_bytecode = True

import common as c

五件套 = ["岗位说明书", "规则", "工具", "编排", "评测"]
v = c.验收("L6")
v.前置()
文件 = c.作品目录 / "迁移卡.md"
if not 文件.is_file():
    v.坏("没有 qc_agent/迁移卡.md")
    v.结束()
文字 = c.读文本(文件)
拆解 = c.节文字(文字, "带教智能体")
if 拆解 is None:
    v.坏("缺「带教智能体拆解」一节：五件套分别在哪个文件")
else:
    缺 = [k for k in 五件套 if k not in 拆解]
    if 缺:
        v.坏("「带教智能体拆解」里没写到：" + "、".join(缺))
    elif not any(x in 拆解 for x in ("SKILL.md", "关卡.yaml", "check_", "progress.py", "guard.py")):
        v.坏("「带教智能体拆解」要写到具体文件（SKILL.md、关卡.yaml、check_L*.py……）")
    else:
        v.好("带教智能体五件套都找到了对应的文件")
其余 = 文字.replace(拆解 or "", "")
缺 = [k for k in 五件套 if k not in 其余]
if 缺:
    v.坏("迁移到你自己工作的部分，还缺：" + "、".join(缺))
elif "第一步" not in 其余:
    v.坏("迁移卡要写「第一步」：先找哪份标准、先写哪几条规则")
else:
    v.好("迁移卡五件套齐全，写了第一步")
v.结束()
