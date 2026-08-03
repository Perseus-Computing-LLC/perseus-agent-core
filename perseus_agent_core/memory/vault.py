"""Thin adapter boundary for the canonical Perseus Vault client.

The core package deliberately does not depend on a transport or Vault SDK. A
consumer supplies its configured Vault client, and this adapter keeps the shared
agent interface stable while preventing legacy Elastic/Engram backends from
being mistaken for the canonical product path.
"""

from __future__ import annotations

from typing import Any, Optional, Protocol

from perseus_agent_core.memory.backend import MemoryBackend, MemoryEntry, MemorySearchResult


class VaultClient(Protocol):
    async def remember(self, entry: MemoryEntry) -> str: ...

    async def recall(
        self,
        query: str,
        project: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 10,
        min_confidence: float = 0.0,
    ) -> list[MemorySearchResult]: ...

    async def forget(self, entry_id: str) -> bool: ...

    async def reflect(self, project: Optional[str] = None) -> list[dict[str, Any]]: ...

    async def health_check(self) -> dict[str, Any]: ...


class VaultMemoryBackend(MemoryBackend):
    """Delegate the shared memory contract to an explicit Vault client."""

    def __init__(self, client: VaultClient):
        self.client = client

    async def remember(self, entry: MemoryEntry) -> str:
        return await self.client.remember(entry)

    async def recall(
        self,
        query: str,
        project: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 10,
        min_confidence: float = 0.0,
    ) -> list[MemorySearchResult]:
        return await self.client.recall(
            query,
            project=project,
            category=category,
            limit=limit,
            min_confidence=min_confidence,
        )

    async def forget(self, entry_id: str) -> bool:
        return await self.client.forget(entry_id)

    async def reflect(self, project: Optional[str] = None) -> list[dict[str, Any]]:
        return await self.client.reflect(project)

    async def health_check(self) -> dict[str, Any]:
        result = dict(await self.client.health_check())
        result.setdefault("backend", "perseus-vault")
        return result
