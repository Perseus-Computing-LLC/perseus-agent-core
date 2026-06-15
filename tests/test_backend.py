"""Tests for memory backend interface."""
import pytest
from perseus_agent_core.memory.backend import MemoryBackend, MemoryEntry, MemorySearchResult


class TestMemoryEntry:
    def test_create_minimal(self):
        entry = MemoryEntry(content="test", category="fact", project="test-proj")
        assert entry.content == "test"
        assert entry.category == "fact"
        assert entry.project == "test-proj"
        assert entry.id == ""
        assert entry.confidence == 1.0

    def test_create_full(self):
        entry = MemoryEntry(
            content="decided on postgres",
            category="decision",
            project="myapp",
            id="mem-001",
            tags=["database", "infra"],
            confidence=0.9,
        )
        assert entry.id == "mem-001"
        assert len(entry.tags) == 2
        assert entry.confidence == 0.9

    def test_default_tags(self):
        entry = MemoryEntry(content="x", category="fact", project="p")
        assert entry.tags == []


class TestMemorySearchResult:
    def test_create(self):
        entry = MemoryEntry(content="test", category="fact", project="p")
        result = MemorySearchResult(entry=entry, score=0.85, search_method="semantic")
        assert result.score == 0.85
        assert result.search_method == "semantic"
        assert result.entry.content == "test"
