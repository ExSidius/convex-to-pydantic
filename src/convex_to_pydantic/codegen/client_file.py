"""Generate _client.py from the IR — async client wrappers around ConvexClient.

Pure module — takes immutable IR + NameRegistry, returns a string.
No IO, no side effects.
"""

from __future__ import annotations

import re

from ..namer import NameRegistry, to_snake
from ..types import ConvexExport
from .types_file import _collect_str_enums, _field_comment, _render_type

_METHOD_MAP = {
    "query": "query",
    "mutation": "mutation",
    "action": "action",
}


def generate_client_file(export: ConvexExport, names: NameRegistry) -> str:
    """Generate the full _client.py file content. Pure function."""
    enums = _collect_str_enums(export, names)
    sections: list[str] = []

    # Header
    sections.append(
        '"""\nAuto-generated Convex client wrappers.\nDO NOT EDIT. Regenerate with: convex-to-pydantic generate\n"""'
    )
    sections.append("from __future__ import annotations")
    sections.append("")
    sections.append("from typing import Any, TYPE_CHECKING")
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
        for field in fn.args.fields:
            rendered = _render_type(field.field_type, names, fn_names.class_name, field.name, enums)
            for token in re.findall(r"\b[A-Z][A-Za-z0-9]+\b", rendered):
                if token not in ("Any", "None", "Literal", "Field", "BaseModel", "ConfigDict"):
                    type_imports.add(token)

    if type_imports:
        sections.append(f"from ._types import {', '.join(sorted(type_imports))}")
        sections.append("")

    # Wrapper functions
    for fn in export.functions:
        fn_names = names.function_names(fn)
        method = _METHOD_MAP.get(fn.fn_type, "query")
        path = f"{fn.module}:{fn.name}"

        lines = [f"async def {fn_names.fn_name}_call("]
        lines.append('    client: "ConvexClient",')

        if fn.args.fields:
            lines.append("    *,")
            required = [f for f in fn.args.fields if not f.optional]
            optional = [f for f in fn.args.fields if f.optional]
            for field in required + optional:
                py_name = to_snake(field.name)
                type_str = _render_type(field.field_type, names, fn_names.class_name, field.name, enums)
                comment = _field_comment(field.field_type)
                if field.optional:
                    type_str = f"{type_str} | None"
                    lines.append(f"    {py_name}: {type_str} = None,{comment}")
                else:
                    lines.append(f"    {py_name}: {type_str},{comment}")

        lines.append(") -> Any:")
        lines.append(f'    """Convex {fn.fn_type}: {path}"""')

        if fn.args.fields:
            arg_names = ", ".join(
                f"{to_snake(f.name)}={to_snake(f.name)}" for f in fn.args.fields
            )
            lines.append(f"    args = {fn_names.fn_name}({arg_names})")
        else:
            lines.append(f"    args = {fn_names.fn_name}()")

        lines.append(
            f'    return await client.{method}("{path}", args.model_dump(by_alias=True, exclude_none=True))'
        )

        sections.append("\n".join(lines))
        sections.append("")

    return "\n".join(sections).rstrip() + "\n"
