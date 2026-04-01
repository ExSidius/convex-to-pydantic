"""Tests for hasher.py — content-hash staleness detection."""

from __future__ import annotations

from pathlib import Path

from convex_to_pydantic.hasher import (
    blob_hash,
    collect_source_files,
    files_hash,
    read_stored_hashes,
    write_stored_hashes,
)


# ---------------------------------------------------------------------------
# Pure hash functions
# ---------------------------------------------------------------------------


class TestBlobHash:
    def test_deterministic(self):
        blob = {"tables": [], "functions": [{"module": "a", "name": "b"}]}
        assert blob_hash(blob) == blob_hash(blob)

    def test_order_independent(self):
        blob1 = {"b": 2, "a": 1}
        blob2 = {"a": 1, "b": 2}
        assert blob_hash(blob1) == blob_hash(blob2)

    def test_different_content_different_hash(self):
        blob1 = {"tables": []}
        blob2 = {"tables": [{"tableName": "x"}]}
        assert blob_hash(blob1) != blob_hash(blob2)

    def test_hex_format(self):
        h = blob_hash({})
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)


class TestFilesHash:
    def test_deterministic(self):
        files = [("a.ts", b"hello"), ("b.ts", b"world")]
        assert files_hash(files) == files_hash(files)

    def test_order_independent(self):
        files1 = [("b.ts", b"world"), ("a.ts", b"hello")]
        files2 = [("a.ts", b"hello"), ("b.ts", b"world")]
        assert files_hash(files1) == files_hash(files2)

    def test_different_content(self):
        f1 = [("a.ts", b"hello")]
        f2 = [("a.ts", b"world")]
        assert files_hash(f1) != files_hash(f2)

    def test_different_paths(self):
        f1 = [("a.ts", b"hello")]
        f2 = [("b.ts", b"hello")]
        assert files_hash(f1) != files_hash(f2)

    def test_empty(self):
        h = files_hash([])
        assert len(h) == 64


# ---------------------------------------------------------------------------
# IO functions (use tmp_path)
# ---------------------------------------------------------------------------


class TestStoredHashes:
    def test_roundtrip(self, tmp_path: Path):
        write_stored_hashes(tmp_path, "source123", "blob456")
        source, blob = read_stored_hashes(tmp_path)
        assert source == "source123"
        assert blob == "blob456"

    def test_missing_returns_none(self, tmp_path: Path):
        source, blob = read_stored_hashes(tmp_path)
        assert source is None
        assert blob is None

    def test_creates_directory(self, tmp_path: Path):
        nested = tmp_path / "a" / "b"
        write_stored_hashes(nested, "s", "b")
        assert read_stored_hashes(nested) == ("s", "b")


class TestCollectSourceFiles:
    def test_collects_ts_files(self, tmp_path: Path):
        (tmp_path / "schema.ts").write_bytes(b"hello")
        (tmp_path / "utils.js").write_bytes(b"world")
        (tmp_path / "readme.md").write_bytes(b"skip me")
        result = collect_source_files(tmp_path)
        paths = [p for p, _ in result]
        assert "schema.ts" in paths
        assert "utils.js" in paths
        assert "readme.md" not in paths

    def test_recursive(self, tmp_path: Path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "deep.ts").write_bytes(b"nested")
        result = collect_source_files(tmp_path)
        paths = [p for p, _ in result]
        assert any("deep.ts" in p for p in paths)
