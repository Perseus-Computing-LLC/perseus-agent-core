# Perseus Agent Core

Shared memory and tool layer for Perseus agents.

## Structure
- `perseus_agent_core/memory/` — memory backend interface and implementations
- `perseus_agent_core/tools/` — decision log, knowledge graph, project context

## Memory Backend
The canonical backend is Perseus Vault. Use `VaultMemoryBackend` with an
explicitly configured Vault client. Elastic is an isolated historical path;
do not select it for new product work.
