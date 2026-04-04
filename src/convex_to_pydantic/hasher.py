"""Content-hash staleness detection for generated files.

Two layers of hashing:

1. **Source-file hash** — SHA-256 over the sorted contents of all .ts/.js/.mjs
   files in the convex directory. Computed *before* calling Node.js. If unchanged,
   we skip extraction entirely (the most expensive step).

2. **Blob hash** — SHA-256 over the canonical JSON extraction blob. Checked after
   extraction. If unchanged, we skip codegen + file writes.

Both hashes are stored in `.convex_codegen_hash` as two lines.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

HASH_FILE = ".convex_codegen_hash"

_SOURCE_EXTENSIONS = frozenset((".ts", ".tsx", ".js", ".jsx", ".mjs"))


# ---------------------------------------------------------------------------
# Pure hash functions (no IO — take data, return digests)
# ---------------------------------------------------------------------------


def blob_hash(blob: dict) -> str:
    """Compute a deterministic SHA-256 hex digest of the extraction blob."""
    canonical = json.dumps(blob, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def files_hash(file_contents: list[tuple[str, bytes]]) -> str:
    """Compute a SHA-256 digest over sorted (relative_path, content) pairs.

    The input is a list of (relative_path, raw_bytes) tuples — the caller
    is responsible for reading the files. This function is pure.
    """
    h = hashlib.sha256()
    for path, content in sorted(file_contents):
        h.update(path.encode())
        h.update(b"\x00")
        h.update(content)
        h.update(b"\x00")
    return h.hexdigest()


# ---------------------------------------------------------------------------
# IO functions — read/write the hash file (thin edge layer)
# ---------------------------------------------------------------------------


def read_stored_hashes(output_dir: Path) -> tuple[str | None, str | None]:
    """Read stored (source_hash, blob_hash) or (None, None) if missing."""
    path = output_dir / HASH_FILE
    try:
        lines = path.read_text().splitlines()
        source = lines[0] if len(lines) > 0 and lines[0] else None
        blob = lines[1] if len(lines) > 1 and lines[1] else None
        return source, blob
    except (FileNotFoundError, OSError):
        return None, None


def write_stored_hashes(output_dir: Path, source_digest: str, blob_digest: str) -> None:
    """Write both hashes to the output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / HASH_FILE).write_text(f"{source_digest}\n{blob_digest}\n")


def collect_source_files(convex_dir: Path) -> list[tuple[str, bytes]]:
    """Read all source files from a convex directory.

    This is the only IO in the hash pipeline — isolated for testability.
    Returns (relative_path, content) pairs.
    """
    results: list[tuple[str, bytes]] = []
    for f in convex_dir.rglob("*"):
        if f.is_file() and f.suffix in _SOURCE_EXTENSIONS:
            rel = str(f.relative_to(convex_dir))
            results.append((rel, f.read_bytes()))
    return results
