"""Tests for pipeline.py — the pure transformation core."""

from __future__ import annotations

import json
from pathlib import Path

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
            result.types_content = "modified"
            assert False, "Should have raised"
        except AttributeError:
            pass
