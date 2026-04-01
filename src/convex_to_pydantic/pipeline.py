"""Pure transformation pipeline: blob → generated file contents.

This is the core of the package — a single pure function with no IO.
All side effects (file reads, subprocess calls, file writes) live in
cli.py and __init__.py at the edges.
"""

from __future__ import annotations

from dataclasses import dataclass

from .codegen.client_file import generate_client_file
from .codegen.types_file import generate_types_file
from .converter import parse_export
from .namer import NameRegistry, assign_names
from .types import ConvexExport


@dataclass(frozen=True)
class GeneratedFiles:
    """The output of the pure pipeline — just strings, no IO."""
    types_content: str
    client_content: str
    num_tables: int
    num_functions: int


def transform(blob: dict) -> GeneratedFiles:
    """Pure pipeline: raw JSON dict → generated file contents.

    blob → parse (IR) → assign names → codegen → GeneratedFiles
    """
    export = parse_export(blob)
    names = assign_names(export)
    return _generate(export, names)


def _generate(export: ConvexExport, names: NameRegistry) -> GeneratedFiles:
    return GeneratedFiles(
        types_content=generate_types_file(export, names),
        client_content=generate_client_file(export, names),
        num_tables=len(export.tables),
        num_functions=len(export.functions),
    )
