"""历史日志语义索引：records/*.md 与 reports/*.md 分块 → 向量化 → SQLite（data/rag_index.db）。

问答前懒同步：按文件内容 hash 与索引 diff，增量补 embedding；源文件删除时清对应
chunk；向量化模型变化时全量重建（meta 表记录 model）。检索用 numpy 余弦暴力计算，
万级 chunk 毫秒级，不引入向量库依赖。

自检（不调 API，用伪造向量验证分块/同步/删除/重建全链路）：
    python core/indexer.py --selfcheck
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hashlib
import re
import sqlite3
import time
from datetime import date, datetime, timedelta

import numpy as np

from core import config, llm

if sys.stdout is not None:
    sys.stdout.reconfigure(encoding="utf-8")

DB_PATH = config.DATA_DIR / "rag_index.db"

# capture.py 写时间线的占位条目，无信息量，不入索引
_PLACEHOLDER = "分析失败，下轮自动重试"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT
);
CREATE TABLE IF NOT EXISTS files (
  path TEXT PRIMARY KEY,
  hash TEXT
);
CREATE TABLE IF NOT EXISTS chunks (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  file_path  TEXT,
  source     TEXT,   -- 'record' 日报时间线 | 'report' 日报/周报
  date       TEXT,   -- YYYY-MM-DD，周报为空
  time       TEXT,   -- HH:MM，仅日报时间线有
  heading    TEXT,   -- 小节标题（分类 / 报告小节名）
  text       TEXT,   -- 块正文
  hash       TEXT,   -- 块内容 sha256
  embedding  BLOB,   -- float32 向量
  model      TEXT,   -- 生成向量所用模型（与 meta.model 一致）
  embedded_at REAL
);
CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_path);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(_SCHEMA)
    return conn


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _embed_text(date: str, time_: str, heading: str, body: str) -> str:
    """送入向量模型的文本：日期/时间/小节名一并带上，利于时间类提问的召回。"""
    where = " ".join(p for p in (date, time_) if p)
    return f"{where} {heading}\n{body}".strip()


# ---------- 分块解析 ----------

def parse_record_md(path: Path) -> list:
    """日报时间线 md → chunk 列表，以「## HH:MM · 分类」小节为界。

    返回元素：{date, time, heading, text}；文件标题（# 行）与"分析失败"占位块跳过。
    """
    date = path.stem
    chunks = []
    time_ = heading = None
    body: list = []

    def flush() -> None:
        text = "\n".join(body).strip()
        if heading is not None and text and text != _PLACEHOLDER:
            chunks.append({"date": date, "time": time_, "heading": heading, "text": text})

    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            flush()
            body = []
            head = line[3:].strip()
            t, _, cat = head.partition("·")
            time_, heading = t.strip(), (cat.strip() or head)
        elif line.startswith("# "):
            continue  # 文件大标题
        else:
            body.append(line)
    flush()
    return chunks


def parse_report_md(path: Path) -> list:
    """报告 md → chunk 列表，以「## 」小节为界；文件名可解析出日期则带上。"""
    import re  # noqa: PLC0415

    m = re.search(r"\d{4}-\d{2}-\d{2}", path.stem)
    date = m.group(0) if m else ""
    title = ""
    chunks = []
    heading = None
    body: list = []

    def flush() -> None:
        text = "\n".join(body).strip()
        if heading is not None and text:
            chunks.append({"date": date, "time": "", "heading": heading, "text": text})

    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# ") and not line.startswith("## "):
            title = line[2:].strip()
            continue
        if line.startswith("## "):
            flush()
            body = []
            heading = line[3:].strip()
        else:
            body.append(line)
    flush()
    # 块内没有独立标题上下文时把报告标题并进首块，检索"周报"这类词也能命中
    if chunks and title:
        first = chunks[0]
        first["heading"] = f"{title} · {first['heading']}" if first["heading"] else title
    return chunks


# ---------- 懒同步 ----------

def _require_embed_config() -> None:
    if not config.EMBED_API_KEY:
        raise ValueError("问答检索尚未配置向量化 API Key，请在设置页「问答检索」中填写")


def _iter_source_files():
    """待索引文件与来源类型（records 下的 md 是日报时间线，reports 下的都是报告）。"""
    if config.RECORDS_DIR.exists():
        for p in sorted(config.RECORDS_DIR.glob("*.md")):
            yield p, "record"
    if config.REPORTS_DIR.exists():
        for p in sorted(config.REPORTS_DIR.glob("*.md")):
            yield p, "report"


def _embed_batch(texts: list) -> list:
    return llm.embed_texts(config.EMBED_BASE_URL, config.EMBED_API_KEY,
                           config.EMBED_MODEL, texts, label="问答索引")


def sync_index() -> dict:
    """把记录/报告增量同步进向量索引；调用前须已配置向量化服务。

    返回 {"indexed": 新索引文件数, "skipped": 未变化数, "removed": 清理数, "chunks": 现有块数}。
    """
    _require_embed_config()
    model = config.EMBED_MODEL
    conn = _connect()
    try:
        meta = dict(conn.execute("SELECT key, value FROM meta"))
        if meta.get("model") != model:  # 模型（向量空间）变了：旧向量全部作废
            conn.execute("DELETE FROM chunks")
            conn.execute("DELETE FROM files")
            conn.execute("INSERT OR REPLACE INTO meta VALUES ('model', ?)", (model,))

        wanted = {}
        for p, source in _iter_source_files():
            text = p.read_text(encoding="utf-8")
            wanted[str(p)] = (source, _sha256(text), text)
        known = {row[0]: row[1] for row in conn.execute("SELECT path, hash FROM files")}

        removed = 0
        for path in known:
            if path not in wanted:  # 源文件已删（如保留天数清理）：索引同步移除
                conn.execute("DELETE FROM chunks WHERE file_path = ?", (path,))
                conn.execute("DELETE FROM files WHERE path = ?", (path,))
                removed += 1

        indexed = skipped = 0
        for path, (source, fhash, text) in wanted.items():
            if path in known and known[path] == fhash:
                skipped += 1
                continue
            conn.execute("DELETE FROM chunks WHERE file_path = ?", (path,))
            chunks = (parse_record_md(Path(path)) if source == "record"
                      else parse_report_md(Path(path)))
            for c in chunks:
                c["source"] = source
                c["file_path"] = path
                c["hash"] = _sha256(c["text"])
            for i in range(0, len(chunks), config.EMBED_BATCH):
                batch = chunks[i:i + config.EMBED_BATCH]
                vecs = _embed_batch([_embed_text(c["date"], c["time"], c["heading"], c["text"])
                                     for c in batch])
                for c, vec in zip(batch, vecs):
                    conn.execute(
                        "INSERT INTO chunks (file_path, source, date, time, heading, text,"
                        " hash, embedding, model, embedded_at)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (c["file_path"], c["source"], c["date"], c["time"], c["heading"],
                         c["text"], c["hash"], np.asarray(vec, dtype=np.float32).tobytes(),
                         model, time.time()))
            conn.execute("INSERT OR REPLACE INTO files VALUES (?, ?)", (path, fhash))
            indexed += 1
        conn.commit()
        n = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        if indexed or removed:
            _vec_cache.clear()  # 向量缓存随数据变化失效
        return {"indexed": indexed, "skipped": skipped, "removed": removed, "chunks": n}
    finally:
        conn.close()


# ---------- 检索 ----------

# 进程内向量缓存：(model, 元数据列表, 矩阵)；sync/模型切换时清空。
# 万级 chunk × 1024 维约 40MB，换得每次问答免掉一次全表 BLOB 读取。
_vec_cache: list = []


def _load_vectors(model: str):
    if _vec_cache and _vec_cache[0] == model:
        return _vec_cache[1], _vec_cache[2]
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT source, date, time, heading, text, file_path, embedding"
            " FROM chunks WHERE model = ?", (model,)).fetchall()
    finally:
        conn.close()
    metas, vecs = [], []
    for source, date, time_, heading, text, fpath, blob in rows:
        vecs.append(np.frombuffer(blob, dtype=np.float32))
        metas.append({"source": source, "date": date, "time": time_,
                      "heading": heading, "text": text, "file_path": fpath})
    _vec_cache.clear()
    _vec_cache.extend([model, metas, vecs])
    return metas, vecs


def extract_dates(query: str) -> list:
    """从问题抽明确日期：2026-08-28 / 2026年8月28日 / 8月28号(日) / 今天/昨天/前天。

    月日式缺省按当前年解析（解析到无数据自然回退全局检索）。相对表达
    （上周/上个月等）不解析，返回空列表走全局检索。
    """
    found = set()
    for m in re.finditer(r"(\d{4})[年\-/.](\d{1,2})[月\-/.](\d{1,2})", query):
        try:
            found.add(date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat())
        except ValueError:
            continue  # 2026-13-45 之类的口误日期，不当作过滤条件
    for m in re.finditer(r"(\d{1,2})月(\d{1,2})[号日]?", query):
        try:
            found.add(date(datetime.now().year, int(m.group(1)), int(m.group(2))).isoformat())
        except ValueError:
            continue
    today = date.today()
    if "今天" in query:
        found.add(today.isoformat())
    if "昨天" in query:
        found.add((today - timedelta(days=1)).isoformat())
    if "前天" in query:
        found.add((today - timedelta(days=2)).isoformat())
    return sorted(found)


def search(query: str, top_k: int = None) -> list:
    """问题向量化后在索引内做余弦检索，返回按相关度降序的 chunk 元数据（含 score）。

    问题含明确日期时只在该日期的块内检索（无匹配回退全局）——embedding 对
    "8月28号"和"2026-08-28"这类日期数字的语义对齐弱，必须显式过滤兜底。
    """
    _require_embed_config()
    top_k = top_k or config.ASK_TOP_K
    qvec = llm.embed_texts(config.EMBED_BASE_URL, config.EMBED_API_KEY,
                           config.EMBED_MODEL, [query], label="问答检索")[0]
    q = np.asarray(qvec, dtype=np.float32)
    metas, vecs = _load_vectors(config.EMBED_MODEL)
    hits = []
    qnorm = float(np.linalg.norm(q))
    for meta, v in zip(metas, vecs):
        if v.shape[0] != q.shape[0]:  # 维度不符的残留向量（理论上已被重建清空）跳过
            continue
        denom = qnorm * float(np.linalg.norm(v))
        sim = float(q @ v / denom) if denom else 0.0
        hits.append({**meta, "score": round(sim, 4)})
    hits.sort(key=lambda h: -h["score"])
    wanted = set(extract_dates(query))
    if wanted:
        dated = [h for h in hits if h.get("date") in wanted]
        if dated:
            return dated[:top_k]
    return hits[:top_k]


# ---------- 自检 ----------

def _selfcheck() -> int:
    """不调 API 的全链路自检：伪造向量验证 分块→同步→检索→删除→重建。"""
    import shutil
    import tempfile

    print("[selfcheck] 建立临时索引环境…")
    tmp = Path(tempfile.mkdtemp(prefix="dailylog-rag-selfcheck-"))
    old = (DB_PATH, config.RECORDS_DIR, config.REPORTS_DIR)
    fail = []

    def check(name, cond, detail=""):
        print(f"  {'✓' if cond else '✗'} {name}{('：' + detail) if detail else ''}")
        if not cond:
            fail.append(name)

    try:
        rec_dir, rep_dir = tmp / "records", tmp / "reports"
        rec_dir.mkdir()
        rep_dir.mkdir()
        config.RECORDS_DIR, config.REPORTS_DIR = rec_dir, rep_dir
        indexer_db = tmp / "rag_index.db"
        # DB_PATH 是模块常量，替换后 _connect 走临时库
        globals()["DB_PATH"] = indexer_db

        (rec_dir / "2026-08-28.md").write_text(
            "# 2026-08-28 工作日志\n\n"
            "## 22:44 · 开发\n排查右上角指示灯黑色字体不可见问题\n进展：已定位为 CSS 问题\n\n"
            "## 22:50 · 其他\n分析失败，下轮自动重试\n\n"
            "## 22:55 · 会议\n与产品确认日报模板改版方向\n\n", encoding="utf-8")
        (rec_dir / "2026-08-29.md").write_text(
            "# 2026-08-29 工作日志\n\n## 10:00 · 开发\n实现问答检索的向量索引模块\n\n",
            encoding="utf-8")
        (rep_dir / "日报-2026-08-28.md").write_text(
            "# 日报 2026-08-28\n\n## 今日核心成果\n### 成果一\n修复指示灯样式问题并验证\n\n"
            "## 风险与阻塞\n暂无\n\n", encoding="utf-8")

        def fake_embed(base_url, api_key, model, texts, label="向量化"):
            out = []
            for t in texts:
                # 确定性伪向量：让含"字体"的文本彼此相近，便于检索断言
                seed = hashlib.sha256(("字体" if "字体" in t else t).encode()).digest()
                v = np.frombuffer(seed, dtype=np.uint8)[:16].astype(np.float32)
                out.append((v / (np.linalg.norm(v) or 1)).tolist())
            return out

        real_embed = llm.embed_texts
        llm.embed_texts = fake_embed
        real_key, real_model = config.EMBED_API_KEY, config.EMBED_MODEL
        config.EMBED_API_KEY = "test-key"
        config.EMBED_MODEL = "fake-embedding"
        try:
            print("[selfcheck] 1/5 首次同步")
            stats = sync_index()
            check("三份文件全部入库", stats["indexed"] == 3, str(stats))
            # 08-28 两个有效块（占位块跳过）+ 08-29 一块 + 报告两块
            check("占位条目未入索引", stats["chunks"] == 5, f"chunks={stats['chunks']}")

            print("[selfcheck] 2/5 幂等懒同步")
            stats2 = sync_index()
            check("未变化文件跳过", stats2["indexed"] == 0 and stats2["skipped"] == 3, str(stats2))

            print("[selfcheck] 3/5 检索")
            hits = search("字体显示问题")
            check("命中字体相关记录", bool(hits) and "字体" in hits[0]["text"],
                  hits[0]["text"][:20] if hits else "无结果")
            check("结果带引用元数据", bool(hits) and hits[0]["date"] == "2026-08-28"
                  and hits[0]["source"] in ("record", "report"))

            print("[selfcheck] 4/5 源文件删除同步清理")
            (rec_dir / "2026-08-29.md").unlink()
            stats3 = sync_index()
            check("删除文件被清出索引", stats3["removed"] == 1, str(stats3))

            print("[selfcheck] 5/5 模型切换全量重建")
            config.EMBED_MODEL = "fake-embedding-v2"
            stats4 = sync_index()
            check("切换模型后重建", stats4["indexed"] == 2 and stats4["chunks"] == 4, str(stats4))

            print("[selfcheck] 6/6 日期提问过滤")
            hits = search("8月28号都做了什么")
            check("日期命中限定当天", bool(hits) and all(h["date"] == "2026-08-28" for h in hits),
                  str(sorted({h["date"] for h in hits})))
            hits2 = search("2020年1月1号都做了什么")
            check("无匹配日期回退全局", len(hits2) == 4,
                  f"{len(hits2)} hits（库里全部块）")
        finally:
            llm.embed_texts = real_embed
            config.EMBED_API_KEY, config.EMBED_MODEL = real_key, real_model
    except Exception as e:  # noqa: BLE001
        fail.append(f"异常: {e}")
        print(f"  ✗ 自检异常: {e!r}")
    finally:
        globals()["DB_PATH"] = old[0]
        config.RECORDS_DIR, config.REPORTS_DIR = old[1], old[2]
        _vec_cache.clear()  # 缓存可能持有临时库的向量
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"[selfcheck] {'全部通过' if not fail else f'失败 {len(fail)} 项'}")
    return 0 if not fail else 1


def main() -> int:
    if "--selfcheck" in sys.argv:
        return _selfcheck()
    print("用法：python core/indexer.py --selfcheck")
    return 0


if __name__ == "__main__":
    sys.exit(main())
