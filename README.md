# perseus-agent-core

Shared interface and tool layer for Perseus agents. The current product memory
boundary is Perseus Vault; this package also retains legacy adapters for older
consumers. Extracted from
[perseus-rapid-agent](https://github.com/Perseus-Computing-LLC/perseus-rapid-agent) and
[perseus-qwen-memory](https://github.com/Perseus-Computing-LLC/perseus-qwen-memory), which
previously carried copy-pasted copies of this code — the same `MemoryEntry`
crash shipped twice because of it. Fixes now land once, here.

## What's in it

- `perseus_agent_core.memory` — `MemoryEntry`, `MemorySearchResult`,
  `MemoryBackend` (interface), and `VaultMemoryBackend`, a transport-neutral
  adapter for an explicitly configured Perseus Vault client.
- `perseus_agent_core.memory.legacy` contains the isolated historical Elastic
  adapter. It is not re-exported by the current memory boundary and is not the
  canonical authority/evidence store.
- `perseus_agent_core.tools` — `DecisionLogTool`, `KnowledgeGraphTool`,
  `ProjectContextTool`.

Agent-specific code (`AgentConfig`, agent classes, LLM clients, demos) stays in
the consuming repos.

## Install

```bash
pip install "perseus-agent-core @ git+https://github.com/Perseus-Computing-LLC/perseus-agent-core.git"
# Historical Elastic compatibility only; new code should inject a Vault client into
# VaultMemoryBackend instead:
pip install "perseus-agent-core[elastic] @ git+https://github.com/Perseus-Computing-LLC/perseus-agent-core.git"
```

There are zero hard dependencies. The canonical adapter accepts a configured
Vault client so transport and authorization remain owned by the Vault package.

## Usage

```python
from perseus_agent_core.memory import MemoryEntry, VaultMemoryBackend
from perseus_agent_core.tools import DecisionLogTool

memory = VaultMemoryBackend(vault_client)
log = DecisionLogTool(memory)
```

Intentional historical Elastic consumers can import `ElasticMemoryBackend` from
`perseus_agent_core.memory.legacy`.
