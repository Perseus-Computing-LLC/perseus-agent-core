"""Elasticsearch memory backend.

Uses Elasticsearch directly via elasticsearch-py: keyword search always,
plus semantic search (ELSER via a `semantic_text` field) when the
deployment supports it — the index is created with a semantic mapping
first and falls back to a plain mapping if the inference endpoint isn't
available, so the backend works on any 8.x deployment and gets smarter
on Elastic Cloud.

Configuration via environment variables:
  ELASTIC_CLOUD_ID: Elastic Cloud deployment ID
  ELASTIC_API_KEY: Elasticsearch API key
  ELASTIC_MEMORY_INDEX: Index name (default: "perseus-agent-memory")
"""

import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from perseus_agent_core.memory.backend import (
    MemoryBackend,
    MemoryBackendError,
    MemoryEntry,
    MemorySearchResult,
)

_PLAIN_MAPPINGS = {
    "properties": {
        "content": {"type": "text"},
        "category": {"type": "keyword"},
        "project": {"type": "keyword"},
        "tags": {"type": "keyword"},
        "source_session": {"type": "keyword"},
        "confidence": {"type": "float"},
        "created_at": {"type": "date"},
        "updated_at": {"type": "date"},
        "metadata": {"type": "object", "enabled": True},
    }
}

_SEMANTIC_MAPPINGS = {
    "properties": {
        **_PLAIN_MAPPINGS["properties"],
        "content": {"type": "text", "copy_to": "content_semantic"},
        "content_semantic": {"type": "semantic_text"},
    }
}

# Optional elasticsearch-py for standalone mode
try:
    from elasticsearch import Elasticsearch
    _HAS_ELASTICSEARCH = True
except ImportError:
    _HAS_ELASTICSEARCH = False


class ElasticMemoryBackend(MemoryBackend):
    """Memory backend storing entries in an Elasticsearch index."""

    def __init__(self):
        self.cloud_id = os.getenv("ELASTIC_CLOUD_ID", "")
        self.api_key = os.getenv("ELASTIC_API_KEY", "")
        self.memory_index = os.getenv("ELASTIC_MEMORY_INDEX", "perseus-agent-memory")
        if not all([self.cloud_id, self.api_key]):
            raise ValueError(
                "ELASTIC_CLOUD_ID and ELASTIC_API_KEY must be set. "
                "Get them from elastic.co cloud console."
            )

        self._es = None
        self._semantic: Optional[bool] = None  # unknown until index is ensured

    @property
    def es(self):
        """Lazy Elasticsearch client — created on first use."""
        if self._es is None:
            try:
                from elasticsearch import Elasticsearch
            except ImportError as exc:
                raise MemoryBackendError(
                    "elasticsearch package not installed — "
                    "pip install -r requirements.txt"
                ) from exc
            self._es = Elasticsearch(
                cloud_id=self.cloud_id,
                api_key=self.api_key,
                request_timeout=10,
            )
        return self._es

    def _ensure_index(self) -> None:
        """Create the memory index on first use; detect semantic support."""
        if self._semantic is not None:
            return
        try:
            if self.es.indices.exists(index=self.memory_index):
                mapping = self.es.indices.get_mapping(index=self.memory_index)
                props = mapping[self.memory_index]["mappings"].get("properties", {})
                self._semantic = "content_semantic" in props
                return
            try:
                self.es.indices.create(
                    index=self.memory_index, mappings=_SEMANTIC_MAPPINGS
                )
                self._semantic = True
            except Exception:
                # No inference endpoint / pre-8.15 deployment — plain mapping.
                self.es.indices.create(
                    index=self.memory_index, mappings=_PLAIN_MAPPINGS
                )
                self._semantic = False
        except MemoryBackendError:
            raise
        except Exception as exc:
            self._semantic = None  # retry on next call
            raise MemoryBackendError(f"Elastic index setup failed: {exc}") from exc
    async def remember(self, entry: MemoryEntry) -> str:
        """Store a memory entry in Elasticsearch."""
        if not entry.id:
            entry.id = f"mem-{uuid.uuid4().hex[:12]}"

        now = datetime.now(timezone.utc)
        if not entry.created_at:
            entry.created_at = now
        entry.updated_at = now

        doc = {
            "id": entry.id,
            "content": entry.content,
            "category": entry.category,
            "project": entry.project,
            "tags": entry.tags,
            "source_session": entry.source_session,
            "confidence": entry.confidence,
            "created_at": entry.created_at.isoformat(),
            "updated_at": entry.updated_at.isoformat(),
            "metadata": entry.metadata,
        }

        self._ensure_index()
        try:
            # refresh="wait_for": a recall immediately after a remember must
            # see the new entry — session demos and tests depend on it.
            self.es.index(
                index=self.memory_index,
                id=entry.id,
                document=doc,
                refresh="wait_for",
            )
        except MemoryBackendError:
            raise
        except Exception as exc:
            raise MemoryBackendError(f"Elastic store failed: {exc}") from exc

        return entry.id

    async def recall(
        self,
        query: str,
        project: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 10,
        min_confidence: float = 0.0,
    ) -> list[MemorySearchResult]:
        """Search memory: keyword match always, semantic match when available.

        Returns [] only when the search succeeded and found nothing;
        backend failures raise MemoryBackendError.
        """
        self._ensure_index()

        filters = []
        if project:
            filters.append({"term": {"project": project}})
        if category:
            filters.append({"term": {"category": category}})
        if min_confidence > 0.0:
            filters.append({"range": {"confidence": {"gte": min_confidence}}})

        if not query or query == "*":
            # Tools use "*" to mean "everything in scope".
            bool_query: dict = {"must": {"match_all": {}}}
        else:
            should = [{"match": {"content": {"query": query}}}]
            if self._semantic:
                should.append(
                    {"semantic": {"field": "content_semantic", "query": query}}
                )
            bool_query = {"should": should, "minimum_should_match": 1}
        if filters:
            bool_query["filter"] = filters

        try:
            response = self.es.search(
                index=self.memory_index,
                query={"bool": bool_query},
                size=limit,
            )
        except Exception as exc:
            raise MemoryBackendError(f"Elastic search failed: {exc}") from exc

        results = []
        for hit in response["hits"]["hits"]:
            src = hit["_source"]
            entry = MemoryEntry(
                id=src.get("id", hit["_id"]),
                content=src.get("content", ""),
                category=src.get("category", "fact"),
                project=src.get("project", ""),
                tags=src.get("tags") or [],
                source_session=src.get("source_session"),
                confidence=src.get("confidence", 1.0),
                created_at=_parse_dt(src.get("created_at")),
                updated_at=_parse_dt(src.get("updated_at")),
                metadata=src.get("metadata") or {},
            )
            results.append(
                MemorySearchResult(
                    entry=entry,
                    score=hit.get("_score") or 0.0,
                    search_method="hybrid" if self._semantic else "keyword",
                )
            )
        return results

    async def forget(self, entry_id: str) -> bool:
        """Delete a memory entry by ID. Returns False if it didn't exist."""
        self._ensure_index()
        try:
            from elasticsearch import NotFoundError
        except ImportError as exc:
            raise MemoryBackendError("elasticsearch package not installed") from exc
        try:
            self.es.delete(index=self.memory_index, id=entry_id, refresh="wait_for")
            return True
        except NotFoundError:
            return False
        except Exception as exc:
            raise MemoryBackendError(f"Elastic delete failed: {exc}") from exc

    async def reflect(self, project: Optional[str] = None) -> list[dict]:
        """Cross-reference memories to find patterns and insights.

        Currently surfaces:
        - stale facts (confidence < 0.3) that may need re-verification
        - knowledge distribution by category (gaps show up as absences)
        """
        self._ensure_index()
        filters = [{"term": {"project": project}}] if project else []

        insights: list[dict] = []
        try:
            stale = self.es.search(
                index=self.memory_index,
                query={
                    "bool": {
                        "filter": filters
                        + [{"range": {"confidence": {"lt": 0.3}}}]
                    }
                },
                sort=[{"confidence": "asc"}],
                size=10,
            )
            for hit in stale["hits"]["hits"]:
                src = hit["_source"]
                insights.append(
                    {
                        "type": "stale_fact",
                        "summary": (
                            f"Low-confidence memory may need re-verification: "
                            f"{src.get('content', '')[:120]}"
                        ),
                        "confidence": src.get("confidence"),
                        "id": src.get("id", hit["_id"]),
                        "backend": "elastic",
                    }
                )

            clusters = self.es.search(
                index=self.memory_index,
                query={"bool": {"filter": filters}} if filters else {"match_all": {}},
                aggs={"by_category": {"terms": {"field": "category"}}},
                size=0,
            )
            buckets = (
                clusters.get("aggregations", {})
                .get("by_category", {})
                .get("buckets", [])
            )
            if buckets:
                dist = ", ".join(f"{b['key']}: {b['doc_count']}" for b in buckets)
                insights.append(
                    {
                        "type": "knowledge_distribution",
                        "summary": f"Knowledge by category — {dist}",
                        "backend": "elastic",
                    }
                )
        except Exception as exc:
            raise MemoryBackendError(f"Elastic reflect failed: {exc}") from exc

        return insights

    async def health_check(self) -> dict:
        """Verify Elasticsearch connection and index health. Never raises."""
        try:
            if not self.es.ping():
                return {
                    "status": "error",
                    "backend": "elastic",
                    "error": "Elasticsearch ping failed (bad credentials or endpoint)",
                }
            return {
                "status": "ok",
                "backend": "elastic",
                "cloud_id": self.cloud_id[:12] + "...",
                "memory_index": self.memory_index,
                "index_exists": bool(
                    self.es.indices.exists(index=self.memory_index)
                ),
                "semantic_search": self._semantic,
            }
        except Exception as exc:
            return {"status": "error", "backend": "elastic", "error": str(exc)}


def _parse_dt(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
