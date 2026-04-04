"""Generate per-module files for tree output mode.

Pure module — returns strings, no IO.
"""

from __future__ import annotations

from ..namer import NameRegistry, to_snake
from ..types import (
    ConvexExport,
    ConvexObject,
    FunctionSchema,
)
from .types_file import (
    _collect_objects_for_root,
    _render_constructor,
    _render_enum,
    _render_model,
    _render_type,
    _field_comment,
    _check_imports_for_objects,
)
from .client_file import _METHOD_MAP


def generate_tables_file(
    export: ConvexExport,
    names: NameRegistry,
    enums: dict[str, list[str]],
) -> str:
    """Generate _tables.py containing all table models + constructors."""
    sections: list[str] = []

    sections.append(
        '"""\nAuto-generated Convex table types.\nDO NOT EDIT. Regenerate with: convex-to-pydantic generate\n"""'
    )
    sections.append("from __future__ import annotations")
    sections.append("")

    # Collect all table objects
    seen: set[int] = set()
    table_groups = []
    all_objects = []
    for table in export.tables:
        objs = _collect_objects_for_root(table.document_type, seen)
        table_groups.append((table, objs))
        all_objects.extend(objs)

    # Imports
    needs_any, needs_literal = _check_imports_for_objects(all_objects)

    typing_imports = []
    if needs_any:
        typing_imports.append("Any")
    if needs_literal:
        typing_imports.append("Literal")
    if typing_imports:
        sections.append(f"from typing import {', '.join(sorted(typing_imports))}")

    # Check if enums are used in table fields
    table_enums = {
        k: v for k, v in enums.items() if _enum_used_in_objects(k, all_objects, names, enums)
    }
    if table_enums:
        sections.append("from enum import StrEnum")

    sections.append("")
    sections.append("from pydantic import BaseModel, ConfigDict, Field")
    sections.append("")

    # Enums used by tables
    if table_enums:
        sections.append("")
        for name, values in table_enums.items():
            sections.append(_render_enum(name, values))
            sections.append("")

    # Table groups
    for table, table_objects in table_groups:
        if table_objects:
            sections.append("")
            sections.append(f"# --- Table: {table.table_name} ---")
            sections.append("")
            for obj in table_objects:
                sections.append(_render_model(obj, names, enums))
                sections.append("")

            user_fields = tuple(
                f for f in table.document_type.fields if f.name not in ("_id", "_creationTime")
            )
            if user_fields:
                table_class = names.object_name(table.document_type)
                fn_name = to_snake(table.table_name) + "_table"
                sections.append(
                    _render_constructor(
                        fn_name,
                        table_class,
                        user_fields,
                        f"Construct a {table.table_name} document (without system fields).",
                        names,
                        enums,
                    )
                )
                sections.append("")

    return "\n".join(sections).rstrip() + "\n"


def generate_module_file(
    functions: list[FunctionSchema],
    names: NameRegistry,
    enums: dict[str, list[str]],
) -> str:
    """Generate a single module file with function arg models + constructors + client wrappers."""
    sections: list[str] = []
    module = functions[0].module

    sections.append(
        f'"""\nAuto-generated types and client for Convex module: {module}\nDO NOT EDIT. Regenerate with: convex-to-pydantic generate\n"""'
    )
    sections.append("from __future__ import annotations")
    sections.append("")
    sections.append("from typing import Any, TYPE_CHECKING")
    sections.append("")
    sections.append("if TYPE_CHECKING:")
    sections.append("    from convex import ConvexClient")
    sections.append("")

    # Collect all objects for these functions
    seen: set[int] = set()
    fn_groups = []
    all_objects = []
    for fn in functions:
        objs = _collect_objects_for_root(fn.args, seen)
        fn_groups.append((fn, objs))
        all_objects.extend(objs)

    # Imports
    needs_any, needs_literal = _check_imports_for_objects(all_objects)
    # We already import Any above
    typing_imports = []
    if needs_literal:
        typing_imports.append("Literal")
    if typing_imports:
        sections.append(f"from typing import {', '.join(sorted(typing_imports))}")

    fn_enums = {
        k: v for k, v in enums.items() if _enum_used_in_objects(k, all_objects, names, enums)
    }
    if fn_enums:
        sections.append("from enum import StrEnum")

    sections.append("")
    sections.append("from pydantic import BaseModel, ConfigDict, Field")
    sections.append("")

    # Enums
    if fn_enums:
        sections.append("")
        for name, values in fn_enums.items():
            sections.append(_render_enum(name, values))
            sections.append("")

    # Per-function: models + constructor + client wrapper
    for fn, fn_objects in fn_groups:
        fn_names = names.function_names(fn)
        method = _METHOD_MAP.get(fn.fn_type, "query")
        path = f"{fn.module}:{fn.name}"

        sections.append("")
        sections.append(f"# --- {fn.name} ({fn.fn_type}) ---")
        sections.append("")

        # Models
        for obj in fn_objects:
            sections.append(_render_model(obj, names, enums))
            sections.append("")

        # Constructor
        sections.append(
            _render_constructor(
                fn_names.fn_name,
                fn_names.class_name,
                fn.args.fields,
                f"Validate args for Convex {fn.fn_type} {fn.module}:{fn.name}.",
                names,
                enums,
            )
        )
        sections.append("")

        # Client wrapper
        lines = [f"async def {fn_names.fn_name}_call("]
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
            f'    return await client.{method}("{path}", args.model_dump(by_alias=True, exclude_none=True))'
        )
        sections.append("\n".join(lines))
        sections.append("")

    return "\n".join(sections).rstrip() + "\n"


def generate_barrel(
    *,
    has_tables: bool,
    module_public_names: dict[str, list[str]],
) -> str:
    """Generate __init__.py that re-exports all public names."""
    sections: list[str] = []
    sections.append(
        '"""\nAuto-generated Convex package.\nDO NOT EDIT. Regenerate with: convex-to-pydantic generate\n"""'
    )
    sections.append("")

    if has_tables:
        sections.append("from ._tables import *  # noqa: F401,F403")

    for module in sorted(module_public_names):
        py_module = module.replace("/", ".")
        sections.append(f"from .{py_module} import *  # noqa: F401,F403")

    sections.append("")
    return "\n".join(sections)


def _enum_used_in_objects(
    enum_name: str,
    objects: list[ConvexObject],
    names: NameRegistry,
    enums: dict[str, list[str]],
) -> bool:
    """Check if an enum is referenced by any of the given objects."""
    for obj in objects:
        parent = names.object_name(obj)
        for field in obj.fields:
            rendered = _render_type(field.field_type, names, parent, field.name, enums)
            if enum_name in rendered:
                return True
    return False
