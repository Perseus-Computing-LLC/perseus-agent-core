"""Decision logging and recall tools.

Every time the agent (or a developer working with it) makes an architectural
decision, the agent logs it. Later sessions can recall past decisions and
their rationale, preventing the "why did we do that?" problem.

Exposed as MCP tools:
  - log_decision: Record a decision with rationale and context
  - recall_decisions: Find past decisions relevant to current context
  - list_decisions: List all decisions for a project
"""

from datetime import datetime, timezone
from typing import Optional

from perseus_agent_core.memory.backend import MemoryEntry


class DecisionLogTool:
    """Logs and recalls architectural decisions with rationale."""

    def __init__(self, memory_backend):
        self.memory = memory_backend

    async def log_decision(
        self,
        project: str,
        decision: str,
        rationale: str,
        alternatives: Optional[list[str]] = None,
        context: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> dict:
        """Log an architectural or design decision with full context.

        The agent calls this whenever a decision is made or discovered.
        Future sessions can recall these to understand why choices were made.
        """
        content_parts = [f"Decision: {decision}", f"Rationale: {rationale}"]

        if alternatives:
            content_parts.append(f"Alternatives considered: {', '.join(alternatives)}")

        if context:
            content_parts.append(f"Context: {context}")

        entry = MemoryEntry(
            content=" | ".join(content_parts),
            category="decision",
            project=project,
            tags=tags or ["decision"],
            metadata={
                "decision": decision,
                "rationale": rationale,
                "alternatives": alternatives or [],
                "context": context or "",
            },
        )

        entry_id = await self.memory.remember(entry)

        return {
            "status": "logged",
            "id": entry_id,
            "decision": decision,
        }

    async def recall_decisions(
        self,
        query: str,
        project: str,
        limit: int = 5,
    ) -> list[dict]:
        """Find past decisions relevant to the current situation."""
        results = await self.memory.recall(
            query=query,
            project=project,
            category="decision",
            limit=limit,
        )

        return [
            {
                "id": r.entry.id,
                "content": r.entry.content,
                "score": r.score,
                "metadata": r.entry.metadata,
            }
            for r in results
        ]

    async def list_decisions(self, project: str) -> list[dict]:
        """List all decisions for a project, newest first."""
        results = await self.memory.recall(
            query="decision",
            project=project,
            category="decision",
            limit=50,
        )

        return [
            {
                "id": r.entry.id,
                "content": r.entry.content,
                "metadata": r.entry.metadata,
            }
            for r in results
        ]
