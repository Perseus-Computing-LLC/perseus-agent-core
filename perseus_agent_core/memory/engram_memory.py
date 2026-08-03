"""Legacy Engram/Mimir compatibility backend.

Uses the historical Mimir (formerly Engram-rs) memory store. Mimir is an MCP-native
JSON-RPC stdio server backed by SQLite + FTS5. It provides persistent,
searchable memory across sessions with zero cloud dependencies.

This backend implements the shared interface for older consumers. It is not the
canonical Perseus Vault path; new integrations should use ``VaultMemoryBackend``.

Mimir: https://github.com/tcconnally/mimir (MIT licensed)
Perseus: https://github.com/tcconnally/perseus (context + memory for AI agents)
"""

import json
import os
import subprocess
import uuid
import time
from datetime import datetime, timezone
from typing import Optional

from perseus_agent_core.memory.backend import MemoryBackend, MemoryEntry, MemorySearchResult


class _MimirProcess:
    """Manages a persistent Mimir MCP stdio subprocess.

    Mimir v0.5.0 communicates via JSON-RPC 2.0 over stdin/stdout.
    This class handles the lifecycle: start, handshake, tool discovery,
    and sending/receiving JSON-RPC messages.
    """

    def __init__(self, binary: str, db_path: str):
        self.binary = binary
        self.db_path = db_path
        self._proc: Optional[subprocess.Popen] = None
        self._request_id = 0
        self._tools: dict[str, dict] = {}

    def _ensure_started(self):
        if self._proc is not None and self._proc.poll() is None:
            return  # Already running

        self._proc = subprocess.Popen(
            [self.binary, "--db", self.db_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )

        # MCP handshake: initialize
        init_response = self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "perseus-agent-core", "version": "1.0.0"},
        })
        if "error" in init_response:
            raise RuntimeError(f"Mimir initialize failed: {init_response['error']}")

        # Send initialized notification
        self._send_notification("notifications/initialized", {})

        # Discover tools
        tools_response = self._send_request("tools/list", {})
        for tool in tools_response.get("result", {}).get("tools", []):
            self._tools[tool["name"]] = tool

    def _send_request(self, method: str, params: dict) -> dict:
        """Send a JSON-RPC request and return the parsed response."""
        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }
        return self._send_raw(request)

    def _send_notification(self, method: str, params: dict):
        """Send a JSON-RPC notification (no response expected)."""
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        self._send_raw(notification, expect_response=False)

    def _send_raw(self, payload: dict, expect_response: bool = True) -> dict:
        """Write JSON-RPC message to stdin, read response from stdout."""
        assert self._proc is not None
        assert self._proc.stdin is not None
        assert self._proc.stdout is not None

        line = json.dumps(payload) + "\n"
        self._proc.stdin.write(line)
        self._proc.stdin.flush()

        if not expect_response:
            return {}

        response_line = self._proc.stdout.readline()
        if not response_line:
            raise RuntimeError("Mimir process closed stdout unexpectedly")

        try:
            return json.loads(response_line)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"Mimir returned invalid JSON: {response_line[:200]}") from e

    def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """Call a Mimir MCP tool and return the parsed text result."""
        self._ensure_started()

        response = self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })

        if "error" in response:
            raise RuntimeError(
                f"Mimir tool '{tool_name}' failed: {response['error']}"
            )

        # MCP tool results come as content blocks
        content = response.get("result", {}).get("content", [])
        if not content:
            return {}

        # First text block is the result
        text = content[0].get("text", "{}")
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return {"text": text}

    def close(self):
        if self._proc is not None:
            try:
                self._proc.stdin.close()
                self._proc.stdout.close()
                self._proc.wait(timeout=5)
            except Exception:
                self._proc.kill()
            self._proc = None

    def __del__(self):
        self.close()


class EngramMemoryBackend(MemoryBackend):
    """Self-hosted memory backend using Mimir (engram-rs successor).

    Mimir v0.5.0 is an MCP-native JSON-RPC stdio server. This backend
    manages a persistent mimir subprocess and calls MCP tools for all
    memory operations.

    Configuration via environment variables:
      MIMIR_BIN: Path to mimir binary (default: "mimir")
      ENGRAM_BIN: Fallback for legacy env var (deprecated)
      ENGRAM_DB_PATH: Full path to mimir.db
      MIMIR_DB_PATH: Preferred env var for db path
    """

    def __init__(self):
        # Binary: prefer MIMIR_BIN, fall back to ENGRAM_BIN, default "mimir"
        self.mimir_bin = os.getenv("MIMIR_BIN") or os.getenv("ENGRAM_BIN", "mimir")

        # DB path: prefer MIMIR_DB_PATH, fall back to ENGRAM_DB_PATH, default
        self.db_path = os.getenv(
            "MIMIR_DB_PATH",
        ) or os.getenv(
            "ENGRAM_DB_PATH",
        ) or os.path.expanduser("~/.mimir/data/mimir.db")

        self._mimir: Optional[_MimirProcess] = None

    def _get_mimir(self) -> _MimirProcess:
        """Lazy-init the Mimir subprocess."""
        if self._mimir is None:
            self._mimir = _MimirProcess(self.mimir_bin, self.db_path)
        return self._mimir

    async def remember(self, entry: MemoryEntry) -> str:
        """Store a memory entry via mimir_remember.

        Mimir stores entities with a composite key of (category, key).
        We use the entry's id as the key for direct lookup, and store
        the full payload as body_json.
        """
        if not entry.id:
            entry.id = f"mem-{uuid.uuid4().hex[:12]}"

        now = datetime.now(timezone.utc)
        entry.created_at = entry.created_at or now
        entry.updated_at = now

        body = {
            "content": entry.content,
            "project": entry.project,
            "tags": entry.tags,
            "source_session": entry.source_session,
            "confidence": entry.confidence,
            "created_at": entry.created_at.isoformat(),
            "updated_at": entry.updated_at.isoformat(),
            "metadata": entry.metadata,
        }

        mimir = self._get_mimir()
        result = mimir.call_tool("mimir_remember", {
            "category": entry.category,
            "key": entry.id,
            "body_json": json.dumps(body),
            "tags": entry.tags,
            "type": "insight",
        })

        if result.get("status") == "error":
            raise RuntimeError(f"Mimir remember failed: {result.get('error', 'unknown')}")

        return entry.id

    async def recall(
        self,
        query: str,
        project: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 10,
        min_confidence: float = 0.0,
    ) -> list[MemorySearchResult]:
        """Search memory via mimir_recall.

        Mimir uses SQLite FTS5 with BM25 ranking for full-text search.
        Results are filtered by category, type, and topic.
        """
        mimir = self._get_mimir()

        # Build filters — Mimir recall supports query, category, type, topic, limit
        args: dict = {"query": query, "limit": limit}
        if category:
            args["category"] = category

        result = mimir.call_tool("mimir_recall", args)

        # Parse results from Mimir's response format
        results = []
        entities = result.get("entities", result.get("results", []))
        if not entities and isinstance(result, list):
            entities = result

        for item in entities:
            if not isinstance(item, dict):
                continue

            # Extract body from Mimir entity format
            body = {}
            body_str = item.get("body_json", item.get("body", "{}"))
            if isinstance(body_str, str):
                try:
                    body = json.loads(body_str)
                except (json.JSONDecodeError, TypeError):
                    body = {}
            elif isinstance(body_str, dict):
                body = body_str

            content = body.get("content", item.get("content", ""))
            if not content:
                continue

            confidence = body.get("confidence", item.get("confidence", item.get("decay_score", 1.0)))
            if isinstance(confidence, (int, float)) and confidence < min_confidence:
                continue

            entry = MemoryEntry(
                id=item.get("key", item.get("id", "")),
                content=content,
                category=item.get("category", body.get("category", "fact")),
                project=body.get("project", ""),
                tags=body.get("tags", item.get("tags", [])),
                confidence=float(confidence) if confidence else 1.0,
                metadata=body.get("metadata", {}),
            )

            score = item.get("score", item.get("relevance", 0.0))
            results.append(MemorySearchResult(
                entry=entry,
                score=float(score) if score else 0.0,
                search_method="fts5",
            ))

        return results

    async def forget(self, entry_id: str) -> bool:
        """Soft-delete a memory entry via mimir_forget.

        Mimir uses soft delete (archived=1). The entry can be recovered.
        Requires the category to locate the entity. We try 'fact' as default
        since that's the most common category.
        """
        mimir = self._get_mimir()

        # First try to recall the entry to find its category
        recall_result = mimir.call_tool("mimir_recall", {
            "query": entry_id,
            "limit": 1,
        })
        entities = recall_result.get("entities", recall_result.get("results", []))
        category = "fact"
        if entities and isinstance(entities[0], dict):
            category = entities[0].get("category", "fact")

        result = mimir.call_tool("mimir_forget", {
            "category": category,
            "key": entry_id,
        })

        return result.get("status") != "error"

    async def reflect(self, project: Optional[str] = None) -> list[dict]:
        """Cross-reference memories to find patterns.

        Uses mimir_recall with topic/type filtering and aggregates results
        to identify patterns, contradictions, and knowledge gaps.
        """
        mimir = self._get_mimir()

        # Search for decisions and insights to cross-reference
        insights = []

        # Find contradictory decisions (same topic, different outcomes)
        if project:
            decisions = mimir.call_tool("mimir_recall", {
                "query": project,
                "category": "decision",
                "limit": 50,
            })
        else:
            decisions = mimir.call_tool("mimir_recall", {
                "query": "",
                "category": "decision",
                "limit": 50,
            })

        entities = decisions.get("entities", decisions.get("results", []))
        if entities:
            insights.append({
                "type": "cross_reference",
                "summary": f"Cross-referenced {len(entities)} decisions",
                "backend": "mimir",
                "entity_count": len(entities),
            })

        # Find stale facts (low confidence)
        stale = mimir.call_tool("mimir_recall", {
            "query": "",
            "limit": 20,
        })
        stale_entities = stale.get("entities", stale.get("results", []))
        low_confidence = [
            e for e in stale_entities
            if isinstance(e, dict) and e.get("decay_score", 1.0) < 0.3
        ]
        if low_confidence:
            insights.append({
                "type": "stale_facts",
                "summary": f"{len(low_confidence)} facts have decayed below 0.3 confidence",
                "count": len(low_confidence),
            })

        return insights or [
            {
                "type": "insight",
                "summary": "Mimir reflect operation — cross-session memory analysis",
                "backend": "mimir",
                "note": "No cross-session patterns detected yet. More sessions needed.",
            }
        ]

    async def health_check(self) -> dict:
        """Verify Mimir connection and database health."""
        try:
            mimir = self._get_mimir()
            result = mimir.call_tool("mimir_health", {})

            return {
                "status": result.get("status", "ok"),
                "backend": "mimir",
                "db_path": self.db_path,
                "entry_count": result.get("entity_count", result.get("entry_count", 0)),
                "db_size_bytes": result.get("db_size_bytes", 0),
            }
        except FileNotFoundError:
            return {
                "status": "error",
                "backend": "mimir",
                "db_path": self.db_path,
                "error": (
                    f"Mimir binary not found: {self.mimir_bin}. "
                    f"Install with: curl -sSL "
                    f"https://raw.githubusercontent.com/tcconnally/mimir/main/scripts/bootstrap.sh | bash"
                ),
            }
        except Exception as e:
            return {
                "status": "error",
                "backend": "mimir",
                "db_path": self.db_path,
                "error": str(e),
            }


# Backward-compatible alias
MimirMemoryBackend = EngramMemoryBackend
