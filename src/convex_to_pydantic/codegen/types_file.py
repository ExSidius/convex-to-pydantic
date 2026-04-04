"""Generate _types.py from the IR — Pydantic models + constructor functions.

Pure module — takes immutable IR + NameRegistry, returns a string.
No IO, no side effects.
"""

from __future__ import annotations

from ..namer import NameRegistry, to_pascal, to_snake
from ..types import (
    ConvexAny,
    ConvexArray,
    ConvexBoolean,
    ConvexBytes,
    ConvexExport,
    ConvexField,
    ConvexFloat64,
    ConvexId,
    ConvexInt64,
    ConvexLiteral,
    ConvexNull,
    ConvexObject,
    ConvexRecord,
    ConvexString,
    ConvexType,
    ConvexUnion,
    FunctionSchema,
    TableSchema,
)


# ---------------------------------------------------------------------------
# StrEnum detection
# ---------------------------------------------------------------------------


def _is_all_string_literal_union(t: ConvexType) -> bool:
    if not isinstance(t, ConvexUnion):
        return False
    if len(t.variants) < 2:
        return False
    return all(isinstance(v, ConvexLiteral) and isinstance(v.value, str) for v in t.variants)


def _collect_str_enums(export: ConvexExport, names: NameRegistry) -> dict[str, list[str]]:
    """Collect all all-string-literal unions, keyed by derived enum name.

    Returns enum class name → list of string values.
    """
    enums: dict[str, list[str]] = {}
    seen_value_sets: dict[tuple[str, ...], str] = {}

    def _walk_object(obj: ConvexObject) -> None:
        parent = names.object_name(obj)
        for field in obj.fields:
            _walk_field(parent, field.name, field.field_type)

    def _walk_field(parent_name: str, field_name: str, t: ConvexType) -> None:
        if _is_all_string_literal_union(t):
            assert isinstance(t, ConvexUnion)
            values = [v.value for v in t.variants if isinstance(v, ConvexLiteral)]
            key = tuple(values)
            if key in seen_value_sets:
                return
            enum_name = parent_name + to_pascal(field_name) + "Enum"
            seen_value_sets[key] = enum_name
            enums[enum_name] = list(values)
            return
        if isinstance(t, ConvexObject):
            _walk_object(t)
            return
        if isinstance(t, ConvexArray):
            _walk_field(parent_name, field_name + "Item", t.element)
            return
        if isinstance(t, ConvexUnion):
            for i, v in enumerate(t.variants):
                _walk_field(parent_name, f"{field_name}Variant{i}", v)
            return
        if isinstance(t, ConvexRecord):
            _walk_field(parent_name, field_name + "Value", t.values)

    for table in export.tables:
        _walk_object(table.document_type)
    for fn in export.functions:
        _walk_object(fn.args)

    return enums


# ---------------------------------------------------------------------------
# Type annotation rendering
# ---------------------------------------------------------------------------


def _enum_name_for_union(t: ConvexUnion, enums: dict[str, list[str]]) -> str | None:
    values = tuple(v.value for v in t.variants if isinstance(v, ConvexLiteral))
    for name, vals in enums.items():
        if tuple(vals) == values:
            return name
    return None


def _render_type(
    t: ConvexType,
    names: NameRegistry,
    parent_name: str = "",
    field_name: str = "",
    enums: dict[str, list[str]] | None = None,
) -> str:
    """Render a ConvexType as a Python type annotation string."""
    if isinstance(t, ConvexNull):
        return "None"
    if isinstance(t, ConvexBoolean):
        return "bool"
    if isinstance(t, ConvexFloat64):
        return "float"
    if isinstance(t, ConvexInt64):
        return "int"
    if isinstance(t, ConvexString):
        return "str"
    if isinstance(t, ConvexBytes):
        return "bytes"
    if isinstance(t, ConvexAny):
        return "Any"
    if isinstance(t, ConvexId):
        return "str"
    if isinstance(t, ConvexLiteral):
        return f"Literal[{t.value!r}]"
    if isinstance(t, ConvexArray):
        inner = _render_type(t.element, names, parent_name, field_name + "Item", enums)
        return f"list[{inner}]"
    if isinstance(t, ConvexRecord):
        k = _render_type(t.keys, names, parent_name, field_name + "Key", enums)
        v = _render_type(t.values, names, parent_name, field_name + "Value", enums)
        return f"dict[{k}, {v}]"
    if isinstance(t, ConvexUnion):
        if enums and _is_all_string_literal_union(t):
            enum_name = _enum_name_for_union(t, enums)
            if enum_name:
                return enum_name

        non_null = [v for v in t.variants if not isinstance(v, ConvexNull)]
        has_null = len(non_null) < len(t.variants)
        parts = [
            _render_type(v, names, parent_name, f"{field_name}Variant{i}", enums)
            for i, v in enumerate(t.variants)
            if not isinstance(v, ConvexNull)
        ]

        if has_null:
            if len(parts) == 1:
                return f"{parts[0]} | None"
            return " | ".join(parts) + " | None"
        return " | ".join(parts)
    if isinstance(t, ConvexObject):
        return names.object_name(t)
    raise ValueError(f"Unknown type: {t}")


def _field_comment(t: ConvexType) -> str:
    if isinstance(t, ConvexInt64):
        return "  # int64"
    if isinstance(t, ConvexId):
        return f"  # Id[{t.table_name}]"
    return ""


# ---------------------------------------------------------------------------
# Object collection (topological order)
# ---------------------------------------------------------------------------


def _collect_objects(
    export: ConvexExport,
) -> list[ConvexObject]:
    """Collect all ConvexObject nodes in dependency order (leaves first)."""
    seen: set[int] = set()
    objects: list[ConvexObject] = []

    for table in export.tables:
        objects.extend(_collect_objects_for_root(table.document_type, seen))
    for fn in export.functions:
        objects.extend(_collect_objects_for_root(fn.args, seen))

    return objects


def _collect_objects_for_root(
    root: ConvexObject,
    seen: set[int],
) -> list[ConvexObject]:
    """Collect ConvexObject nodes reachable from one root, in dependency order (leaves first).

    The shared ``seen`` set prevents emitting objects already claimed by an earlier root.
    """
    objects: list[ConvexObject] = []

    def _walk(t: ConvexType) -> None:
        if isinstance(t, ConvexArray):
            _walk(t.element)
            return
        if isinstance(t, ConvexUnion):
            for v in t.variants:
                _walk(v)
            return
        if isinstance(t, ConvexRecord):
            _walk(t.keys)
            _walk(t.values)
            return
        if not isinstance(t, ConvexObject):
            return
        if id(t) in seen:
            return
        seen.add(id(t))
        for f in t.fields:
            _walk(f.field_type)
        objects.append(t)

    _walk(root)
    return objects


# ---------------------------------------------------------------------------
# Code generation (all pure — returns strings)
# ---------------------------------------------------------------------------


def _check_imports_for_objects(objects: list[ConvexObject]) -> tuple[bool, bool]:
    """Return (needs_any, needs_literal) after scanning all objects."""
    needs_any = False
    needs_literal = False

    def _check(t: ConvexType) -> None:
        nonlocal needs_any, needs_literal
        if isinstance(t, ConvexAny):
            needs_any = True
        elif isinstance(t, ConvexLiteral):
            needs_literal = True
        elif isinstance(t, ConvexArray):
            _check(t.element)
        elif isinstance(t, ConvexRecord):
            _check(t.keys)
            _check(t.values)
        elif isinstance(t, ConvexUnion):
            if not _is_all_string_literal_union(t):
                for v in t.variants:
                    _check(v)
            else:
                for v in t.variants:
                    if isinstance(v, ConvexLiteral) and not isinstance(v.value, str):
                        needs_literal = True
                    elif not isinstance(v, ConvexLiteral):
                        _check(v)
        elif isinstance(t, ConvexObject):
            for f in t.fields:
                _check(f.field_type)

    for obj in objects:
        for f in obj.fields:
            _check(f.field_type)

    return needs_any, needs_literal


def _render_field_line(
    field: ConvexField,
    parent_name: str,
    names: NameRegistry,
    enums: dict[str, list[str]],
) -> str:
    py_name = to_snake(field.name)
    type_str = _render_type(field.field_type, names, parent_name, field.name, enums)
    comment = _field_comment(field.field_type)
    needs_alias = py_name != field.name

    if field.optional:
        type_str = f"{type_str} | None"

    if field.optional and needs_alias:
        return f"    {py_name}: {type_str} = Field(default=None, alias={field.name!r}){comment}"
    elif field.optional:
        return f"    {py_name}: {type_str} = None{comment}"
    elif needs_alias:
        return f"    {py_name}: {type_str} = Field(alias={field.name!r}){comment}"
    else:
        return f"    {py_name}: {type_str}{comment}"


def _render_model(
    obj: ConvexObject,
    names: NameRegistry,
    enums: dict[str, list[str]],
) -> str:
    class_name = names.object_name(obj)
    lines = [
        f"class {class_name}(BaseModel):",
        '    model_config = ConfigDict(extra="forbid", populate_by_name=True)',
    ]

    if not obj.fields:
        lines.append("    pass")
    else:
        required = [f for f in obj.fields if not f.optional]
        optional = [f for f in obj.fields if f.optional]
        for field in required + optional:
            lines.append(_render_field_line(field, class_name, names, enums))

    return "\n".join(lines)


def _render_constructor(
    fn_name: str,
    class_name: str,
    fields: tuple[ConvexField, ...],
    doc: str,
    names: NameRegistry,
    enums: dict[str, list[str]],
) -> str:
    lines = [f"def {fn_name}("]

    if not fields:
        lines[0] += f") -> {class_name}:"
    else:
        lines.append("    *,")
        required = [f for f in fields if not f.optional]
        optional = [f for f in fields if f.optional]
        for field in required + optional:
            py_name = to_snake(field.name)
            type_str = _render_type(field.field_type, names, class_name, field.name, enums)
            comment = _field_comment(field.field_type)
            if field.optional:
                type_str = f"{type_str} | None"
                lines.append(f"    {py_name}: {type_str} = None,{comment}")
            else:
                lines.append(f"    {py_name}: {type_str},{comment}")
        lines.append(f") -> {class_name}:")

    lines.append(f'    """{doc}"""')

    if not fields:
        lines.append(f"    return {class_name}()")
    else:
        args = ", ".join(f"{to_snake(f.name)}={to_snake(f.name)}" for f in fields)
        lines.append(f"    return {class_name}({args})")

    return "\n".join(lines)


def _render_enum(name: str, values: list[str]) -> str:
    lines = [f"class {name}(StrEnum):"]
    for v in values:
        member = v.upper().replace("-", "_").replace(" ", "_")
        lines.append(f'    {member} = "{v}"')
    return "\n".join(lines)


def generate_types_file(
    export: ConvexExport,
    names: NameRegistry,
    *,
    enums: dict[str, list[str]] | None = None,
) -> str:
    """Generate the full _types.py file content. Pure function.

    Output is grouped by entity: each table's models + constructor appear together,
    then each function's arg models + constructor.
    """
    if enums is None:
        enums = _collect_str_enums(export, names)

    # Collect all objects and check needed imports in one pass.
    needs_any = False
    needs_literal = False

    def _check_imports(t: ConvexType) -> None:
        nonlocal needs_any, needs_literal
        if isinstance(t, ConvexAny):
            needs_any = True
        elif isinstance(t, ConvexLiteral):
            needs_literal = True
        elif isinstance(t, ConvexArray):
            _check_imports(t.element)
        elif isinstance(t, ConvexRecord):
            _check_imports(t.keys)
            _check_imports(t.values)
        elif isinstance(t, ConvexUnion):
            if not _is_all_string_literal_union(t):
                for v in t.variants:
                    _check_imports(v)
            else:
                for v in t.variants:
                    if isinstance(v, ConvexLiteral) and not isinstance(v.value, str):
                        needs_literal = True
                    elif not isinstance(v, ConvexLiteral):
                        _check_imports(v)
        elif isinstance(t, ConvexObject):
            for f in t.fields:
                _check_imports(f.field_type)

    # Single walk: collect per-entity object groups AND scan imports.
    seen: set[int] = set()
    table_groups: list[tuple[TableSchema, list[ConvexObject]]] = []
    fn_groups: list[tuple[FunctionSchema, list[ConvexObject]]] = []

    for table in export.tables:
        objs = _collect_objects_for_root(table.document_type, seen)
        table_groups.append((table, objs))
        for obj in objs:
            for f in obj.fields:
                _check_imports(f.field_type)

    for fn in export.functions:
        objs = _collect_objects_for_root(fn.args, seen)
        fn_groups.append((fn, objs))
        for obj in objs:
            for f in obj.fields:
                _check_imports(f.field_type)

    # Build output
    sections: list[str] = []

    # Header
    sections.append(
        '"""\nAuto-generated Convex types.\nDO NOT EDIT. Regenerate with: convex-to-pydantic generate\n"""'
    )
    sections.append("from __future__ import annotations")
    sections.append("")

    typing_imports = []
    if needs_any:
        typing_imports.append("Any")
    if needs_literal:
        typing_imports.append("Literal")

    if typing_imports:
        sections.append(f"from typing import {', '.join(sorted(typing_imports))}")
    if enums:
        sections.append("from enum import StrEnum")

    sections.append("")
    sections.append("from pydantic import BaseModel, ConfigDict, Field")
    sections.append("")

    # StrEnums (global, deduplicated)
    if enums:
        sections.append("")
        sections.append("# --- Enums ---")
        sections.append("")
        for name, values in enums.items():
            sections.append(_render_enum(name, values))
            sections.append("")

    # Per-table groups: nested models + table model + constructor
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

    # Per-function groups: nested arg models + arg model + constructor
    for fn, fn_objects in fn_groups:
        fn_names = names.function_names(fn)
        sections.append("")
        sections.append(f"# --- Function: {fn.module}:{fn.name} ({fn.fn_type}) ---")
        sections.append("")
        for obj in fn_objects:
            sections.append(_render_model(obj, names, enums))
            sections.append("")
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

    return "\n".join(sections).rstrip() + "\n"
