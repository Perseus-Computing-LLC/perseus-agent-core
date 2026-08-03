"""Canonical and legacy-compatible memory backend boundaries.

``VaultMemoryBackend`` is the current product boundary. Elastic and Engram are
retained as explicitly legacy compatibility implementations for older agents;
they are not interchangeable authority or evidence stores.
"""

from perseus_agent_core.memory.backend import (
    MemoryBackend,
    MemoryBackendError,
    MemoryEntry,
    MemorySearchResult,
)
from perseus_agent_core.memory.elastic_memory import ElasticMemoryBackend
from perseus_agent_core.memory.engram_memory import EngramMemoryBackend, MimirMemoryBackend
from perseus_agent_core.memory.vault import VaultClient, VaultMemoryBackend

CANONICAL_BACKEND = "perseus-vault"
LEGACY_BACKENDS = ("elastic", "engram")

__all__ = [
    "MemoryBackend",
    "MemoryBackendError",
    "MemoryEntry",
    "MemorySearchResult",
    "ElasticMemoryBackend",
    "EngramMemoryBackend",
    "MimirMemoryBackend",
    "VaultClient",
    "VaultMemoryBackend",
    "CANONICAL_BACKEND",
    "LEGACY_BACKENDS",
]
