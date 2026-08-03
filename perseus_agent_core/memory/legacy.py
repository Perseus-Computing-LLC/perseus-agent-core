"""Explicit historical compatibility namespace.

The current product boundary is Perseus Vault. The Elastic adapter remains
available only for consumers that intentionally import this historical module;
it is never re-exported from ``perseus_agent_core.memory``.
"""

from perseus_agent_core.memory.elastic_memory import ElasticMemoryBackend

__all__ = ["ElasticMemoryBackend"]

