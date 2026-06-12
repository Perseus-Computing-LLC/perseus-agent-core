# perseus-agent-core

Shared memory and tool layer for Perseus agents. Extracted from
[perseus-rapid-agent](https://github.com/tcconnally/perseus-rapid-agent) and
[perseus-qwen-memory](https://github.com/tcconnally/perseus-qwen-memory), which
previously carried copy-pasted copies of this code — the same `MemoryEntry`
crash shipped twice because of it. Fixes now land once, here.

## What's in it

- `perseus_agent_core.memory` — `MemoryEntry`, `MemorySearchResult`,
  `MemoryBackend` (interface), `MemoryBackendError`, plus two implementations:
  - `ElasticMemoryBackend` — Elasticsearch via `elasticsearch-py`, keyword
    search always, ELSER semantic search when the deployment supports it.
  - `EngramMemoryBackend` — shells out to the [engram-rs](https://github.com/tcconnally/engram-rs)
    CLI; retry-on-lock, timeout handling, helpful install hint when missing.
- `perseus_agent_core.tools` — `DecisionLogTool`, `KnowledgeGraphTool`,
  `ProjectContextTool`.

Agent-specific code (`AgentConfig`, agent classes, LLM clients, demos) stays in
the consuming repos.

## Install

```bash
pip install "perseus-agent-core @ git+https://github.com/tcconnally/perseus-agent-core.git"
# with the Elasticsearch backend:
pip install "perseus-agent-core[elastic] @ git+https://github.com/tcconnally/perseus-agent-core.git"
```

There are zero hard dependencies — the elastic client is imported lazily only
when `ElasticMemoryBackend` is used.

## Usage

```python
from perseus_agent_core.memory import EngramMemoryBackend, MemoryEntry
from perseus_agent_core.tools import DecisionLogTool

memory = EngramMemoryBackend()
log = DecisionLogTool(memory)
```
