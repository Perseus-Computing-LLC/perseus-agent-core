import pytest

from perseus_agent_core.memory import (
    CANONICAL_BACKEND,
    LEGACY_BACKENDS,
    MemoryBackendError,
    MemoryEntry,
    VaultMemoryBackend,
)


class FakeVaultClient:
    def __init__(self):
        self.records = {}

    def remember(self, category, key=None, body=None, **extra):
        self.records[(extra.get("workspace_hash"), category, key)] = dict(body or {})
        return {"key": key}

    def recall(self, query, *, category=None, limit=10, mode="hybrid", **extra):
        workspace = extra.get("workspace_hash")
        items = []
        for (scope, stored_category, key), body in self.records.items():
            if scope != workspace or (category and category != stored_category):
                continue
            if query.lower() not in body.get("content", "").lower():
                continue
            items.append(
                {
                    "id": key,
                    "text": body.get("content", ""),
                    "score": 1.0,
                    "raw": {
                        "category": stored_category,
                        "key": key,
                        "body_json": body,
                    },
                }
            )
        return items[:limit]

    def forget(self, category, key, *, reason=None):
        matches = [identity for identity in self.records if identity[1:] == (category, key)]
        for identity in matches:
            del self.records[identity]
        return bool(matches) or key == "known"

    def health(self):
        return {"status": "healthy"}

    def context(self, query=None, **extra):
        return "bounded context" if query else ""


@pytest.mark.asyncio
async def test_vault_adapter_matches_official_client_shape_and_scope():
    client = FakeVaultClient()
    backend = VaultMemoryBackend(client)
    entry = MemoryEntry(
        content="SQLite + FTS5",
        category="decision",
        project="workspace-a",
        id="use-sqlite",
        metadata={"source": "test"},
    )
    first = await backend.remember(entry)
    second = await backend.remember(entry)
    assert first == second == "decision:use-sqlite"
    assert len(client.records) == 1
    assert (await backend.recall("SQLite", project="workspace-a"))[0].entry.content == "SQLite + FTS5"
    assert await backend.recall("SQLite", project="workspace-b") == []
    assert await backend.forget(first) is True
    assert (await backend.health_check())["backend"] == CANONICAL_BACKEND


@pytest.mark.asyncio
async def test_vault_adapter_reflects_bounded_context():
    backend = VaultMemoryBackend(FakeVaultClient())
    assert await backend.reflect("workspace-a") == [
        {"backend": "perseus-vault", "project": "workspace-a", "context": "bounded context"}
    ]


@pytest.mark.asyncio
async def test_backend_failure_is_distinct_and_sanitized():
    class BrokenClient(FakeVaultClient):
        def health(self):
            raise TimeoutError("secret db path must not escape")

    with pytest.raises(MemoryBackendError, match="perseus-vault health failed: TimeoutError"):
        await VaultMemoryBackend(BrokenClient()).health_check()


def test_legacy_backends_are_explicitly_noncanonical():
    assert CANONICAL_BACKEND == "perseus-vault"
    assert LEGACY_BACKENDS == ("elastic",)
