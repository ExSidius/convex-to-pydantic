"""Tests for hasher.py — content-hash staleness detection."""

from __future__ import annotations

from pathlib import Path

from convex_to_pydantic.hasher import content_hash, read_hash, write_hash


class TestContentHash:
    def test_deterministic(self):
        blob = {"tables": [], "functions": [{"module": "a", "name": "b"}]}
        assert content_hash(blob) == content_hash(blob)

    def test_order_independent(self):
        blob1 = {"b": 2, "a": 1}
        blob2 = {"a": 1, "b": 2}
        assert content_hash(blob1) == content_hash(blob2)

    def test_different_content_different_hash(self):
        blob1 = {"tables": []}
        blob2 = {"tables": [{"tableName": "x"}]}
        assert content_hash(blob1) != content_hash(blob2)

    def test_hex_format(self):
        h = content_hash({})
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


class TestReadWriteHash:
    def test_roundtrip(self, tmp_path: Path):
        write_hash(tmp_path, "abc123")
        assert read_hash(tmp_path) == "abc123"

    def test_missing_returns_none(self, tmp_path: Path):
        assert read_hash(tmp_path) is None

    def test_creates_directory(self, tmp_path: Path):
        nested = tmp_path / "a" / "b"
        write_hash(nested, "xyz")
        assert read_hash(nested) == "xyz"
