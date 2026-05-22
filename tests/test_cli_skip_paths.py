"""Regression tests for the blob-hash and source-hash skip paths in _run_pipeline.

Verifies that skipping regeneration never writes to disk — a write on a skip
path causes pre-commit hooks to report "files were modified by this hook"
spuriously, even when no generated Python actually changed.

Both skip paths are exercised against a real ``convex_dir`` (with
``extract`` monkeypatched so the suite does not require Node.js), so the
tests actually reach the code paths that previously refreshed the hash file.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from convex_to_pydantic import cli
from convex_to_pydantic.cli import _run_pipeline
from convex_to_pydantic.hasher import read_stored_hashes

FIXTURES = Path(__file__).parent / "fixtures"


def _make_convex_dir(tmp_path: Path, body: str = "// initial\n") -> Path:
    """Create a tiny ``convex_dir`` containing one .ts source file."""
    convex_dir = tmp_path / "convex"
    convex_dir.mkdir()
    (convex_dir / "schema.ts").write_text(body)
    return convex_dir


def _stub_extract(blob: dict, monkeypatch) -> None:
    """Patch ``cli.extract`` to return ``blob`` so tests don't need Node.js."""
    monkeypatch.setattr(cli, "extract", lambda _convex_dir: blob)


def _freeze_mtime(*paths: Path, ts: float = 1_000_000_000.0) -> None:
    """Pin atime/mtime so equality checks don't depend on filesystem resolution."""
    for p in paths:
        os.utime(p, (ts, ts))


class TestBlobHashSkipDoesNotWriteDisk:
    """The blob-hash skip path (Layer 2) must not modify any file on disk."""

    def test_no_hash_file_write_when_source_changed_but_schema_unchanged(
        self, tmp_path: Path, monkeypatch
    ):
        """The exact precondition that previously triggered the spurious write:
        Layer 1 sees a different source_digest (source files were edited) but
        Layer 2 sees an unchanged blob_hash (schema didn't actually change).
        Before the fix this branch called ``write_stored_hashes`` to refresh
        the stale source hash — that write is what caused pre-commit to
        report "files were modified by this hook"."""
        blob = json.loads((FIXTURES / "chat_app.json").read_text())
        _stub_extract(blob, monkeypatch)

        convex_dir = _make_convex_dir(tmp_path, body="// initial\n")
        output_dir = tmp_path / "output"

        first = _run_pipeline(convex_dir, None, output_dir, do_format=False)
        assert first.regenerated, "initial run should populate the cache"

        hash_file = output_dir / ".convex_codegen_hash"
        stored_source_before, stored_blob_before = read_stored_hashes(output_dir)
        assert stored_source_before and stored_blob_before

        # Mutate the source file: source hash now differs from stored, but the
        # stubbed extract still returns the same blob, so Layer 2 will hit.
        (convex_dir / "schema.ts").write_text("// initial\n// later comment\n")

        _freeze_mtime(hash_file)
        mtime_before = hash_file.stat().st_mtime

        second = _run_pipeline(convex_dir, None, output_dir, do_format=False)

        assert second.skipped_at == "blob_hash", (
            f"expected Layer 2 (blob-hash) skip; got skipped_at={second.skipped_at!r}"
        )
        assert not second.regenerated
        assert hash_file.stat().st_mtime == mtime_before, (
            "Hash file was rewritten on the blob-hash skip path — "
            "this causes spurious pre-commit hook failures."
        )
        # Stored source must NOT have been refreshed to the new digest.
        stored_source_after, stored_blob_after = read_stored_hashes(output_dir)
        assert stored_source_after == stored_source_before
        assert stored_blob_after == stored_blob_before

    def test_generated_files_not_written_on_blob_hash_skip(
        self, tmp_path: Path, monkeypatch
    ):
        """``_types.py`` and ``_client.py`` must not be touched on a Layer 2 skip."""
        blob = json.loads((FIXTURES / "chat_app.json").read_text())
        _stub_extract(blob, monkeypatch)

        convex_dir = _make_convex_dir(tmp_path, body="// initial\n")
        output_dir = tmp_path / "output"

        _run_pipeline(convex_dir, None, output_dir, do_format=False)

        # Mutate the source so Layer 1 misses and we fall through to Layer 2.
        (convex_dir / "schema.ts").write_text("// initial\n// touch\n")

        types_path = output_dir / "_types.py"
        client_path = output_dir / "_client.py"
        _freeze_mtime(types_path, client_path)
        types_mtime = types_path.stat().st_mtime
        client_mtime = client_path.stat().st_mtime

        result = _run_pipeline(convex_dir, None, output_dir, do_format=False)

        assert result.skipped_at == "blob_hash"
        assert types_path.stat().st_mtime == types_mtime
        assert client_path.stat().st_mtime == client_mtime


class TestSourceHashSkipDoesNotWriteDisk:
    """The source-hash skip path (Layer 1) must also not modify any file."""

    def test_no_writes_when_source_hash_matches(self, tmp_path: Path, monkeypatch):
        """Layer 1 short-circuit: identical convex source files → return before
        ``extract`` runs and before anything is written."""
        blob = json.loads((FIXTURES / "chat_app.json").read_text())
        _stub_extract(blob, monkeypatch)

        convex_dir = _make_convex_dir(tmp_path)
        output_dir = tmp_path / "output"

        _run_pipeline(convex_dir, None, output_dir, do_format=False)

        hash_file = output_dir / ".convex_codegen_hash"
        types_path = output_dir / "_types.py"
        client_path = output_dir / "_client.py"
        _freeze_mtime(hash_file, types_path, client_path)
        hash_mtime = hash_file.stat().st_mtime
        types_mtime = types_path.stat().st_mtime
        client_mtime = client_path.stat().st_mtime

        result = _run_pipeline(convex_dir, None, output_dir, do_format=False)

        assert result.skipped_at == "source_hash"
        assert not result.regenerated
        assert hash_file.stat().st_mtime == hash_mtime
        assert types_path.stat().st_mtime == types_mtime
        assert client_path.stat().st_mtime == client_mtime
