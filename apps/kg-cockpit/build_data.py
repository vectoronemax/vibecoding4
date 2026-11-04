"""把质检规则库（和可选的 Yuxi 图谱）整理成知识图谱大屏的数据层 apps/kg-cockpit/data.js。

用法（项目根目录）：python3 apps/kg-cockpit/build_data.py

输入（只读）：
  资料/质检智能体/规则库_参考.yaml          规则、依据文件、用词与严重度、明确不查的条文
  资料/质检智能体/上海控规质检_条文摘录.md   条文原文，用来核对规则里抄的「原文」
  apps/kg-cockpit/yuxi/*.json               可选：fetch_yuxi.py 从 Yuxi 拉下来的子图，每个文件一张图谱

输出 window.KG_DATA = {meta, graphs:[{id, name, types, rels, nodes, edges, tree, checks, ...}]}
节点、关系用数组下标引用（edges = [起点, 终点, 关系下标, 属性]）；节点坐标在这里算好，
网页只读 data.js，换数据只重跑本脚本。

图谱的每个实体、每条关系都能在 YAML 的某个字段里找到出处，不靠大模型抽取；
解析不了的依据、认不出的用地代码会列出来并中止，不静默丢弃。
"""
import json
import re
import sys
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
RULES_YAML = ROOT / "资料" / "质检智能体" / "规则库_参考.yaml"
EXCERPT_MD = ROOT / "资料" / "质检智能体" / "上海控规质检_条文摘录.md"
YUXI_DIR = HERE / "yuxi"
OUT_JS = HERE / "data.js"

COURSE_BASIS = "课程口径"
COURSE_BASIS_NOTE = "控规成果的数据库标准、汇交质检细则目前没有公开文本，数据完整性、编码、拓扑几条是课程自定的口径（条文摘录 · 开头说明）"
DEFAULT_DOC = "准则2016"  # 摘录里不带文件名的「表x-y」都出自准则2016（表3-2、表4-1、表5-3）

# 用地代码 → 名称。名称只取自条文摘录「表3-2 用到的代码」和规则库原文，摘录没写的留空，不臆造。
# 规则里出现的代码统一归到「中类」（Rs4 → Rs、C53 → C5、S51 → S5），原始写法记在关系属性里。
LANDUSE = {
    # 大类
    "R": "居住", "C": "公共设施", "M": "工业", "W": "仓储", "S": "道路广场", "U": "市政",
    "G": "绿地", "Z": "综合用地", "X": "城市发展备建用地", "K": "控制用地",
    "D": "特殊用地",   # 准则2016 3.4.4「特殊用地」↔ 规则 Q06 口径 D*
    "T": None,         # 规则 Q04 口径出现，摘录未列名称
    # 中类
    "Rr": "住宅组团", "Rc": "社区级公共服务设施", "Rs": "基础教育",
    "C2": "商业服务业", "C3": "文化", "C5": "医疗卫生", "C8": "商务办公",
    "M1": None, "M2": "二类工业", "M3": "三类工业", "M4": "工业研发",   # M2/M3：准则2016 3.4.4 ↔ Q06；M4：Q10 适用
    "W2": "危险品仓储",  # 准则2016 3.4.4「危险品仓储用地」↔ Q06 口径 W2
    "S3": "社会停车场", "S4": "公交场站", "S5": "广场", "S6": None, "S9": None,
    "G1": "公共绿地",
}
LANDUSE_SRC = "名称取自 资料/质检智能体/上海控规质检_条文摘录.md「表3-2 用到的代码」与准则2016 3.4.4 原文"
# 只是举例、不是适用对象的代码提及
EXAMPLE_ONLY = {("Q03", "Rr")}  # Q03 口径「大小写敏感（Rr3 ≠ RR3）」

DOC_RE = r"准则2016|成果规范2020|技术规定|绿化审核|制定办法"
CN_NUM = "一二三四五六七八九十百零"
CLAUSE_RE = re.compile(
    rf"表[\d{CN_NUM}]+(?:-\d+)?|附录[{CN_NUM}]+|第[{CN_NUM}]+条(?:至第[{CN_NUM}]+条)?|\d+(?:\.\d+)+"
)
_CODE = r"[A-Z](?:[a-z]\d*|\d+)?\*?"
# 一次提及 = 一个代码或一个区间（Rr1–Rr4），整段原样记进关系属性
CODE_RE = re.compile(rf"(?<![A-Za-z0-9_*])({_CODE}(?:[–-]{_CODE})?)(?![A-Za-z0-9_*])")
SEV_TOKENS = ["待确认", "错误", "提示", "不检查"]


def fail(msg, items=None):
    print(f"✗ {msg}，已中止，未写出 data.js")
    for it in items or []:
        print(f"  - {it}")
    sys.exit(1)


def strip_parens(s):
    """去掉（…）和「…」里的内容，返回 (主体, [括号里的内容])。"""
    notes = re.findall(r"（([^（）]*)）", s)
    body = re.sub(r"（[^（）]*）", "", s)
    body = re.sub(r"「[^「」]*」", "", body)
    return body.strip(), notes


def split_top(s, sep="；"):
    """只按括号外的分隔符切分。"""
    parts, depth, cur = [], 0, ""
    for ch in s:
        depth += ch in "（(「"
        depth -= ch in "）)」"
        if ch == sep and depth == 0:
            parts.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts


def norm_text(s):
    """只留汉字、字母、数字，用来比对原文（摘录在数字两边加了空格、标点也有出入）。"""
    return re.sub(r"[^\w]", "", s.replace("……", "")).replace("_", "")


# ---------------------------------------------------------------- 条文摘录

def read_excerpt():
    """从摘录里抽出「**条文**：原文」，返回 {文件 条文号: 原文}。表格类条文取紧随其后的 Markdown 表。"""
    lines = EXCERPT_MD.read_text(encoding="utf-8").splitlines()
    out = {}
    for i, line in enumerate(lines):
        m = re.match(r"^- \*\*(.+?)\*\*(.*)$", line)
        if not m:
            continue
        head, rest = m.group(1), m.group(2)
        text = rest.split("：", 1)[1].strip() if "：" in rest else ""
        if not text:  # 表4-1 这类：原文是下面的表；表3-2 这类：原文是下面缩进的子列表
            tbl = []
            for nxt in lines[i + 1:]:
                if nxt.startswith("|") or nxt.startswith("  - "):
                    tbl.append(nxt.strip())
                elif tbl or nxt.strip():
                    break
            text = "\n".join(tbl)
        body, _ = strip_parens(head)
        doc_m = re.match(rf"^({DOC_RE})\s*", body)
        doc = doc_m.group(1) if doc_m else DEFAULT_DOC
        for clause in CLAUSE_RE.findall(body):
            out[f"{doc} {clause}"] = text
    return out


# ---------------------------------------------------------------- 图

class Graph:
    def __init__(self, gid, name):
        self.id, self.name = gid, name
        self.types, self.rels = [], []
        self.nodes, self.edges = [], []
        self.index = {}
        self.edge_keys = set()

    def _ti(self, lst, v):
        if v not in lst:
            lst.append(v)
        return lst.index(v)

    def node(self, key, ntype, name, short=None, props=None):
        if key in self.index:
            return self.index[key]
        self.index[key] = len(self.nodes)
        n = {"t": self._ti(self.types, ntype), "n": name}
        if short:
            n["s"] = short
        if props:
            n["p"] = {k: v for k, v in props.items() if v not in (None, "", [], {})}
        self.nodes.append(n)
        return self.index[key]

    def edge(self, a, b, rel, props=None):
        key = (a, b, rel)
        if key in self.edge_keys:
            return
        self.edge_keys.add(key)
        e = [a, b, self._ti(self.rels, rel)]
        if props:
            e.append(props)
        self.edges.append(e)

    def export(self, **extra):
        pos = layout(len(self.nodes), [(e[0], e[1]) for e in self.edges])
        for n, (x, y) in zip(self.nodes, pos):
            n["x"], n["y"] = round(float(x), 1), round(float(y), 1)
        return {"id": self.id, "name": self.name, "types": self.types, "rels": self.rels,
                "nodes": self.nodes, "edges": self.edges, **extra}


def layout(n, edges, seed=7, w=1000.0, h=1000.0):
    """Fruchterman–Reingold 力导向布局，固定随机种子：每次重跑坐标一样，网页里高亮也不会把图抖乱。

    参数是对着两张图调出来的（质检规则图谱 108 节点、300 节点的稀疏 Yuxi 样例）：
    - 理想边长 0.65·√(面积/节点数)，取 1.0 时质检图谱有 27–46 个节点挤在边上；
    - 线性向心力系数 24，坐标只在 3 倍框处兜底截断。按原文把坐标卡在 1 倍框里，
      稀疏的大图会有一半节点贴边（300 个里 147 个）；
    - 不在最大连通分量里的节点（如「可 → 不检查」）向心力 ×30，免得被推到角落。
    网页按坐标外包框自动缩放，坐标的绝对大小没有意义。
    """
    if n == 0:
        return np.zeros((0, 2))
    iters = 600 if n <= 400 else 300  # 1000 节点跑 600 轮要 40 秒左右
    rng = np.random.default_rng(seed)
    half = np.array([w / 2, h / 2])
    pos = rng.uniform(-1, 1, size=(n, 2)) * half
    k = 0.65 * np.sqrt(w * h / n)
    pairs = np.array([(a, b) for a, b in edges if a != b], dtype=int).reshape(-1, 2)
    csize = component_sizes(n, pairs)
    grav = np.where(csize < csize.max(), 24.0 * 30, 24.0)[:, None] * (k / max(w, h))
    t0 = w / 10
    for it in range(iters):
        delta = pos[:, None, :] - pos[None, :, :]
        dist = np.maximum(np.linalg.norm(delta, axis=-1), 0.01)
        disp = (delta / dist[..., None] * (k * k / dist)[..., None]).sum(axis=1)
        if len(pairs):
            d = pos[pairs[:, 0]] - pos[pairs[:, 1]]
            dl = np.maximum(np.linalg.norm(d, axis=-1, keepdims=True), 0.01)
            f = d / dl * (dl * dl / k)
            np.add.at(disp, pairs[:, 0], -f)
            np.add.at(disp, pairs[:, 1], f)
        disp -= pos * grav
        length = np.maximum(np.linalg.norm(disp, axis=-1, keepdims=True), 0.01)
        t = t0 * (1 - it / iters) + 0.5
        pos = np.clip(pos + disp / length * np.minimum(length, t), -3 * half, 3 * half)
    pos -= (pos.max(axis=0) + pos.min(axis=0)) / 2
    return pos


def component_sizes(n, pairs):
    """每个节点所在连通分量的大小（并查集）。"""
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs:
        parent[find(a)] = find(b)
    roots = [find(i) for i in range(n)]
    size = {}
    for r in roots:
        size[r] = size.get(r, 0) + 1
    return np.array([size[r] for r in roots])


# ---------------------------------------------------------------- 质检规则图谱

def build_rules_graph():
    lib = yaml.safe_load(RULES_YAML.read_text(encoding="utf-8"))
    excerpt = read_excerpt()
    rules = lib["规则"]
    g = Graph("qc-rules", "控规质检规则图谱")
    checks, problems = [], []

    def check(name, actual, expect=None, ok=None, note="", warn=False):
        """ok=False 中止构建（退出码 1）；warn=True 只提醒，页面和终端显示 ⚠。"""
        ok = (actual == expect) if ok is None else ok
        checks.append({"name": name, "actual": actual, "expect": expect, "ok": bool(ok), "warn": bool(warn), "note": note})

    ids = [r["id"] for r in rules]
    check("规则条数", len(rules), 21, note="Q01–Q21")
    check("规则编号唯一且连续", ids == [f"Q{i:02d}" for i in range(1, len(rules) + 1)], True)

    # 依据文件
    docs = dict(lib["依据文件"])
    doc_idx = {abbr: g.node(f"doc:{abbr}", "依据文件", abbr, props={"全称": full}) for abbr, full in docs.items()}
    doc_idx[COURSE_BASIS] = g.node(f"doc:{COURSE_BASIS}", "依据文件", COURSE_BASIS, props={"说明": COURSE_BASIS_NOTE})

    # 用词 → 严重度（准则附录五）
    word_sev, sev_idx, word_idx = {}, {}, {}
    for words, sev in lib["用词与严重度"].items():
        sev_idx.setdefault(sev, g.node(f"sev:{sev}", "严重度", sev))
        for w in [x.strip() for x in words.split("/")]:
            word_sev[w] = sev
            word_idx[w] = g.node(f"word:{w}", "用词", w, props={"出处": "准则2016 附录五「准则用词说明」"})
            g.edge(word_idx[w], sev_idx[sev], "对应")

    def sev_node(s):
        if s not in sev_idx:
            sev_idx[s] = g.node(f"sev:{s}", "严重度", s)
        return sev_idx[s]

    def find_words(text):
        """最长匹配：「不宜」不会被拆成「宜」，「不应」不会被拆成「应」。"""
        found, i, vocab = [], 0, sorted(word_sev, key=len, reverse=True)
        while i < len(text):
            for w in vocab:
                if text.startswith(w, i):
                    found.append(w)
                    i += len(w)
                    break
            else:
                i += 1
        return list(dict.fromkeys(found))

    def clause_node(doc, clause):
        key = f"{doc} {clause}"
        text = excerpt.get(key)
        return g.node(f"clause:{key}", "条文", key, short=clause,
                      props={"所属文件": doc, "摘录原文": text, "摘录": "已收录" if text else "摘录未收录，查原文"})

    cat_idx, landuse_idx, quote_stat, word_stat = {}, {}, {}, {"一致": 0, "无法核对": [], "不一致": []}
    code_mentions = 0

    def landuse_node(code):
        if code not in LANDUSE:
            return None
        if code not in landuse_idx:
            name = LANDUSE[code]
            landuse_idx[code] = g.node(f"lu:{code}", "用地", f"{code} {name}" if name else code, short=code,
                                       props={"代码": code, "名称": name or "（摘录未列名称，查准则2016 表3-2 原文）",
                                              "层级": "大类" if len(code) == 1 else "中类", "名称出处": LANDUSE_SRC})
            if len(code) > 1:
                parent = landuse_node(code[0])
                g.edge(landuse_idx[code], parent, "归属大类")
        return landuse_idx[code]

    def codes_in(text):
        out = {}
        for raw in CODE_RE.findall(text):
            if re.fullmatch(r"Q\d{2}", raw):  # 规则编号，另按「口径引用」处理
                continue
            for code in {re.sub(r"\*$", "", c) for c in re.split(r"[–-]", raw)}:
                mid = code if len(code) <= 2 else code[:2]
                out.setdefault(mid, []).append(raw)
        return out

    for r in rules:
        rid = r["id"]
        params = r.get("参数")
        ri = g.node(f"rule:{rid}", "规则", f"{rid} {r['名称']}", short=rid, props={
            "编号": rid, "名称": r["名称"], "类别": r["类别"], "依据": r["依据"], "原文": r["原文"],
            "用词": r["用词"], "严重度": r["严重度"], "适用": r["适用"], "口径": str(r["口径"]).strip(),
            "参数": json.dumps(params, ensure_ascii=False) if params else None, "检查函数": r["检查"],
        })
        for field in ("类别", "依据", "严重度", "检查"):
            if not r.get(field):
                problems.append(f"{rid} 缺「{field}」")

        # 类别
        cat = r["类别"]
        if cat not in cat_idx:
            cat_idx[cat] = g.node(f"cat:{cat}", "规则类别", cat)
        g.edge(ri, cat_idx[cat], "属于")

        # 依据：按括号外的「；」切成几段，每段 = 文件 + 若干条文号 + 括号注
        clause_keys = []
        for seg in split_top(r["依据"]):
            body, notes = strip_parens(seg)
            m = re.match(rf"^({DOC_RE}|{COURSE_BASIS})\s*(.*)$", body)
            if not m:
                problems.append(f"{rid} 依据「{seg}」认不出文件名")
                continue
            doc, rest = m.group(1), m.group(2)
            if doc not in doc_idx:
                problems.append(f"{rid} 依据文件「{doc}」不在规则库「依据文件」里")
                continue
            tokens = [t.strip() for t in rest.split("、") if t.strip()]
            if not tokens:
                g.edge(ri, doc_idx[doc], "依据", {"注": "；".join(notes)} if notes else None)
            for tok in tokens:
                if not CLAUSE_RE.fullmatch(tok):
                    problems.append(f"{rid} 依据里的「{tok}」不像条文号")
                    continue
                ci = clause_node(doc, tok)
                g.edge(ri, ci, "依据")
                g.edge(ci, doc_idx[doc], "出自")
                clause_keys.append(f"{doc} {tok}")
            for note in notes:  # 括号注里提到的其它文件 = 参照
                for other in re.findall(DOC_RE, note):
                    if other != doc and other in doc_idx:
                        g.edge(ri, doc_idx[other], "参照", {"注": note})

        # 原文与摘录核对
        quote = (r["原文"] or "").strip()
        if not quote:
            status = "原文为空（课程口径）"
        else:
            pool = norm_text("".join(excerpt.get(k, "") for k in clause_keys))
            frags = [norm_text(f) for f in quote.split("……") if norm_text(f)]
            if pool and all(f in pool for f in frags):
                status = "逐字一致"
            elif pool:
                ratio = min(max(SequenceMatcher(None, f, pool[i:i + len(f) + 20]).ratio()
                                for i in range(0, max(1, len(pool) - len(f) + 1), 4)) for f in frags)
                status = f"近似一致（相似度 {ratio:.2f}）" if ratio >= 0.85 else f"有出入（相似度 {ratio:.2f}）"
            else:
                status = "摘录未收录对应条文"
        g.nodes[ri]["p"]["摘录核对"] = status
        quote_stat.setdefault(status.split("（")[0], []).append(rid)

        # 用词 → 严重度，并核对规则自己写的严重度是否覆盖用词对应的严重度
        words = find_words(r["用词"])
        for w in words:
            g.edge(ri, word_idx[w], "用词", {"原文写法": r["用词"]} if r["用词"] != w else None)
        sevs = {}
        for part in split_top(r["严重度"]):
            for tok in SEV_TOKENS:
                if tok in part:
                    _, cond = strip_parens(part.replace(f"「{tok}」", tok))
                    sevs.setdefault(tok, "；".join(cond) or part.replace(tok, "").strip("；，、 ") or None)
                    break
            else:
                problems.append(f"{rid} 严重度「{part}」认不出")
        for s, cond in sevs.items():
            g.edge(ri, sev_node(s), "判定", {"条件": cond} if cond else None)
        implied = {word_sev[w] for w in words}
        if not implied:
            word_stat["无法核对"].append(f"{rid}（用词「{r['用词']}」不在附录五）")
        elif implied <= set(sevs):
            word_stat["一致"] += 1
        else:
            word_stat["不一致"].append(f"{rid} 用词→{implied}，规则写 {set(sevs)}")

        # 用地：适用 → 适用于；口径里另外提到的 → 口径涉及
        seen = set()
        for field, rel in (("适用", "适用于"), ("口径", "口径涉及")):
            for mid, raws in codes_in(str(r[field])).items():
                code_mentions += len(raws)
                if (rid, mid) in EXAMPLE_ONLY or mid in seen:
                    continue
                li = landuse_node(mid)
                if li is None:
                    problems.append(f"{rid}「{field}」里的用地代码 {raws} 不在 LANDUSE 字典里")
                    continue
                seen.add(mid)
                g.edge(ri, li, rel, {"原文写法": "、".join(dict.fromkeys(raws))})

        # 口径里引用的其它规则（如 Q20：无效地块不再做 Q12、Q18、Q19）
        for other in dict.fromkeys(re.findall(r"Q\d{2}", str(r["口径"]))):
            if other != rid:
                g.edge(ri, g.index[f"rule:{other}"] if f"rule:{other}" in g.index else
                       g.node(f"rule:{other}", "规则", other, short=other), "口径引用")

    # 明确不查的条文
    for item in lib.get("不适用", []):
        body, _ = strip_parens(item["条文"])
        m = re.match(rf"^({DOC_RE})", body)
        doc = m.group(1) if m else DEFAULT_DOC
        ni = g.node(f"skip:{item['条文']}", "明确不查", item["条文"],
                    props={"为什么不查": item["为什么不查"], "所属文件": doc})
        g.edge(ni, doc_idx[doc], "出自")

    if problems:
        fail("规则库有字段解析不了", problems)

    # 引用了却不在规则库里的规则编号
    dangling = [n["n"] for n in g.nodes if g.types[n["t"]] == "规则" and "p" not in n]
    if dangling:
        fail("口径里引用了不存在的规则", dangling)

    deg = np.zeros(len(g.nodes), dtype=int)
    for e in g.edges:
        deg[e[0]] += 1
        deg[e[1]] += 1
    isolated = [g.nodes[i]["n"] for i in np.where(deg == 0)[0]]
    used_docs = {e[1] for e in g.edges if g.rels[e[2]] in ("出自", "依据", "参照")}

    clause_total = sum(1 for n in g.nodes if g.types[n["t"]] == "条文")
    clause_in = sum(1 for n in g.nodes if g.types[n["t"]] == "条文" and n["p"].get("摘录") == "已收录")
    check("依据文件（规则库「依据文件」节 + 课程口径）", len(docs) + 1, 5)
    check("被规则或「不查」引用到的依据文件", len(used_docs & set(doc_idx.values())), len(doc_idx))
    check("规则类别", len(cat_idx), None, ok=len(cat_idx) > 0, note="、".join(cat_idx))
    check("条文节点在摘录里找到原文", f"{clause_in}/{clause_total}", None, ok=True,
          note="未收录：" + "、".join(n["n"] for n in g.nodes if g.types[n["t"]] == "条文" and n["p"]["摘录"] != "已收录"))
    check("规则「原文」与摘录逐字一致", len(quote_stat.get("逐字一致", [])), None, ok=True,
          warn=bool(quote_stat.get("有出入") or quote_stat.get("摘录未收录对应条文")),
          note="；".join(f"{k} {len(v)} 条：{'、'.join(v)}" for k, v in quote_stat.items() if k != "逐字一致"))
    check("用词→严重度 与规则写的严重度一致", word_stat["一致"], None, ok=not word_stat["不一致"],
          note="；".join(word_stat["不一致"] + word_stat["无法核对"]))
    check("用地代码提及 → 中类/大类节点", f"{code_mentions} 次 → {len(landuse_idx)} 个", None, ok=True,
          note="未列名称：" + "、".join(c for c in landuse_idx if not LANDUSE[c]))
    check("明确不查的条文", len(lib.get("不适用", [])), 3)
    check("孤立节点", len(isolated), 0, note="、".join(isolated))

    # 知识导图：规则库 → 类别 → 规则 → 按关系分组的邻居
    nbrs = {}
    for a, b, ri_, *rest in g.edges:
        nbrs.setdefault(a, []).append((g.rels[ri_], b))

    def rule_children(i):
        """规则的出边按关系分组：依据 / 用词 / 判定 / 适用于 / 口径涉及 …（「属于」已经是上一层）。"""
        out = []
        for rel in dict.fromkeys(r_ for r_, _ in nbrs.get(i, [])):
            if rel == "属于":
                continue
            kids = []
            for r_, b in nbrs[i]:
                if r_ == rel:
                    nd = g.nodes[b]
                    kids.append({"n": nd["s"] if g.types[nd["t"]] == "用地" else nd["n"], "i": b})
            out.append({"n": rel, "c": kids})
        return out

    tree = {"n": "质检规则库", "c": []}
    for cat, ci in cat_idx.items():
        members = [a for a, b, ri_, *_ in g.edges if b == ci and g.rels[ri_] == "属于"]
        tree["c"].append({"n": cat, "i": ci, "c": [{"n": g.nodes[a]["n"], "i": a, "c": rule_children(a)} for a in members]})
    tree["c"].append({"n": "明确不查的条文", "c": [{"n": n["n"], "i": i} for i, n in enumerate(g.nodes) if g.types[n["t"]] == "明确不查"]})

    return g.export(
        desc="从规则库 YAML 逐字段整理：规则—依据条文—依据文件、规则—用词—严重度、规则—适用用地。每条关系都能回到 YAML 的某个字段。",
        version=lib["版本"],
        source=["资料/质检智能体/规则库_参考.yaml", "资料/质检智能体/上海控规质检_条文摘录.md"],
        footer=f"规则库：资料/质检智能体/规则库_参考.yaml（{lib['版本']}）｜条文：上海公开发布文件摘录（准则2016、成果规范2020、技术规定、绿化审核），"
               "正式质检以主管部门口径和现行文本为准｜图谱数据结构对齐 Yuxi /api/graph/subgraph（xerrors/Yuxi，MIT）",
        tree=tree, checks=checks,
    )


# ---------------------------------------------------------------- Yuxi 子图

YUXI_SKIP_PROPS = {"kb_id", "embedding", "vector", "source_chunk_id"}


def build_yuxi_graph(path):
    """把 fetch_yuxi.py 存下的 /api/graph/subgraph 响应转成同一种图谱结构。"""
    raw = json.loads(path.read_text(encoding="utf-8"))
    data = raw.get("data", raw)
    nodes, edges = data.get("nodes") or [], data.get("edges") or []
    title = raw.get("kb_name") or raw.get("kb_id") or path.stem
    params = raw.get("params", {})
    g = Graph(f"yuxi-{path.stem}", f"Yuxi · {title}")
    dup = 0
    for nd in nodes:
        key = f"y:{nd['id']}"
        if key in g.index:
            dup += 1
            continue
        name, ntype = str(nd.get("name") or nd["id"]), nd.get("type") or "Entity"
        props = {k: (v[:300] + "…" if isinstance(v, str) and len(v) > 300 else v)
                 for k, v in (nd.get("properties") or {}).items()
                 if k not in YUXI_SKIP_PROPS and not isinstance(v, (list, dict)) and v not in (name, ntype)}
        g.node(key, ntype, name, props=props)
    dropped = []
    for ed in edges:
        a, b = g.index.get(f"y:{ed.get('source_id')}"), g.index.get(f"y:{ed.get('target_id')}")
        if a is None or b is None:
            dropped.append(ed.get("id"))
            continue
        props = {k: v for k, v in (ed.get("properties") or {}).items()
                 if k not in YUXI_SKIP_PROPS and not isinstance(v, (list, dict)) and v not in (None, "")}
        g.edge(a, b, ed.get("type") or "RELATED", props or None)

    # 知识导图：知识库 → 实体类型 → 实体（按连接数排序，每类最多 60 个）
    deg = {}
    for e in g.edges:
        deg[e[0]] = deg.get(e[0], 0) + 1
        deg[e[1]] = deg.get(e[1], 0) + 1
    tree = {"n": title, "c": []}
    for ti, t in sorted(enumerate(g.types), key=lambda x: -sum(n["t"] == x[0] for n in g.nodes)):
        members = sorted((i for i, n in enumerate(g.nodes) if n["t"] == ti), key=lambda i: -deg.get(i, 0))
        kids = [{"n": g.nodes[i]["n"], "i": i} for i in members[:60]]
        if len(members) > 60:
            kids.append({"n": f"… 其余 {len(members) - 60} 个"})
        tree["c"].append({"n": f"{t}（{len(members)}）", "c": kids})

    checks = [
        {"name": "节点", "actual": len(g.nodes), "expect": len(nodes) - dup, "ok": True, "note": f"重复 id {dup} 个已合并" if dup else ""},
        {"name": "关系（两端都在子图内）", "actual": len(g.edges), "expect": None, "ok": True, "warn": bool(dropped),
         "note": f"端点不在子图内、未画出 {len(dropped)} 条：{'、'.join(map(str, dropped[:5]))}" if dropped else ""},
        {"name": "查询参数", "actual": "", "expect": None, "ok": True, "warn": len(nodes) >= int(params.get("max_nodes", 10**9)),
         "note": f"关键词 {params.get('node_label', '*')} · 扩展 {params.get('max_depth', '?')} 跳 · 上限 {params.get('max_nodes', '?')} 个节点"
                 f" · {'不含' if str(params.get('exclude_chunk', 'true')) == 'true' else '含'}文档块"
                 + ("。节点数到了上限，子图被截断，不代表知识库全部实体" if len(nodes) >= int(params.get("max_nodes", 10**9)) else "")},
    ]
    print(f"  Yuxi {path.name}：节点 {len(g.nodes)}，关系 {len(g.edges)}" + (f"，丢弃端点缺失的关系 {len(dropped)} 条" if dropped else ""))
    return g.export(
        desc="Yuxi 知识库用大模型从文档块抽取的实体与关系（Neo4j），由 fetch_yuxi.py 经 /api/graph/subgraph 拉取。抽取结果未经人工审定。",
        version=raw.get("fetched_at", ""),
        source=[f"Yuxi 知识库 {raw.get('kb_id', '')}（/api/graph/subgraph）"],
        footer=f"图谱：Yuxi 知识库 {title}，大模型抽取，未经人工审定｜拉取时间 {raw.get('fetched_at', '未知')}｜Yuxi：xerrors/Yuxi（MIT）",
        tree=tree, checks=checks,
    )


def main():
    graphs = [build_rules_graph()]
    for path in sorted(YUXI_DIR.glob("*.json")) if YUXI_DIR.exists() else []:
        graphs.append(build_yuxi_graph(path))

    payload = {"meta": {"generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                        "script": "apps/kg-cockpit/build_data.py"}, "graphs": graphs}
    OUT_JS.write_text("// 由 build_data.py 生成，勿手改\nwindow.KG_DATA = "
                      + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")

    print(f"✓ 写出 {OUT_JS.relative_to(ROOT)}  {OUT_JS.stat().st_size / 1024:.1f} KB，图谱 {len(graphs)} 张")
    for gr in graphs:
        tcount = {t: sum(n["t"] == i for n in gr["nodes"]) for i, t in enumerate(gr["types"])}
        rcount = {r: sum(e[2] == i for e in gr["edges"]) for i, r in enumerate(gr["rels"])}
        print(f"【{gr['name']}】节点 {len(gr['nodes'])}，关系 {len(gr['edges'])}")
        print("  节点：" + "；".join(f"{t} {c}" for t, c in tcount.items()))
        print("  关系：" + "；".join(f"{r} {c}" for r, c in rcount.items()))
        for c in gr["checks"]:
            exp = "" if c["expect"] is None else f"（期望 {c['expect']}）"
            mark = "✗" if not c["ok"] else "⚠" if c.get("warn") else "✓"
            print(f"  {mark} {c['name']}：{c['actual']}{exp}" + (f"  {c['note']}" if c["note"] else ""))
    if not all(c["ok"] for gr in graphs for c in gr["checks"]):
        print("✗ 有核对项没过，data.js 已写出但请先查原因")
        sys.exit(1)


if __name__ == "__main__":
    main()
