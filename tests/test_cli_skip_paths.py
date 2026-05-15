"""Regression tests for the blob-hash and source-hash skip paths in _run_pipeline.

Verifies that skipping regeneration never writes to disk — a write on a skip
path causes pre-commit hooks to report "files were modified by this hook"
spuriously, even when no generated Python actually changed.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from convex_to_pydantic.cli import _run_pipeline
from convex_to_pydantic.hasher import blob_hash, write_stored_hashes

FIXTURES = Path(__file__).parent / "fixtures"


def _setup_output_dir(tmp_path: Path, fixture: str = "chat_app.json") -> tuple[Path, Path]:
    """Run one full pipeline pass so output_dir has generated files + stored hashes.

    Returns (input_json_path, output_dir).
    """
    input_json = FIXTURES / fixture
    output_dir = tmp_path / "output"
    _run_pipeline(None, input_json, output_dir)
    return input_json, output_dir


class TestBlobHashSkipDoesNotWriteDisk:
    """The blob-hash skip path must not modify any file on disk."""

    def test_no_hash_file_write_when_schema_unchanged(self, tmp_path: Path):
        """blob-hash skip: hash file must NOT be updated even when source hash
        differs from what's stored (pre-existing source-hash mismatch is the
        exact trigger condition for the spurious pre-commit failure)."""
        input_json, output_dir = _setup_output_dir(tmp_path)

        hash_file = output_dir / ".convex_codegen_hash"
        assert hash_file.exists(), "hash file should exist after first run"

        # Simulate source files having changed (different source hash stored)
        # while blob hash stays the same, by writing a stale source hash.
        blob = json.loads(input_json.read_text())
        current_blob_hash = blob_hash(blob)
        write_stored_hashes(output_dir, "stale_source_hash_abc123", current_blob_hash)

        mtime_before = hash_file.stat().st_mtime

        result = _run_pipeline(None, input_json, output_dir)

        assert result.skipped_at == "blob_hash"
        assert not result.regenerated
        assert hash_file.stat().st_mtime == mtime_before, (
            "Hash file was written on the blob-hash skip path — "
            "this causes spurious pre-commit hook failures."
        )

    def test_generated_files_not_written_on_blob_hash_skip(self, tmp_path: Path):
        """blob-hash skip: _types.py and _client.py must not be touched."""
        input_json, output_dir = _setup_output_dir(tmp_path)

        types_mtime = (output_dir / "_types.py").stat().st_mtime
        client_mtime = (output_dir / "_client.py").stat().st_mtime

        result = _run_pipeline(None, input_json, output_dir)

        assert result.skipped_at in ("source_hash", "blob_hash")
        assert (output_dir / "_types.py").stat().st_mtime == types_mtime
        assert (output_dir / "_client.py").stat().st_mtime == client_mtime


class TestSourceHashSkipDoesNotWriteDisk:
    """The source-hash skip path (Layer 1) must also not modify any file."""

    def test_no_writes_when_source_hash_matches(self, tmp_path: Path):
        input_json, output_dir = _setup_output_dir(tmp_path)

        hash_file = output_dir / ".convex_codegen_hash"
        types_path = output_dir / "_types.py"

        hash_mtime = hash_file.stat().st_mtime
        types_mtime = types_path.stat().st_mtime

        # Second run with --input (no convex_dir) hits blob_hash skip, not
        # source_hash — to hit source_hash we'd need a real convex_dir.
        # This test confirms the generated files are untouched on any skip.
        result = _run_pipeline(None, input_json, output_dir)

        assert not result.regenerated
        assert types_path.stat().st_mtime == types_mtime
        assert hash_file.stat().st_mtime == hash_mtime
