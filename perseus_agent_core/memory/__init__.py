"""Canonical memory backend boundary.

``VaultMemoryBackend`` is the only current product boundary. The historical
Elastic adapter is isolated under :mod:`perseus_agent_core.memory.legacy` and
is never re-exported here.
"""

from perseus_agent_core.memory.backend import (
    MemoryBackend,
    MemoryBackendError,
    MemoryEntry,
    MemorySearchResult,
)
from perseus_agent_core.memory.vault import VaultClient, VaultMemoryBackend

CANONICAL_BACKEND = "perseus-vault"
LEGACY_BACKENDS = ("elastic",)

__all__ = [
    "MemoryBackend",
    "MemoryBackendError",
    "MemoryEntry",
    "MemorySearchResult",
    "VaultClient",
    "VaultMemoryBackend",
    "CANONICAL_BACKEND",
    "LEGACY_BACKENDS",
]
