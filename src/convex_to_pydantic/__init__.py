"""convex-to-pydantic: Pydantic codegen from Convex schemas."""

from __future__ import annotations

from pathlib import Path

from .extractor.runner import extract, extract_from_json
from .pipeline import GeneratedFiles, transform

__all__ = ["generate", "generate_from_json", "transform", "GeneratedFiles"]


def generate(convex_dir: Path, output_dir: Path, *, client_style: str = "async") -> None:
    """Extract Convex schema and generate typed Python files.

    Args:
        convex_dir: Path to the Convex directory (must contain _generated/api.js).
        output_dir: Directory to write _types.py and _client.py.
        client_style: "async" (default) emits ``async def`` wrappers; "sync"
            emits plain ``def`` wrappers for callers that can't use async.
    """
    blob = extract(convex_dir)
    generated = transform(blob, client_style=client_style)
    _write(output_dir, generated)


def generate_from_json(input_json: Path, output_dir: Path, *, client_style: str = "async") -> None:
    """Generate typed Python files from a pre-exported JSON file.

    Args:
        input_json: Path to the exported JSON file.
        output_dir: Directory to write _types.py and _client.py.
        client_style: "async" (default) emits ``async def`` wrappers; "sync"
            emits plain ``def`` wrappers for callers that can't use async.
    """
    blob = extract_from_json(input_json)
    generated = transform(blob, client_style=client_style)
    _write(output_dir, generated)


def _write(output_dir: Path, generated: GeneratedFiles) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "_types.py").write_text(generated.types_content)
    (output_dir / "_client.py").write_text(generated.client_content)
