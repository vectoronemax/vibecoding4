"""从 Yuxi（xerrors/Yuxi）知识库拉一张知识图谱子图，存成 apps/kg-cockpit/yuxi/<知识库ID>.json。

用法（项目根目录）：
  export YUXI_BASE_URL=http://localhost:5050       # Yuxi API 地址，默认就是这个
  export YUXI_API_KEY=yxkey_...                     # 「设置 → API Keys」创建，权限选 full，所属账号要是管理员
  python3 apps/kg-cockpit/fetch_yuxi.py --list      # 看有哪些可用的知识库图谱
  python3 apps/kg-cockpit/fetch_yuxi.py --kb-id <知识库ID> [--keyword 绿地] [--max-nodes 300]
  python3 apps/kg-cockpit/build_data.py             # 重新生成 data.js，刷新网页，右上角「图谱」里切换

调用的是 Yuxi 的 GET /api/graph/list 和 GET /api/graph/subgraph（管理员接口，只读）。
为什么不在网页里直接请求 Yuxi：浏览器会遇到跨域，而且 API Key 会暴露在页面源码里。
本平台的约定是「Python 脚本取数 → data.js → 网页只读」，这里照做。

只用标准库，不需要额外安装依赖。Key 只从环境变量读，不写进任何文件、不打印。
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent / "yuxi"
TIMEOUT = 60


def request(path, params=None):
    base = os.environ.get("YUXI_BASE_URL", "http://localhost:5050").rstrip("/")
    key = os.environ.get("YUXI_API_KEY", "").strip()
    if not key:
        sys.exit("✗ 没有设置 YUXI_API_KEY。在 Yuxi「设置 → API Keys」创建一个 full 权限的 Key（所属账号需是管理员），"
                 "然后 export YUXI_API_KEY=yxkey_...")
    url = f"{base}{path}" + (f"?{urllib.parse.urlencode(params)}" if params else "")
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        hint = {
            401: "Key 无效、已过期或已撤销。",
            403: "权限不够：图谱接口要求管理员；knowledge / agents 权限的 Key 访问不了 /api/graph，要用 full 权限的 Key。",
            404: "找不到：检查知识库 ID（用 --list 查），或这个 Yuxi 版本没有 /api/graph 接口。",
        }.get(e.code, "")
        sys.exit(f"✗ Yuxi 返回 HTTP {e.code}：{detail}\n  {hint}")
    except urllib.error.URLError as e:
        sys.exit(f"✗ 连不上 {base}：{e.reason}。确认 Yuxi 已启动（docker compose up），或用 YUXI_BASE_URL 指定地址。")
    if isinstance(body, dict) and body.get("success") is False:
        sys.exit(f"✗ Yuxi 返回失败：{json.dumps(body, ensure_ascii=False)[:300]}")
    return body


def list_graphs():
    body = request("/api/graph/list")
    rows = body.get("data", [])
    if not rows:
        print("没有可用的知识库图谱（图谱只支持 Milvus 知识库，且要先在知识库详情页提交图谱构建）。")
        return
    print(f"共 {len(rows)} 个知识库：")
    for r in rows:
        print(f"  {r.get('id')}  {r.get('name')}  {r.get('description') or ''}".rstrip())


def fetch(args):
    params = {
        "kb_id": args.kb_id,
        "node_label": args.keyword,
        "max_depth": args.max_depth,
        "max_nodes": args.max_nodes,
        "exclude_chunk": str(not args.with_chunk).lower(),
    }
    if args.file_id:
        params["file_id"] = args.file_id
    body = request("/api/graph/subgraph", params)
    data = body.get("data", body)
    nodes, edges = data.get("nodes") or [], data.get("edges") or []
    if not nodes:
        sys.exit(f"✗ 子图是空的（关键词「{args.keyword}」）。确认该知识库已完成图谱构建，或换个关键词。")

    kb_name = args.kb_id
    try:
        kb_name = next((r.get("name") for r in request("/api/graph/list").get("data", []) if r.get("id") == args.kb_id), args.kb_id)
    except SystemExit:
        pass  # 取不到名字不影响子图本身

    OUT_DIR.mkdir(exist_ok=True)
    out = OUT_DIR / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', args.kb_id)}.json"
    payload = {
        "kb_id": args.kb_id,
        "kb_name": kb_name,
        "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "params": {k: v for k, v in params.items() if k != "kb_id"},
        "data": {"nodes": nodes, "edges": edges},
    }
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    ids = {n.get("id") for n in nodes}
    dangling = sum(1 for e in edges if e.get("source_id") not in ids or e.get("target_id") not in ids)
    types = Counter(n.get("type") or "Entity" for n in nodes)
    print(f"✓ 写出 {out.relative_to(Path.cwd()) if out.is_relative_to(Path.cwd()) else out}")
    print(f"  知识库：{kb_name}（{args.kb_id}）")
    print(f"  节点 {len(nodes)}，关系 {len(edges)}" + (f"，其中端点不在子图内 {dangling} 条（build_data.py 会丢弃并报告）" if dangling else ""))
    print("  实体类型：" + "；".join(f"{t} {c}" for t, c in types.most_common(10)))
    if len(nodes) >= args.max_nodes:
        print(f"  ⚠ 节点数到了上限 {args.max_nodes}，子图被截断。要看全貌就调大 --max-nodes（Yuxi 上限 1000），或用 --keyword 聚焦。")
    print("下一步：python3 apps/kg-cockpit/build_data.py")


def main():
    ap = argparse.ArgumentParser(description="从 Yuxi 知识库拉知识图谱子图，供 kg-cockpit 大屏使用")
    ap.add_argument("--list", action="store_true", help="列出可用的知识库图谱")
    ap.add_argument("--kb-id", help="知识库 ID（--list 可查）")
    ap.add_argument("--keyword", default="*", help="实体关键词，* 表示不限（默认）")
    ap.add_argument("--max-nodes", type=int, default=300, help="最多节点数，1–1000，默认 300")
    ap.add_argument("--max-depth", type=int, default=2, help="从命中实体向外扩展的跳数，1–5，默认 2（Yuxi 内部封顶 3）")
    ap.add_argument("--with-chunk", action="store_true", help="同时拉文档块（Chunk）节点，默认不拉")
    ap.add_argument("--file-id", help="只看知识库里某个文件抽出来的实体")
    args = ap.parse_args()
    if args.list:
        list_graphs()
    elif args.kb_id:
        if not 1 <= args.max_nodes <= 1000 or not 1 <= args.max_depth <= 5:
            sys.exit("✗ --max-nodes 要在 1–1000，--max-depth 要在 1–5（Yuxi 接口的限制）")
        fetch(args)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
