"""
RAG 记忆引擎

优先使用本地 SentenceTransformer + ChromaDB；当模型、依赖或网络不可用时，
自动退回到确定性的哈希向量。这样项目可以在没有外部下载的情况下跑通
重建索引、检索上下文和流水线测试。
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import Any

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dependency guard
    load_dotenv = None

try:
    import chromadb
except Exception:  # pragma: no cover - optional dependency guard
    chromadb = None

try:
    from sentence_transformers import SentenceTransformer
except Exception:  # pragma: no cover - optional dependency guard
    SentenceTransformer = None


PROJECT_DIR = Path(__file__).resolve().parent
if load_dotenv:
    load_dotenv(PROJECT_DIR / ".env")
    try:
        from dotenv import dotenv_values
        for _k, _v in (dotenv_values(PROJECT_DIR / ".env") or {}).items():
            if _v and not os.getenv(_k):
                os.environ[_k] = _v
    except Exception:
        pass

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")


class HashEmbeddingModel:
    """Small deterministic fallback embedding model for tests and offline runs."""

    dimension = 384

    def encode(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        tokens = re.findall(r"[\w\u4e00-\u9fff]+", text.lower())
        if not tokens:
            tokens = [text[:64] or "empty"]
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[idx] += sign
        norm = sum(x * x for x in vector) ** 0.5 or 1.0
        return [x / norm for x in vector]


CHUNK_CHAR_LIMIT = 1800


class NovelRAG:
    EMBED_MODEL = os.getenv("NOVEL_EMBED_MODEL", r"D:\huggingface\bge-m3")

    def __init__(self, project_dir: str | Path):
        self.project_dir = Path(project_dir)
        self.mode = os.getenv("NOVEL_RAG_MODE", "auto").lower()
        self.EMBED_MODEL = os.getenv("NOVEL_EMBED_MODEL", self.EMBED_MODEL)
        self.model = self._load_embedding_model()

        if chromadb is None:
            raise RuntimeError("缺少 chromadb 依赖，无法初始化 RAG。可先运行 setup_test.py 检查环境。")

        db_path = self.project_dir / ".chromadb"
        self.client = chromadb.PersistentClient(path=str(db_path))
        self.characters = self.client.get_or_create_collection("characters")
        self.chapters = self.client.get_or_create_collection("chapters")
        self.settings = self.client.get_or_create_collection("world_settings")
        self.foreshadows = self.client.get_or_create_collection("foreshadows")
        print(f"[RAG] 初始化完成，embedding={self.model_name}")

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def index_character(self, char_name: str, char_doc: str, source_path: str = "") -> None:
        self._upsert_chunked(
            self.characters,
            base_id=char_name,
            document=char_doc,
            metadata={"name": char_name, "source_type": "character", "source_path": source_path},
        )
        print(f"[RAG] 角色已索引：{char_name}")

    def index_chapter(self, chapter_num: int, content: str, summary: str | None = None) -> None:
        """索引章节摘要；兼容旧调用 index_chapter(chapter_num, summary)。"""
        document = summary or content
        self._upsert_chunked(
            self.chapters,
            base_id=f"ch_{chapter_num:03d}",
            document=document,
            metadata={
                "chapter": chapter_num,
                "source_type": "chapter_memory",
                "full_path": f"02_正文/第{chapter_num:03d}章_定稿.md",
                "source_path": f"03_滚动记忆/章节记忆/第{chapter_num:03d}章_memory.json",
            },
        )
        print(f"[RAG] 第{chapter_num}章摘要已索引")

    def index_world_setting(self, key: str, content: str, source_path: str = "") -> None:
        self._upsert_chunked(
            self.settings,
            base_id=key,
            document=content,
            metadata={"source_type": "world_setting", "name": key, "source_path": source_path},
        )

    def index_foreshadow(self, fid: str, content: str, status: str = "pending", source_path: str = "") -> None:
        self._upsert_chunked(
            self.foreshadows,
            base_id=fid,
            document=content,
            metadata={"status": status, "source_type": "foreshadowing", "source_path": source_path},
        )

    def reindex_all(self) -> None:
        """扫描项目目录，重建角色、世界观、文风、伏笔、最近摘要索引。"""
        self._reset_collections()

        char_dir = self.project_dir / "00_世界观" / "角色档案"
        if char_dir.is_dir():
            for path in sorted(char_dir.glob("*.md")):
                if path.name != "角色模板.md":
                    self.index_character(
                        path.stem,
                        path.read_text(encoding="utf-8"),
                        str(path.relative_to(self.project_dir)).replace("\\", "/"),
                    )

        for rel, key in [
            ("00_世界观/世界观.md", "world_main"),
            ("00_世界观/时间线.md", "timeline"),
            ("00_世界观/文风档案.md", "style"),
            ("01_大纲/总纲.md", "global_outline"),
        ]:
            path = self.project_dir / rel
            if path.is_file():
                self.index_world_setting(key, path.read_text(encoding="utf-8"), rel)

        volume_dir = self.project_dir / "01_大纲" / "卷纲"
        if volume_dir.is_dir():
            for path in sorted(volume_dir.glob("第*卷.md")):
                match = re.search(r"第(\d+)卷", path.name)
                key = f"volume_{int(match.group(1)):02d}" if match else path.stem
                rel = str(path.relative_to(self.project_dir)).replace("\\", "/")
                self.index_world_setting(key, path.read_text(encoding="utf-8"), rel)

        foreshadow_file = self.project_dir / "03_滚动记忆" / "伏笔追踪.md"
        if foreshadow_file.is_file():
            content = foreshadow_file.read_text(encoding="utf-8")
            self.index_foreshadow(
                "foreshadow_table",
                content,
                self._detect_foreshadow_status(content),
                "03_滚动记忆/伏笔追踪.md",
            )

        recent_file = self.project_dir / "03_滚动记忆" / "最近摘要.md"
        if recent_file.is_file():
            for chapter_num, block in self._split_recent_summaries(recent_file.read_text(encoding="utf-8")):
                self.index_chapter(chapter_num, block)

        print("[RAG] 全量重建完成")

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def build_context(self, chapter_outline: str, n_chars: int = 5, n_chapters: int = 3) -> str:
        sections = [
            ("## 相关世界设定", self._query(self.settings, chapter_outline, 4)),
            ("## 相关角色档案", self._query(self.characters, chapter_outline, n_chars)),
            ("## 相关伏笔记录", self._query(self.foreshadows, chapter_outline, 3)),
            ("## 相关历史章节摘要", self._query(self.chapters, chapter_outline, n_chapters)),
        ]

        parts: list[str] = []
        for title, docs in sections:
            parts.append(title)
            if docs:
                parts.extend(doc.strip() for doc in docs if doc and doc.strip())
            else:
                parts.append("（暂无可检索内容）")
            parts.append("---")
        return "\n\n".join(parts).strip() + "\n"

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _load_embedding_model(self) -> Any:
        if self.mode in {"mock", "simple", "hash"}:
            self.model_name = "hash-embedding"
            return HashEmbeddingModel()

        model_path = Path(self.EMBED_MODEL)
        can_load_local = model_path.exists() or not (":" in self.EMBED_MODEL or "\\" in self.EMBED_MODEL)
        if SentenceTransformer is not None and can_load_local:
            try:
                print(f"[RAG] 加载 embedding 模型 {self.EMBED_MODEL}...")
                self.model_name = self.EMBED_MODEL
                return SentenceTransformer(self.EMBED_MODEL)
            except Exception as exc:
                print(f"[RAG] embedding 模型不可用，退回 hash embedding：{exc}")

        self.model_name = "hash-embedding"
        return HashEmbeddingModel()

    def _embedding(self, text: str) -> list[float]:
        vec = self.model.encode(text)
        if hasattr(vec, "tolist"):
            return vec.tolist()
        return list(vec)

    def _upsert(self, collection: Any, doc_id: str, document: str, metadata: dict[str, Any]) -> None:
        collection.upsert(
            ids=[doc_id],
            documents=[document],
            embeddings=[self._embedding(document)],
            metadatas=[self._clean_metadata(metadata)],
        )

    def _upsert_chunked(self, collection: Any, base_id: str, document: str, metadata: dict[str, Any]) -> None:
        chunks = self._chunk_markdown(document)
        if not chunks:
            return
        self._delete_chunk_family(collection, base_id)
        if len(chunks) == 1:
            heading, chunk = chunks[0]
            self._upsert(
                collection,
                base_id,
                chunk,
                {**metadata, "chunk_index": 1, "chunk_total": 1, "heading": heading},
            )
            return
        ids = [f"{base_id}__{idx:03d}" for idx in range(1, len(chunks) + 1)]
        documents = [chunk for _, chunk in chunks]
        metadatas = [
            self._clean_metadata({
                **metadata,
                "chunk_index": idx,
                "chunk_total": len(chunks),
                "heading": heading,
            })
            for idx, (heading, _) in enumerate(chunks, start=1)
        ]
        collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=[self._embedding(chunk) for chunk in documents],
            metadatas=metadatas,
        )

    def _query(self, collection: Any, query: str, n_results: int) -> list[str]:
        count = collection.count()
        if count <= 0 or n_results <= 0:
            return []
        result = collection.query(
            query_embeddings=[self._embedding(query)],
            n_results=min(n_results, count),
            include=["documents", "metadatas"],
        )
        docs = result.get("documents") or [[]]
        metadatas = result.get("metadatas") or [[]]
        if not docs:
            return []
        rows = []
        for doc, meta in zip(docs[0], metadatas[0] if metadatas else []):
            label = self._source_label(meta or {})
            rows.append(f"{label}\n{doc.strip()}" if label else doc.strip())
        return rows

    def _chunk_markdown(self, text: str, limit: int = CHUNK_CHAR_LIMIT) -> list[tuple[str, str]]:
        text = text.strip()
        if not text:
            return []
        if len(text) <= limit:
            return [("全文", text)]

        blocks: list[tuple[str, str]] = []
        current: list[str] = []
        heading = "全文"
        for line in text.splitlines():
            match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
            if match and current:
                blocks.append((heading, "\n".join(current).strip()))
                current = [line]
                heading = match.group(2).strip()
            else:
                if match:
                    heading = match.group(2).strip()
                current.append(line)
        if current:
            blocks.append((heading, "\n".join(current).strip()))

        chunks: list[tuple[str, str]] = []
        for block_heading, block in blocks:
            chunks.extend(self._split_block(block_heading, block, limit))
        return chunks

    def _split_block(self, heading: str, block: str, limit: int) -> list[tuple[str, str]]:
        if len(block) <= limit:
            return [(heading or "全文", block)]
        chunks: list[tuple[str, str]] = []
        parts = re.split(r"\n\s*\n", block)
        current: list[str] = []
        current_len = 0
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if len(part) > limit:
                if current:
                    chunks.append((heading or "全文", "\n\n".join(current)))
                    current = []
                    current_len = 0
                for start in range(0, len(part), limit):
                    chunks.append((heading or "全文", part[start : start + limit]))
                continue
            extra = len(part) + (2 if current else 0)
            if current and current_len + extra > limit:
                chunks.append((heading or "全文", "\n\n".join(current)))
                current = [part]
                current_len = len(part)
            else:
                current.append(part)
                current_len += extra
        if current:
            chunks.append((heading or "全文", "\n\n".join(current)))
        return chunks

    def _delete_chunk_family(self, collection: Any, base_id: str) -> None:
        try:
            existing = collection.get()
        except Exception:
            return
        ids = existing.get("ids", []) if isinstance(existing, dict) else []
        targets = [item for item in ids if item == base_id or item.startswith(f"{base_id}__")]
        if targets:
            collection.delete(ids=targets)

    def _clean_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        cleaned: dict[str, Any] = {}
        for key, value in metadata.items():
            if value is None:
                cleaned[key] = ""
            elif isinstance(value, (str, int, float, bool)):
                cleaned[key] = value
            else:
                cleaned[key] = str(value)
        return cleaned

    def _source_label(self, metadata: dict[str, Any]) -> str:
        source = metadata.get("source_path") or metadata.get("full_path") or metadata.get("name") or ""
        heading = metadata.get("heading") or ""
        index = metadata.get("chunk_index")
        total = metadata.get("chunk_total")
        parts = [str(source)] if source else []
        if heading and heading != "全文":
            parts.append(str(heading))
        if total and int(total) > 1:
            parts.append(f"{index}/{total}")
        return f"【{' · '.join(parts)}】" if parts else ""

    def _reset_collections(self) -> None:
        names = ["characters", "chapters", "world_settings", "foreshadows"]
        existing = {c.name for c in self.client.list_collections()}
        for name in names:
            if name in existing:
                self.client.delete_collection(name)
        self.characters = self.client.get_or_create_collection("characters")
        self.chapters = self.client.get_or_create_collection("chapters")
        self.settings = self.client.get_or_create_collection("world_settings")
        self.foreshadows = self.client.get_or_create_collection("foreshadows")

    def _split_recent_summaries(self, content: str) -> list[tuple[int, str]]:
        blocks = re.split(r"(?=## 第\d+章)", content)
        items: list[tuple[int, str]] = []
        for block in blocks:
            match = re.match(r"## 第(\d+)章", block.strip())
            if match:
                items.append((int(match.group(1)), block.strip()))
        return items

    def _detect_foreshadow_status(self, content: str) -> str:
        if "🟡" in content:
            return "pending"
        if "🔴" in content:
            return "abandoned"
        if "🟢" in content or "✅" in content:
            return "resolved"
        return "unknown"
