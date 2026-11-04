#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""环境检查：Python 版本、PyYAML、shapely、pyproj、数据文件。缺什么就告诉你装什么。"""
import sys

sys.dont_write_bytecode = True

import common as c

安装命令 = "python3 -m pip install pyyaml shapely pyproj"


def 检查环境():
    问题们 = []
    if sys.version_info < (3, 9):
        问题们.append("Python 版本是 " + sys.version.split()[0] + "，至少要 3.9")
    try:
        import yaml  # noqa: F401
    except ImportError:
        问题们.append("缺 PyYAML（读规则库要用）：" + 安装命令)
    try:
        import shapely
        if int(shapely.__version__.split(".")[0]) < 2:
            问题们.append("shapely 版本是 " + shapely.__version__ + "，要 2.0 以上：python3 -m pip install -U shapely")
    except ImportError:
        问题们.append("缺 shapely（量面积、判重叠要用）：" + 安装命令)
    try:
        import pyproj  # noqa: F401
    except ImportError:
        问题们.append("缺 pyproj（坐标转换要用）：" + 安装命令)
    for 名 in ("data/qc/教学单元_地块.geojson", "data/qc/教学单元_街坊.geojson", "qc_agent/qc_tools.py",
              "资料/质检智能体/上海控规质检_条文摘录.md"):
        if not (c.根目录 / 名).is_file():
            问题们.append("找不到 " + 名 + "（是不是没在学员包的根目录打开 Claude Code？）")
    return 问题们


def main():
    c.设置输出()
    问题们 = 检查环境()
    print("Python " + sys.version.split()[0] + "（" + sys.executable + "）")
    if not 问题们:
        print("✓ 环境齐了：PyYAML、shapely、pyproj、数据文件都在。")
        return 0
    for 问题 in 问题们:
        print("✗ " + 问题)
    print("装好以后再跑一次：python3 带教/check_env.py（Windows 上把 python3 换成 python）")
    return 1


if __name__ == "__main__":
    sys.exit(main())
