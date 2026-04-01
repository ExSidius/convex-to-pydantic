"""convex-to-pydantic: Pydantic codegen from Convex schemas."""

from __future__ import annotations

from pathlib import Path

from .codegen.client_file import generate_client_file
from .codegen.types_file import generate_types_file
from .converter import parse_export
from .extractor.runner import extract, extract_from_json
from .namer import assign_names

__all__ = ["generate", "generate_from_json"]


def generate(convex_dir: Path, output_dir: Path) -> None:
    """Extract Convex schema and generate typed Python files.

    Args:
        convex_dir: Path to the Convex directory (must contain _generated/api.js).
        output_dir: Directory to write _types.py and _client.py.
    """
    blob = extract(convex_dir)
    _generate_from_blob(blob, output_dir)


def generate_from_json(input_json: Path, output_dir: Path) -> None:
    """Generate typed Python files from a pre-exported JSON file.

    Args:
        input_json: Path to the exported JSON file.
        output_dir: Directory to write _types.py and _client.py.
    """
    blob = extract_from_json(input_json)
    _generate_from_blob(blob, output_dir)


def _generate_from_blob(blob: dict, output_dir: Path) -> None:
    export = parse_export(blob)
    assign_names(export)

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "_types.py").write_text(generate_types_file(export))
    (output_dir / "_client.py").write_text(generate_client_file(export))
