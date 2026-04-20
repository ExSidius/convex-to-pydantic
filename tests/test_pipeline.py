"""Tests for pipeline.py — the pure transformation core."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from convex_to_pydantic.pipeline import GeneratedFiles, transform

FIXTURES = Path(__file__).parent / "fixtures"


class TestTransform:
    def test_returns_generated_files(self):
        blob = json.loads((FIXTURES / "chat_app.json").read_text())
        result = transform(blob)
        assert isinstance(result, GeneratedFiles)

    def test_counts(self):
        blob = json.loads((FIXTURES / "chat_app.json").read_text())
        result = transform(blob)
        assert result.num_tables == 1
        assert result.num_functions == 2

    def test_kitchen_sink_counts(self):
        blob = json.loads((FIXTURES / "kitchen_sink.json").read_text())
        result = transform(blob)
        assert result.num_tables == 1
        assert result.num_functions == 3

    def test_pure_no_side_effects(self):
        """Calling transform twice with same input gives identical output."""
        blob = json.loads((FIXTURES / "kitchen_sink.json").read_text())
        r1 = transform(blob)
        r2 = transform(blob)
        assert r1 == r2

    def test_empty_export(self):
        result = transform({"tables": [], "functions": []})
        assert isinstance(result, GeneratedFiles)
        assert result.num_tables == 0
        assert result.num_functions == 0
        # Should still produce valid Python
        compile(result.types_content, "_types.py", "exec")
        compile(result.client_content, "_client.py", "exec")

    def test_types_content_is_string(self):
        blob = json.loads((FIXTURES / "chat_app.json").read_text())
        result = transform(blob)
        assert isinstance(result.types_content, str)
        assert isinstance(result.client_content, str)

    def test_result_is_frozen(self):
        blob = json.loads((FIXTURES / "chat_app.json").read_text())
        result = transform(blob)
        try:
            result.types_content = "modified"  # type: ignore
            assert False, "Should have raised"
        except AttributeError:
            pass


class TestClientStyle:
    def test_default_is_async(self):
        blob = json.loads((FIXTURES / "chat_app.json").read_text())
        result = transform(blob)
        assert "async def messages_send_mutation_call(" in result.client_content
        assert "await client.mutation(" in result.client_content

    def test_sync_strips_async_and_await(self):
        blob = json.loads((FIXTURES / "chat_app.json").read_text())
        result = transform(blob, client_style="sync")
        client = result.client_content
        assert "def messages_send_mutation_call(" in client
        assert "async def" not in client
        assert "await " not in client
        assert "return client.mutation(" in client

    def test_sync_output_compiles(self):
        for fixture in FIXTURES.glob("*.json"):
            blob = json.loads(fixture.read_text())
            result = transform(blob, client_style="sync")
            compile(result.client_content, f"{fixture.stem}/_client.py", "exec")

    def test_sync_deterministic(self):
        blob = json.loads((FIXTURES / "kitchen_sink.json").read_text())
        r1 = transform(blob, client_style="sync")
        r2 = transform(blob, client_style="sync")
        assert r1 == r2

    def test_types_unchanged_across_styles(self):
        """Only _client.py should differ between async/sync."""
        blob = json.loads((FIXTURES / "chat_app.json").read_text())
        async_result = transform(blob, client_style="async")
        sync_result = transform(blob, client_style="sync")
        assert async_result.types_content == sync_result.types_content
        assert async_result.client_content != sync_result.client_content

    def test_invalid_client_style_raises(self):
        with pytest.raises(ValueError, match="client_style"):
            transform({"tables": [], "functions": []}, client_style="threaded")

    def test_sync_tree_mode(self):
        blob = json.loads((FIXTURES / "chat_app.json").read_text())
        result = transform(blob, output_mode="tree", client_style="sync")
        module = result.tree_files["messages.py"]
        assert "def messages_send_mutation_call(" in module
        assert "async def" not in module
        assert "await " not in module
        assert "return client.mutation(" in module
