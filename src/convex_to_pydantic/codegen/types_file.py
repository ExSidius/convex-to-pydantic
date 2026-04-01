"""Generate _types.py from the IR — Pydantic models + constructor functions."""

from __future__ import annotations

from collections import defaultdict

from ..namer import to_snake
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
)


# ---------------------------------------------------------------------------
# StrEnum detection
# ---------------------------------------------------------------------------


def _is_all_string_literal_union(t: ConvexType) -> bool:
    """Check if a type is a union of all string literals."""
    if not isinstance(t, ConvexUnion):
        return False
    if len(t.variants) < 2:
        return False
    return all(isinstance(v, ConvexLiteral) and isinstance(v.value, str) for v in t.variants)


def _collect_str_enums(export: ConvexExport) -> dict[str, list[str]]:
    """Collect all all-string-literal unions and their values, keyed by class_name.

    Returns a dict mapping enum class name -> list of string values.
    We derive the enum name from the parent object's class_name + field name.
    """
    enums: dict[str, list[str]] = {}
    seen_value_sets: dict[tuple[str, ...], str] = {}

    def _walk_object(obj: ConvexObject) -> None:
        for field in obj.fields:
            _walk_field(obj.class_name, field.name, field.field_type)

    def _walk_field(parent_name: str, field_name: str, t: ConvexType) -> None:
        if _is_all_string_literal_union(t):
            assert isinstance(t, ConvexUnion)
            values = [v.value for v in t.variants if isinstance(v, ConvexLiteral)]
            key = tuple(values)
            if key not in seen_value_sets:
                enum_name = parent_name + _to_pascal_field(field_name) + "Enum"
                seen_value_sets[key] = enum_name
                enums[enum_name] = list(values)
        elif isinstance(t, ConvexObject):
            _walk_object(t)
        elif isinstance(t, ConvexArray):
            _walk_field(parent_name, field_name + "Item", t.element)
        elif isinstance(t, ConvexUnion):
            for i, v in enumerate(t.variants):
                _walk_field(parent_name, f"{field_name}Variant{i}", v)
        elif isinstance(t, ConvexRecord):
            _walk_field(parent_name, field_name + "Value", t.values)

    for table in export.tables:
        _walk_object(table.document_type)
    for fn in export.functions:
        _walk_object(fn.args)

    return enums


def _to_pascal_field(s: str) -> str:
    """Capitalize the first letter of a field name for enum naming."""
    from ..namer import to_pascal

    return to_pascal(s)


# ---------------------------------------------------------------------------
# Type annotation rendering
# ---------------------------------------------------------------------------


def _enum_name_for_union(parent_name: str, field_name: str, t: ConvexUnion, enums: dict[str, list[str]]) -> str | None:
    """If this union maps to a known StrEnum, return its name."""
    values = tuple(v.value for v in t.variants if isinstance(v, ConvexLiteral))
    for name, vals in enums.items():
        if tuple(vals) == values:
            return name
    return None


def _render_type(
    t: ConvexType,
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
        inner = _render_type(t.element, parent_name, field_name + "Item", enums)
        return f"list[{inner}]"
    if isinstance(t, ConvexRecord):
        k = _render_type(t.keys, parent_name, field_name + "Key", enums)
        v = _render_type(t.values, parent_name, field_name + "Value", enums)
        return f"dict[{k}, {v}]"
    if isinstance(t, ConvexUnion):
        # Check for StrEnum
        if enums and _is_all_string_literal_union(t):
            enum_name = _enum_name_for_union(parent_name, field_name, t, enums)
            if enum_name:
                return enum_name

        # Simplify T | null → T | None
        variants = t.variants
        non_null = [v for v in variants if not isinstance(v, ConvexNull)]
        has_null = len(non_null) < len(variants)

        parts = [_render_type(v, parent_name, f"{field_name}Variant{i}", enums) for i, v in enumerate(variants) if not isinstance(v, ConvexNull)]

        if has_null:
            if len(parts) == 1:
                return f"{parts[0]} | None"
            return " | ".join(parts) + " | None"
        return " | ".join(parts)
    if isinstance(t, ConvexObject):
        return t.class_name
    raise ValueError(f"Unknown type: {t}")


def _field_comment(t: ConvexType) -> str:
    """Return an inline comment for special types."""
    if isinstance(t, ConvexInt64):
        return "  # int64"
    if isinstance(t, ConvexId):
        return f"  # Id[{t.table_name}]"
    return ""


# ---------------------------------------------------------------------------
# Object collection + topological sort
# ---------------------------------------------------------------------------


def _collect_objects(export: ConvexExport) -> list[ConvexObject]:
    """Collect all ConvexObject nodes in the IR."""
    objects: list[ConvexObject] = []
    seen: set[str] = set()

    def _walk(t: ConvexType) -> None:
        if isinstance(t, ConvexObject):
            if t.class_name and t.class_name not in seen:
                seen.add(t.class_name)
                # Walk children first (for dependency ordering)
                for f in t.fields:
                    _walk(f.field_type)
                objects.append(t)
        elif isinstance(t, ConvexArray):
            _walk(t.element)
        elif isinstance(t, ConvexUnion):
            for v in t.variants:
                _walk(v)
        elif isinstance(t, ConvexRecord):
            _walk(t.keys)
            _walk(t.values)

    for table in export.tables:
        _walk(table.document_type)
    for fn in export.functions:
        _walk(fn.args)

    return objects


# ---------------------------------------------------------------------------
# Code generation
# ---------------------------------------------------------------------------


def _render_field_line(field: ConvexField, parent_name: str, enums: dict[str, list[str]]) -> str:
    """Render a single field as a Pydantic model field line."""
    py_name = to_snake(field.name)
    type_str = _render_type(field.field_type, parent_name, field.name, enums)
    comment = _field_comment(field.field_type)
    needs_alias = py_name != field.name

    if field.optional:
        type_str = f"{type_str} | None"

    parts: list[str] = []

    if field.optional and needs_alias:
        parts.append(f"    {py_name}: {type_str} = Field(default=None, alias={field.name!r}){comment}")
    elif field.optional:
        parts.append(f"    {py_name}: {type_str} = None{comment}")
    elif needs_alias:
        parts.append(f"    {py_name}: {type_str} = Field(alias={field.name!r}){comment}")
    else:
        parts.append(f"    {py_name}: {type_str}{comment}")

    return parts[0]


def _render_model(obj: ConvexObject, enums: dict[str, list[str]]) -> str:
    """Render a single Pydantic BaseModel class."""
    lines = [
        f"class {obj.class_name}(BaseModel):",
        '    model_config = ConfigDict(extra="forbid", populate_by_name=True)',
    ]

    if not obj.fields:
        lines.append("    pass")
    else:
        # Render required fields first, then optional
        required = [f for f in obj.fields if not f.optional]
        optional = [f for f in obj.fields if f.optional]
        for field in required + optional:
            lines.append(_render_field_line(field, obj.class_name, enums))

    return "\n".join(lines)


def _render_constructor(
    fn_name: str,
    class_name: str,
    obj: ConvexObject,
    doc: str,
    enums: dict[str, list[str]],
) -> str:
    """Render a keyword-arg constructor function."""
    lines = [f"def {fn_name}("]

    if not obj.fields:
        lines[0] += f") -> {class_name}:"
    else:
        lines.append("    *,")
        required = [f for f in obj.fields if not f.optional]
        optional = [f for f in obj.fields if f.optional]
        for field in required + optional:
            py_name = to_snake(field.name)
            type_str = _render_type(field.field_type, class_name, field.name, enums)
            comment = _field_comment(field.field_type)
            if field.optional:
                type_str = f"{type_str} | None"
                lines.append(f"    {py_name}: {type_str} = None,{comment}")
            else:
                lines.append(f"    {py_name}: {type_str},{comment}")
        lines.append(f") -> {class_name}:")

    lines.append(f'    """{doc}"""')

    if not obj.fields:
        lines.append(f"    return {class_name}()")
    else:
        args = ", ".join(f"{to_snake(f.name)}={to_snake(f.name)}" for f in obj.fields)
        lines.append(f"    return {class_name}({args})")

    return "\n".join(lines)


def _render_enum(name: str, values: list[str]) -> str:
    """Render a StrEnum class."""
    lines = [f"class {name}(StrEnum):"]
    for v in values:
        member = v.upper().replace("-", "_").replace(" ", "_")
        lines.append(f'    {member} = "{v}"')
    return "\n".join(lines)


def generate_types_file(export: ConvexExport) -> str:
    """Generate the full _types.py file content."""
    enums = _collect_str_enums(export)
    objects = _collect_objects(export)

    sections: list[str] = []

    # Header
    sections.append(
        '"""\nAuto-generated Convex types.\nDO NOT EDIT. Regenerate with: convex-to-pydantic generate\n"""'
    )
    sections.append("from __future__ import annotations")
    sections.append("")

    # Imports — collect what we need
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
            # Check if it's a StrEnum — if so, don't need Literal for it
            if not _is_all_string_literal_union(t):
                for v in t.variants:
                    _check_imports(v)
            else:
                # Still check non-literal variants (shouldn't exist, but safe)
                for v in t.variants:
                    if isinstance(v, ConvexLiteral) and not isinstance(v.value, str):
                        needs_literal = True
                    elif not isinstance(v, ConvexLiteral):
                        _check_imports(v)
        elif isinstance(t, ConvexObject):
            for f in t.fields:
                _check_imports(f.field_type)

    for obj in objects:
        for f in obj.fields:
            _check_imports(f.field_type)

    # Check if we need Literal for non-enum contexts too
    # (mixed literal unions that aren't all-string won't be enums)
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

    # Section 1: StrEnums
    if enums:
        sections.append("")
        sections.append("# --- Enums ---")
        sections.append("")
        for name, values in enums.items():
            sections.append(_render_enum(name, values))
            sections.append("")

    # Section 2: Models (already in topological order from _collect_objects)
    sections.append("")
    sections.append("# --- Models ---")
    sections.append("")
    for obj in objects:
        sections.append(_render_model(obj, enums))
        sections.append("")

    # Section 3: Table constructors
    has_table_constructors = any(
        # Non-system fields exist
        any(f.name not in ("_id", "_creationTime") for f in table.document_type.fields)
        for table in export.tables
    )
    has_fn_constructors = bool(export.functions)

    if has_table_constructors or has_fn_constructors:
        sections.append("")
        sections.append("# --- Constructors ---")
        sections.append("")

    for table in export.tables:
        # Constructor for table — only user fields (not _id, _creationTime)
        user_fields = [f for f in table.document_type.fields if f.name not in ("_id", "_creationTime")]
        if user_fields:
            user_obj = ConvexObject(fields=user_fields, class_name=table.document_type.class_name)
            fn_name = to_snake(table.table_name) + "_table"
            sections.append(
                _render_constructor(
                    fn_name,
                    table.document_type.class_name,
                    user_obj,
                    f"Construct a {table.table_name} document (without system fields).",
                    enums,
                )
            )
            sections.append("")

    # Section 4: Function constructors
    for fn in export.functions:
        sections.append(
            _render_constructor(
                fn.fn_name,
                fn.class_name,
                fn.args,
                f"Validate args for Convex {fn.fn_type} {fn.module}:{fn.name}.",
                enums,
            )
        )
        sections.append("")

    return "\n".join(sections).rstrip() + "\n"
