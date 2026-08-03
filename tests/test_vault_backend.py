import pytest

from perseus_agent_core.memory import (
    CANONICAL_BACKEND,
    LEGACY_BACKENDS,
    MemoryEntry,
    VaultMemoryBackend,
)


class FakeVaultClient:
    async def remember(self, entry):
        return f"vault:{entry.id or 'generated'}"

    async def recall(self, query, **kwargs):
        return []

    async def forget(self, entry_id):
        return entry_id == "known"

    async def reflect(self, project=None):
        return []

    async def health_check(self):
        return {"backend": "perseus-vault", "status": "healthy"}


@pytest.mark.asyncio
async def test_vault_adapter_delegates_to_canonical_client():
    backend = VaultMemoryBackend(FakeVaultClient())
    entry = MemoryEntry(content="decision", category="decision", project="demo", id="a1")
    assert await backend.remember(entry) == "vault:a1"
    assert await backend.recall("decision") == []
    assert await backend.forget("known") is True
    assert await backend.reflect("demo") == []
    assert (await backend.health_check())["backend"] == CANONICAL_BACKEND


def test_legacy_backends_are_explicitly_noncanonical():
    assert CANONICAL_BACKEND == "perseus-vault"
    assert LEGACY_BACKENDS == ("elastic", "engram")
