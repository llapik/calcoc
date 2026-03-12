"""Retrieval-Augmented Generation — local knowledge base for repair guidance."""

import json
from pathlib import Path

from src.core.logger import get_logger

log = get_logger("ai.rag")


class KnowledgeBase:
    """Simple file-based knowledge retrieval (ChromaDB when available, fallback to keyword search)."""

    def __init__(self, knowledge_dir: str | Path):
        self.knowledge_dir = Path(knowledge_dir)
        self._documents: list[dict] = []
        self._texts: list[str] = []  # precomputed lowercase searchable text per document
        self._collection = None
        self._load_documents()
        self._try_init_chromadb()

    def _load_documents(self) -> None:
        """Load all JSON knowledge files from the knowledge directory."""
        if not self.knowledge_dir.exists():
            log.warning("Knowledge directory not found: %s", self.knowledge_dir)
            return

        for path in self.knowledge_dir.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, list):
                    self._documents.extend(data)
                elif isinstance(data, dict) and "entries" in data:
                    self._documents.extend(data["entries"])
            except Exception as exc:
                log.warning("Failed to load %s: %s", path, exc)

        log.info("Loaded %d knowledge documents", len(self._documents))
        self._texts = [
            " ".join(filter(None, [
                d.get("content", ""), d.get("title", ""), d.get("description", ""),
            ])).lower()
            for d in self._documents
        ]

    def _try_init_chromadb(self) -> None:
        """Try to initialize ChromaDB for semantic search."""
        if not self._documents:
            return
        try:
            import chromadb

            # EphemeralClient is the current API; fall back to Client for older versions
            try:
                client = chromadb.EphemeralClient()
            except AttributeError:
                client = chromadb.Client()  # type: ignore[attr-defined]

            self._collection = client.create_collection(
                name="knowledge", metadata={"hnsw:space": "cosine"}
            )

            ids = [f"doc_{i}" for i in range(len(self._documents))]
            texts = [
                d.get("content", "") or d.get("description", "") or str(d)
                for d in self._documents
            ]
            metadatas = [
                {"title": d.get("title", ""), "category": d.get("category", "")}
                for d in self._documents
            ]
            self._collection.add(documents=texts, ids=ids, metadatas=metadatas)
            log.info("ChromaDB initialized with %d documents", len(self._documents))
        except ImportError:
            log.debug("ChromaDB not available, falling back to keyword search")
        except Exception as exc:
            log.warning("ChromaDB initialization failed: %s", exc)
            self._collection = None

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Search the knowledge base for relevant documents."""
        if not self._documents:
            return []

        # Clamp top_k so ChromaDB doesn't crash when collection has fewer docs
        effective_k = min(top_k, len(self._documents))

        if self._collection is not None:
            try:
                results = self._collection.query(query_texts=[query], n_results=effective_k)
                docs = []
                for i, doc_text in enumerate(results["documents"][0]):
                    meta = results["metadatas"][0][i] if results["metadatas"] else {}
                    docs.append({
                        "content": doc_text,
                        "title": meta.get("title", ""),
                        "category": meta.get("category", ""),
                        "score": results["distances"][0][i] if results.get("distances") else 0,
                    })
                return docs
            except Exception as exc:
                log.debug("ChromaDB search failed, using keyword fallback: %s", exc)

        return self._keyword_search(query, effective_k)

    def _keyword_search(self, query: str, top_k: int) -> list[dict]:
        """Simple keyword-based search as fallback."""
        query_words = set(query.lower().split())
        scored = []
        for doc, text in zip(self._documents, self._texts):
            score = sum(1 for w in query_words if w in text)
            if score > 0:
                scored.append((score, doc))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {**doc, "score": score}
            for score, doc in scored[:top_k]
        ]
