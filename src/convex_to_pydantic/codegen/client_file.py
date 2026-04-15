"""Generate _client.py from the IR — client wrappers around ConvexClient.

Supports both async (``async def ... await client.query(...)``) and sync
(``def ... client.query(...)``) styles via the ``client_style`` argument.

Pure module — takes immutable IR + NameRegistry, returns a string.
No IO, no side effects.
"""

from __future__ import annotations

import re

from ..namer import NameRegistry, to_snake
from ..types import ConvexExport, ConvexObject
from .types_file import (
    _check_imports_for_objects,
    _collect_str_enums,
    _field_comment,
    _render_type,
)

_METHOD_MAP = {
    "query": "query",
    "mutation": "mutation",
    "action": "action",
}

_BUILTIN_NAMES = frozenset({"Any", "None", "Literal", "Field", "BaseModel", "ConfigDict"})
_PASCAL_RE = re.compile(r"\b[A-Z][A-Za-z0-9]+\b")


def _collect_type_refs(
    obj: ConvexObject,
    names: NameRegistry,
    parent_name: str,
    enums: dict[str, list[str]],
    out: set[str],
) -> None:
    """Collect PascalCase type references from an object's fields."""
    for field in obj.fields:
        rendered = _render_type(field.field_type, names, parent_name, field.name, enums)
        for token in _PASCAL_RE.findall(rendered):
            if token not in _BUILTIN_NAMES:
                out.add(token)


def generate_client_file(
    export: ConvexExport,
    names: NameRegistry,
    *,
    enums: dict[str, list[str]] | None = None,
    client_style: str = "async",
) -> str:
    """Generate the full _client.py file content. Pure function.

    Args:
        client_style: "async" (default) emits ``async def`` wrappers using
            ``await client.<method>(...)``; "sync" emits plain ``def``
            wrappers calling the client synchronously.
    """
    if client_style not in ("async", "sync"):
        raise ValueError(f"Invalid client_style {client_style!r}; expected 'async' or 'sync'.")
    if enums is None:
        enums = _collect_str_enums(export, names)
    is_async = client_style == "async"
    def_prefix = "async def " if is_async else "def "
    call_prefix = "await " if is_async else ""
    sections: list[str] = []

    # Header
    sections.append(
        '"""\nAuto-generated Convex client wrappers.\nDO NOT EDIT. Regenerate with: convex-to-pydantic generate\n"""'
    )
    sections.append("from __future__ import annotations")
    sections.append("")

    # `Any` is always needed (generated wrappers always return `-> Any`);
    # `TYPE_CHECKING` is always needed (guards the ConvexClient import).
    # `Literal` is only imported when a fn arg's rendered type emits it.
    _, needs_literal = _check_imports_for_objects([fn.args for fn in export.functions])
    typing_imports = ["Any", "TYPE_CHECKING"]
    if needs_literal:
        typing_imports.append("Literal")
    sections.append(f"from typing import {', '.join(sorted(typing_imports))}")
    sections.append("")
    sections.append("if TYPE_CHECKING:")
    sections.append("    from convex import ConvexClient")
    sections.append("")

    # Collect imports from _types
    type_imports: set[str] = set()
    for fn in export.functions:
        fn_names = names.function_names(fn)
        type_imports.add(fn_names.class_name)
        type_imports.add(fn_names.fn_name)
        _collect_type_refs(fn.args, names, fn_names.class_name, enums, type_imports)

    if type_imports:
        sections.append(f"from ._types import {', '.join(sorted(type_imports))}")
        sections.append("")

    # Wrapper functions
    for fn in export.functions:
        fn_names = names.function_names(fn)
        method = _METHOD_MAP.get(fn.fn_type, "query")
        path = f"{fn.module}:{fn.name}"

        lines = [f"{def_prefix}{fn_names.fn_name}_call("]
        lines.append('    client: "ConvexClient",')

        if fn.args.fields:
            lines.append("    *,")
            required = [f for f in fn.args.fields if not f.optional]
            optional = [f for f in fn.args.fields if f.optional]
            for field in required + optional:
                py_name = to_snake(field.name)
                type_str = _render_type(
                    field.field_type, names, fn_names.class_name, field.name, enums
                )
                comment = _field_comment(field.field_type)
                if field.optional:
                    type_str = f"{type_str} | None"
                    lines.append(f"    {py_name}: {type_str} = None,{comment}")
                else:
                    lines.append(f"    {py_name}: {type_str},{comment}")

        lines.append(") -> Any:")
        lines.append(f'    """Convex {fn.fn_type}: {path}"""')

        if fn.args.fields:
            arg_names = ", ".join(f"{to_snake(f.name)}={to_snake(f.name)}" for f in fn.args.fields)
            lines.append(f"    args = {fn_names.fn_name}({arg_names})")
        else:
            lines.append(f"    args = {fn_names.fn_name}()")

        lines.append(
            f'    return {call_prefix}client.{method}("{path}", args.model_dump(by_alias=True, exclude_none=True))'
        )

        sections.append("\n".join(lines))
        sections.append("")

    return "\n".join(sections).rstrip() + "\n"
