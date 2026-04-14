"""Pure transformation pipeline: blob → generated file contents.

This is the core of the package — a single pure function with no IO.
All side effects (file reads, subprocess calls, file writes) live in
cli.py and __init__.py at the edges.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .codegen.client_file import generate_client_file
from .codegen.tree import generate_module_file, generate_tables_file, generate_barrel
from .codegen.types_file import _collect_str_enums, generate_types_file
from .converter import parse_export
from .namer import NameRegistry, assign_names
from .types import ConvexExport, FunctionSchema


@dataclass(frozen=True)
class GeneratedFiles:
    """The output of the pure pipeline — just strings, no IO."""

    types_content: str
    client_content: str
    num_tables: int
    num_functions: int
    # Tree mode: relative path → content (e.g. {"chat/messages.py": "...", "__init__.py": "..."})
    tree_files: dict[str, str] = field(default_factory=dict)


def transform(
    blob: dict, *, output_mode: str = "single", client_style: str = "async"
) -> GeneratedFiles:
    """Pure pipeline: raw JSON dict → generated file contents.

    blob → parse (IR) → assign names → codegen → GeneratedFiles

    Args:
        blob: Raw Convex schema export as a dict.
        output_mode: "single" (default) emits one _types.py + _client.py; "tree"
            emits per-module files.
        client_style: "async" (default) emits `async def` wrappers using
            `await client.<method>(...)`; "sync" emits plain `def` wrappers
            that call the client synchronously.
    """
    if client_style not in ("async", "sync"):
        raise ValueError(f"Invalid client_style {client_style!r}; expected 'async' or 'sync'.")
    export = parse_export(blob)
    names = assign_names(export)
    if output_mode == "tree":
        return _generate_tree(export, names, client_style=client_style)
    return _generate(export, names, client_style=client_style)


def _generate(export: ConvexExport, names: NameRegistry, *, client_style: str) -> GeneratedFiles:
    enums = _collect_str_enums(export, names)
    return GeneratedFiles(
        types_content=generate_types_file(export, names, enums=enums),
        client_content=generate_client_file(export, names, enums=enums, client_style=client_style),
        num_tables=len(export.tables),
        num_functions=len(export.functions),
    )


def _generate_tree(
    export: ConvexExport, names: NameRegistry, *, client_style: str
) -> GeneratedFiles:
    """Generate per-module files mirroring the Convex directory structure."""
    enums = _collect_str_enums(export, names)
    tree_files: dict[str, str] = {}

    # Tables go into _tables.py
    if export.tables:
        tree_files["_tables.py"] = generate_tables_file(export, names, enums)

    # Group functions by module
    by_module: dict[str, list[FunctionSchema]] = defaultdict(list)
    for fn in export.functions:
        by_module[fn.module].append(fn)

    module_public_names: dict[str, list[str]] = {}
    for module, fns in sorted(by_module.items()):
        path = module.replace("/", "/") + ".py"
        content = generate_module_file(fns, names, enums, client_style=client_style)
        tree_files[path] = content
        # Collect public names for barrel
        fn_names_list = []
        for fn in fns:
            fn_ns = names.function_names(fn)
            fn_names_list.append(fn_ns.class_name)
            fn_names_list.append(fn_ns.fn_name)
            fn_names_list.append(fn_ns.fn_name + "_call")
        module_public_names[module] = fn_names_list

    # Barrel __init__.py
    tree_files["__init__.py"] = generate_barrel(
        has_tables=bool(export.tables),
        module_public_names=module_public_names,
    )

    return GeneratedFiles(
        types_content="",
        client_content="",
        num_tables=len(export.tables),
        num_functions=len(export.functions),
        tree_files=tree_files,
    )
