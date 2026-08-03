# Perseus Agent Core

Shared memory and tool layer for Perseus agents.

## Structure
- `perseus_agent_core/memory/` — memory backend interface and implementations
- `perseus_agent_core/tools/` — decision log, knowledge graph, project context

## Memory Backend
The canonical backend is Perseus Vault. Use `VaultMemoryBackend` with an
explicitly configured Vault client. Elastic and Engram/Mimir implementations
are legacy compatibility paths only; do not select them for new product work.
