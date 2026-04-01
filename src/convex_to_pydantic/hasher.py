"""Content-hash staleness detection for generated files.

Instead of a full merkle tree (overkill — the extraction output is a single
JSON blob, not a tree of independent files), we compute a SHA-256 digest of
the canonical JSON and store it in a small `.convex_codegen_hash` file next
to the generated output. On the next run we compare: if the hash matches,
the schema hasn't changed and we skip regeneration entirely.

This makes watch mode efficient: filesystem events fire frequently (editor
auto-save, `npx convex dev` writing intermediates), but the expensive
Node.js extraction + Python codegen only runs when the actual schema content
has changed.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

HASH_FILE = ".convex_codegen_hash"


def content_hash(blob: dict) -> str:
    """Compute a deterministic SHA-256 hex digest of the extraction blob."""
    # sort_keys + separators → canonical JSON regardless of dict ordering
    canonical = json.dumps(blob, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def read_hash(output_dir: Path) -> str | None:
    """Read the stored content hash, or None if missing/corrupt."""
    path = output_dir / HASH_FILE
    try:
        return path.read_text().strip()
    except (FileNotFoundError, OSError):
        return None


def write_hash(output_dir: Path, digest: str) -> None:
    """Write the content hash to the output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / HASH_FILE).write_text(digest + "\n")
