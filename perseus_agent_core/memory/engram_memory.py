"""Engram-rs memory backend — self-hosted, MIT-licensed persistent memory.

Uses Engram-rs CLI (engram) as the memory store. Engram-rs is a SQLite-backed
long-term memory system for AI agents that provides persistent, searchable
memory across sessions with zero cloud dependencies.

This backend implements the same MemoryBackend interface as ElasticMemoryBackend,
so switching between Elastic (cloud) and Engram-rs (local) requires changing
exactly one line of configuration.

Engram-rs: https://github.com/tcconnally/engram-rs (MIT licensed)
Perseus: https://github.com/tcconnally/perseus (context + memory for AI agents)
"""

import json
import os
import subprocess
import uuid
from datetime import datetime, timezone
from typing import Optional

from perseus_agent_core.memory.backend import MemoryBackend, MemoryEntry, MemorySearchResult


class EngramMemoryBackend(MemoryBackend):
    """Self-hosted memory backend using Engram-rs.

    Configuration via environment variables:
      ENGRAM_BIN: Path to engram binary (default: "engram")
      ENGRAM_DATA_DIR: Data directory (default: "~/.hermes/mnemosyne/data")
      ENGRAM_DB_PATH: Full path to engram.db (overrides ENGRAM_DATA_DIR)

    Engram-rs provides MCP-compatible tools:
      - engram_store: persist a memory entry
      - engram_recall: search memory
      - engram_health: check connection
    """

    def __init__(self):
        self.engram_bin = os.getenv("ENGRAM_BIN", "engram")
        data_dir = os.getenv(
            "ENGRAM_DATA_DIR",
            os.path.expanduser("~/.hermes/mnemosyne/data"),
        )
        self.db_path = os.getenv(
            "ENGRAM_DB_PATH",
            os.path.join(data_dir, "mnemosyne.db"),
        )

    def _run_engram(self, args: list[str], retries: int = 1) -> dict:
        """Run an engram CLI command and return parsed JSON output.

        Args:
            args: CLI arguments to pass to engram
            retries: Number of retry attempts on transient failures (timeout/lock)
        """
        cmd = [self.engram_bin] + args
        last_error = None
        for attempt in range(retries + 1):
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode != 0:
                    stderr = result.stderr.strip()
                    # Retry on transient SQLite lock errors
                    if "database is locked" in stderr.lower() and attempt < retries:
                        import time
                        time.sleep(2 * (attempt + 1))
                        last_error = stderr
                        continue
                    return {
                        "error": stderr,
                        "exit_code": result.returncode,
                    }
                if result.stdout.strip():
                    return json.loads(result.stdout)
                return {}
            except FileNotFoundError:
                return {
                    "error": f"Engram binary not found: {self.engram_bin}. "
                    f"Install with: curl -sSL https://raw.githubusercontent.com/"
                    f"tcconnally/engram-rs/main/scripts/bootstrap.sh | bash",
                    "exit_code": -1,
                }
            except subprocess.TimeoutExpired:
                if attempt < retries:
                    import time
                    time.sleep(2 * (attempt + 1))
                    last_error = "Engram command timed out"
                    continue
                return {"error": "Engram command timed out after retries", "exit_code": -2}
        return {"error": last_error or "unknown error", "exit_code": -3}

    async def remember(self, entry: MemoryEntry) -> str:
        """Store a memory entry via engram_store.

        Engram-rs stores entries as key-value pairs with metadata in SQLite.
        """
        if not entry.id:
            entry.id = f"mem-{uuid.uuid4().hex[:12]}"

        now = datetime.now(timezone.utc)
        entry.created_at = entry.created_at or now
        entry.updated_at = now

        payload = {
            "id": entry.id,
            "content": entry.content,
            "category": entry.category,
            "project": entry.project,
            "tags": entry.tags,
            "confidence": entry.confidence,
            "metadata": entry.metadata,
        }

        result = self._run_engram(
            [
                "store",
                "--db", self.db_path,
                "--id", entry.id,
                "--data", json.dumps(payload),
                "--project", entry.project,
                "--category", entry.category,
                "--tags", ",".join(entry.tags),
            ]
        )

        if "error" in result:
            raise RuntimeError(f"Engram store failed: {result['error']}")

        return entry.id

    async def recall(
        self,
        query: str,
        project: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 10,
        min_confidence: float = 0.0,
    ) -> list[MemorySearchResult]:
        """Search memory via engram_recall.

        Engram-rs uses SQLite FTS5 for full-text search across stored memories.
        """
        args = [
            "recall",
            "--db", self.db_path,
            "--query", query,
            "--limit", str(limit),
        ]

        if project:
            args += ["--project", project]
        if category:
            args += ["--category", category]

        result = self._run_engram(args)

        if "error" in result:
            raise RuntimeError(f"Engram recall failed: {result['error']}")

        results = []
        for item in result.get("results", []):
            try:
                entry_data = json.loads(item.get("data", "{}"))
            except (json.JSONDecodeError, TypeError):
                continue
            entry = MemoryEntry(
                id=item.get("id", ""),
                content=entry_data.get("content", item.get("content", "")),
                category=entry_data.get("category", item.get("category", "fact")),
                project=entry_data.get("project", item.get("project", "")),
                tags=entry_data.get("tags", []),
                confidence=entry_data.get("confidence", 1.0),
                metadata=entry_data.get("metadata", {}),
            )
            if entry.confidence >= min_confidence:
                results.append(
                    MemorySearchResult(
                        entry=entry,
                        score=item.get("score", 0.0),
                        search_method="fts5",
                    )
                )

        return results

    async def forget(self, entry_id: str) -> bool:
        """Remove a memory entry from Engram-rs."""
        result = self._run_engram(
            ["delete", "--db", self.db_path, "--id", entry_id]
        )
        return "error" not in result

    async def reflect(self, project: Optional[str] = None) -> list[dict]:
        """Cross-reference memories to find patterns.

        Uses Engram-rs SQL queries to analyze stored memories.
        """
        args = ["reflect", "--db", self.db_path]
        if project:
            args += ["--project", project]

        result = self._run_engram(args)

        if "error" in result:
            return [
                {
                    "type": "insight",
                    "summary": "Engram-rs reflect operation (SQL-backed analysis)",
                    "note": "Install engram >= 0.2.0 for reflect support. "
                    "Current: FTS5 search + metadata filtering available.",
                }
            ]

        return result.get("insights", [])

    async def health_check(self) -> dict:
        """Verify Engram-rs connection and database health."""
        result = self._run_engram(["health", "--db", self.db_path])

        if "error" in result:
            return {
                "status": "error",
                "backend": "engram-rs",
                "db_path": self.db_path,
                "error": result["error"],
            }

        return {
            "status": "ok",
            "backend": "engram-rs",
            "db_path": self.db_path,
            "entry_count": result.get("entry_count", 0),
            "db_size_bytes": result.get("db_size_bytes", 0),
        }
