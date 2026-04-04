"""Subprocess wrapper for the bundled Node.js schema extractor."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


class ExtractionError(Exception):
    """Raised when the Node.js extractor fails."""


def _check_node() -> str:
    """Verify Node.js >=18 is on PATH. Returns the node binary path."""
    node = shutil.which("node")
    if node is None:
        raise RuntimeError(
            "convex-to-pydantic requires Node.js ≥18 on PATH.\n"
            "Install from https://nodejs.org or via your package manager.\n"
            "  macOS:  brew install node\n"
            "  Linux:  https://nodejs.org/en/download/package-manager\n"
            "  Windows: https://nodejs.org/en/download"
        )
    out = subprocess.check_output([node, "--version"], text=True).strip()
    major = int(out.lstrip("v").split(".")[0])
    if major < 18:
        raise RuntimeError(
            f"convex-to-pydantic requires Node.js ≥18, found {out}.\n"
            "Please upgrade: https://nodejs.org"
        )
    return node


def extract(convex_dir: Path) -> dict:
    """Run bundled schema_export.mjs, return parsed JSON."""
    node = _check_node()
    script = Path(__file__).parent / "schema_export.mjs"

    if not script.exists():
        raise ExtractionError(f"Bundled extractor not found at {script}")

    result = subprocess.run(
        [node, str(script), "--convex-dir", str(convex_dir)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ExtractionError(
            f"Node.js extractor failed (exit {result.returncode}):\n{result.stderr}"
        )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise ExtractionError(
            f"Invalid JSON from extractor: {e}\nOutput: {result.stdout[:500]}"
        ) from e


def extract_from_json(path: Path) -> dict:
    """Load a pre-exported JSON file (for testing or offline use)."""
    return json.loads(path.read_text())
