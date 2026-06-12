"""Abstract memory backend interface.

All memory backends (Elastic, Engram-rs) implement this interface so the agent
can swap between managed cloud memory and self-hosted open-source memory
without changing any agent code.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


class MemoryBackendError(RuntimeError):
    """The memory backend itself failed (connection, auth, storage).

    Distinct from an empty result: "I know nothing about that" and
    "my memory is broken" must never look the same to the caller.
    """


@dataclass
class MemoryEntry:
    """A single fact, decision, or piece of context stored in agent memory.

    `id` is optional: backends auto-generate one for falsy ids. It sits
    after the required fields because dataclass ordering forbids a
    defaulted field before non-defaulted ones.
    """

    content: str
    category: str  # "fact", "decision", "preference", "lesson", "context"
    project: str  # project namespace
    id: str = ""
    tags: list[str] = field(default_factory=list)
    source_session: Optional[str] = None
    confidence: float = 1.0  # 0.0-1.0, can decay or be reinforced
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class MemorySearchResult:
    """Result from a memory search with relevance score."""

    entry: MemoryEntry
    score: float
    search_method: str  # "semantic", "keyword", "hybrid"


class MemoryBackend(ABC):
    """Abstract interface for agent memory backends.

    Implementations:
      - ElasticMemoryBackend: Uses Elastic Agent Builder MCP
      - EngramMemoryBackend: Uses Engram-rs CLI (SQLite-backed)
    """

    @abstractmethod
    async def remember(self, entry: MemoryEntry) -> str:
        """Store a memory entry. Returns the entry ID."""
        ...

    @abstractmethod
    async def recall(
        self,
        query: str,
        project: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 10,
        min_confidence: float = 0.0,
    ) -> list[MemorySearchResult]:
        """Search memory for relevant entries.

        Args:
            query: Natural language search query
            project: Filter to specific project
            category: Filter to category ("fact", "decision", etc.)
            limit: Max results
            min_confidence: Minimum confidence threshold
        """
        ...

    @abstractmethod
    async def forget(self, entry_id: str) -> bool:
        """Remove a memory entry. Returns True if deleted."""
        ...

    @abstractmethod
    async def reflect(
        self,
        project: Optional[str] = None,
    ) -> list[dict]:
        """Cross-reference memories to synthesize new insights.

        This is the "institutional knowledge" operation — the agent looks
        across all stored facts and identifies patterns, contradictions,
        or gaps that should be surfaced to the user.
        """
        ...

    @abstractmethod
    async def health_check(self) -> dict:
        """Check backend health and connection status."""
        ...
