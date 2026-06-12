"""Knowledge graph and compounding tools.

The agent builds a knowledge graph over time by linking related facts,
decisions, and lessons. This is the "institutional knowledge" layer —
the agent gets smarter about your codebase with every session.

Exposed as MCP tools:
  - link_facts: Connect related memories
  - find_patterns: Discover patterns across stored knowledge
  - summarize_knowledge: Get a summary of what the agent knows about a project
"""

from typing import Optional

from perseus_agent_core.memory.backend import MemoryEntry


class KnowledgeGraphTool:
    """Builds and queries the agent's knowledge graph over stored memories."""

    def __init__(self, memory_backend):
        self.memory = memory_backend

    async def link_facts(
        self,
        source_id: str,
        target_id: str,
        relationship: str,
        project: str,
    ) -> dict:
        """Create a relationship between two stored memories.

        Example: link a "decision" to the "fact" that motivated it.
        """
        entry = MemoryEntry(
            content=f"Linked: {source_id} --[{relationship}]--> {target_id}",
            category="link",
            project=project,
            tags=["knowledge-graph", relationship],
            metadata={
                "source_id": source_id,
                "target_id": target_id,
                "relationship": relationship,
            },
        )

        entry_id = await self.memory.remember(entry)

        return {
            "status": "linked",
            "id": entry_id,
            "source": source_id,
            "target": target_id,
            "relationship": relationship,
        }

    async def find_patterns(self, project: str) -> dict:
        """Analyze stored memories to surface patterns.

        Uses the reflect operation to cross-reference memories and find:
        - Frequently co-occurring tags (emerging themes)
        - Confidence decay (facts that need refreshing)
        - Knowledge gaps (under-documented areas)
        """
        insights = await self.memory.reflect(project=project)

        return {
            "project": project,
            "insights": insights,
            "summary": f"Found {len(insights)} patterns across stored memories",
        }

    async def summarize_knowledge(self, project: str) -> dict:
        """Get a structured summary of everything the agent knows."""
        facts = await self.memory.recall(
            query="*", project=project, category="fact", limit=50
        )
        decisions = await self.memory.recall(
            query="*", project=project, category="decision", limit=50
        )
        preferences = await self.memory.recall(
            query="*", project=project, category="preference", limit=50
        )
        lessons = await self.memory.recall(
            query="*", project=project, category="lesson", limit=50
        )

        return {
            "project": project,
            "knowledge": {
                "facts": len(facts),
                "decisions": len(decisions),
                "preferences": len(preferences),
                "lessons": len(lessons),
            },
            "recent_facts": [r.entry.content for r in facts[:5]],
            "recent_decisions": [r.entry.metadata.get("decision", "") for r in decisions[:5]],
        }
