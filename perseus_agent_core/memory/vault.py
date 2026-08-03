"""Async boundary over the official synchronous Perseus Vault client.

The core package does not depend on the Vault transport. A caller supplies the
``perseus_vault_client.VaultClient`` instance, whose category/key/body API is
wrapped in ``asyncio.to_thread`` so synchronous stdio I/O never blocks an async
agent loop. Returned IDs are deterministic ``category:key`` values, making a
repeated logical write idempotent and allowing forget to reconstruct its Vault
identity without a process-local lookup table.
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any, Optional, Protocol

from perseus_agent_core.memory.backend import (
    MemoryBackend,
    MemoryBackendError,
    MemoryEntry,
    MemorySearchResult,
)


class VaultClient(Protocol):
    """Structural subset of ``perseus_vault_client.VaultClient``."""

    def remember(
        self,
        category: str,
        key: Optional[str] = None,
        body: Optional[dict[str, Any]] = None,
        *,
        importance: Optional[float] = None,
        **extra: Any,
    ) -> dict[str, Any]: ...

    def recall(
        self,
        query: str,
        *,
        category: Optional[str] = None,
        limit: int = 10,
        mode: str = "hybrid",
        **extra: Any,
    ) -> list[dict[str, Any]]: ...

    def forget(self, category: str, key: str, *, reason: Optional[str] = None) -> bool: ...

    def health(self) -> dict[str, Any]: ...

    def context(self, query: Optional[str] = None, **extra: Any) -> str: ...


class VaultMemoryBackend(MemoryBackend):
    """Adapt the official synchronous Vault client to ``MemoryBackend``."""

    def __init__(self, client: VaultClient):
        self.client = client

    @staticmethod
    def _key(entry: MemoryEntry) -> str:
        if entry.id:
            return entry.id
        stable = f"{entry.project}\0{entry.category}\0{entry.content}".encode("utf-8")
        return hashlib.sha256(stable).hexdigest()[:32]

    async def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        try:
            return await asyncio.to_thread(getattr(self.client, method), *args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - preserve backend failure boundary
            raise MemoryBackendError(f"perseus-vault {method} failed: {type(exc).__name__}") from exc

    async def remember(self, entry: MemoryEntry) -> str:
        key = self._key(entry)
        body = {
            "content": entry.content,
            "tags": list(entry.tags),
            "source_session": entry.source_session,
            "metadata": dict(entry.metadata),
        }
        result = await self._call(
            "remember",
            entry.category,
            key,
            body,
            importance=entry.confidence,
            workspace_hash=entry.project,
        )
        stored_key = result.get("key", key) if isinstance(result, dict) else key
        return f"{entry.category}:{stored_key}"

    async def recall(
        self,
        query: str,
        project: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 10,
        min_confidence: float = 0.0,
    ) -> list[MemorySearchResult]:
        items = await self._call(
            "recall",
            query,
            category=category,
            limit=limit,
            mode="hybrid",
            workspace_hash=project,
        )
        results: list[MemorySearchResult] = []
        for item in items if isinstance(items, list) else []:
            raw = item.get("raw", {}) if isinstance(item, dict) else {}
            raw = raw if isinstance(raw, dict) else {}
            body = raw.get("body_json") or raw.get("body") or {}
            if isinstance(body, str):
                import json

                try:
                    body = json.loads(body)
                except json.JSONDecodeError:
                    body = {"content": body}
            body = body if isinstance(body, dict) else {}
            metadata = body.get("metadata") or {}
            score = item.get("score", 0.0) if isinstance(item, dict) else 0.0
            score = float(score) if isinstance(score, (int, float)) else 0.0
            stored_category = raw.get("category") or category or "fact"
            stored_key = item.get("id") or raw.get("key") or raw.get("id", "")
            entry = MemoryEntry(
                content=str(item.get("text") or body.get("content", "")),
                category=str(stored_category),
                project=project or "",
                id=str(stored_key),
                tags=list(body.get("tags") or []),
                source_session=body.get("source_session"),
                confidence=score,
                metadata=metadata if isinstance(metadata, dict) else {},
            )
            if score >= min_confidence:
                results.append(MemorySearchResult(entry=entry, score=score, search_method="hybrid"))
        return results

    async def forget(self, entry_id: str) -> bool:
        category, separator, key = entry_id.partition(":")
        if not separator:
            category, key = "fact", category
        return bool(await self._call("forget", category, key, reason="agent backend forget"))

    async def reflect(self, project: Optional[str] = None) -> list[dict[str, Any]]:
        text = await self._call("context", query=project, workspace_hash=project)
        if not text:
            return []
        return [{"backend": "perseus-vault", "project": project, "context": str(text)}]

    async def health_check(self) -> dict[str, Any]:
        result = await self._call("health")
        result = dict(result) if isinstance(result, dict) else {"status": str(result)}
        result.setdefault("backend", "perseus-vault")
        return result
