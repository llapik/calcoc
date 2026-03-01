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
        self._chromadb = None
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

    def _try_init_chromadb(self) -> None:
        """Try to initialize ChromaDB for semantic search."""
        try:
            import chromadb

            self._chromadb = chromadb.Client()
            self._collection = self._chromadb.create_collection(
                name="knowledge", metadata={"hnsw:space": "cosine"}
            )

            if self._documents:
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

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Search the knowledge base for relevant documents."""
        # Try ChromaDB first
        if self._collection is not None:
            try:
                results = self._collection.query(query_texts=[query], n_results=top_k)
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

        # Keyword-based fallback
        return self._keyword_search(query, top_k)

    def _keyword_search(self, query: str, top_k: int) -> list[dict]:
        """Simple keyword-based search as fallback."""
        query_words = set(query.lower().split())
        scored = []
        for doc in self._documents:
            text = (
                doc.get("content", "") + " " +
                doc.get("title", "") + " " +
                doc.get("description", "")
            ).lower()
            score = sum(1 for w in query_words if w in text)
            if score > 0:
                scored.append((score, doc))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [
            {**doc, "score": score}
            for score, doc in scored[:top_k]
        ]
