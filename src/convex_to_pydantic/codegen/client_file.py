"""Generate _client.py from the IR — client wrappers around ConvexClient.

Supports both async (``async def ... await client.query(...)``) and sync
(``def ... client.query(...)``) styles via the ``client_style`` argument.

Pure module — takes immutable IR + NameRegistry, returns a string.
No IO, no side effects.
"""

from __future__ import annotations

import re

from ..namer import NameRegistry, to_snake
from ..types import ConvexAny, ConvexExport, ConvexObject, ConvexType, FunctionSchema
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


def _collect_type_refs_in(
    t: ConvexType,
    names: NameRegistry,
    parent_name: str,
    enums: dict[str, list[str]],
    out: set[str],
) -> None:
    """Collect PascalCase type references from any rendered type."""
    rendered = _render_type(t, names, parent_name, "", enums)
    for token in _PASCAL_RE.findall(rendered):
        if token not in _BUILTIN_NAMES:
            out.add(token)


def _resolve_return(
    fn: FunctionSchema,
    names: NameRegistry,
    enums: dict[str, list[str]],
    return_type: str,
) -> tuple[str, str | None]:
    """Return ``(annotation, wrap_kind)`` for a function's return.

    ``wrap_kind`` is one of ``None`` (raw), ``"model_validate"``, ``"type_adapter"``,
    or ``"cast"`` — used by the caller to wrap the underlying ``client.<method>``
    call with the appropriate validation/cast expression.
    """
    if return_type == "any" or fn.returns is None or isinstance(fn.returns, ConvexAny):
        return "Any", None
    parent = names.function_names(fn).class_name
    if parent.endswith("Args"):
        parent = parent[: -len("Args")] + "Returns"
    ann = _render_type(fn.returns, names, parent, "", enums)
    if return_type == "typeddict":
        return ann, "cast"
    # pydantic
    if isinstance(fn.returns, ConvexObject):
        return ann, "model_validate"
    return ann, "type_adapter"


def generate_client_file(
    export: ConvexExport,
    names: NameRegistry,
    *,
    enums: dict[str, list[str]] | None = None,
    client_style: str = "async",
    return_type: str = "pydantic",
) -> str:
    """Generate the full _client.py file content. Pure function.

    Args:
        client_style: "async" (default) emits ``async def`` wrappers using
            ``await client.<method>(...)``; "sync" emits plain ``def``
            wrappers calling the client synchronously.
        return_type: "pydantic" (default) wraps Convex responses in
            ``Model.model_validate(...)`` (or ``TypeAdapter`` for non-object
            shapes); "typeddict" emits ``cast(<TypedDict>, ...)``; "any"
            leaves the response untouched and types it as ``Any``.
    """
    if client_style not in ("async", "sync"):
        raise ValueError(f"Invalid client_style {client_style!r}; expected 'async' or 'sync'.")
    if return_type not in ("pydantic", "typeddict", "any"):
        raise ValueError(
            f"Invalid return_type {return_type!r}; expected 'pydantic', 'typeddict', or 'any'."
        )
    if enums is None:
        enums = _collect_str_enums(export, names)
    is_async = client_style == "async"
    def_prefix = "async def " if is_async else "def "
    call_prefix = "await " if is_async else ""
    sections: list[str] = []

    # Resolve each function's return annotation + wrap kind up front so we
    # know which auxiliary imports (TypeAdapter, cast) we need.
    resolved: list[tuple[FunctionSchema, str, str | None]] = []
    for fn in export.functions:
        ann, wrap = _resolve_return(fn, names, enums, return_type)
        resolved.append((fn, ann, wrap))

    needs_type_adapter = any(wrap == "type_adapter" for _, _, wrap in resolved)
    needs_cast = any(wrap == "cast" for _, _, wrap in resolved)
    # `Any` is needed when at least one wrapper has no return annotation.
    needs_any_for_returns = any(wrap is None for _, _, wrap in resolved)

    # Header
    sections.append(
        '"""\nAuto-generated Convex client wrappers.\nDO NOT EDIT. Regenerate with: convex-to-pydantic generate\n"""'
    )
    sections.append("from __future__ import annotations")
    sections.append("")

    # `TYPE_CHECKING` is always needed (guards the ConvexClient import).
    # `Literal` is imported when any rendered arg/return type emits it.
    objs_for_imports: list[ConvexObject] = [fn.args for fn in export.functions]
    objs_for_imports += [
        fn.returns for fn in export.functions if isinstance(fn.returns, ConvexObject)
    ]
    _, needs_literal = _check_imports_for_objects(objs_for_imports)
    typing_imports = ["TYPE_CHECKING"]
    if needs_any_for_returns:
        typing_imports.append("Any")
    if needs_literal:
        typing_imports.append("Literal")
    if needs_cast:
        typing_imports.append("cast")
    sections.append(f"from typing import {', '.join(sorted(typing_imports))}")
    if needs_type_adapter:
        sections.append("from pydantic import TypeAdapter")
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
        if (
            return_type != "any"
            and fn.returns is not None
            and not isinstance(fn.returns, ConvexAny)
        ):
            parent = fn_names.class_name
            if parent.endswith("Args"):
                parent = parent[: -len("Args")] + "Returns"
            _collect_type_refs_in(fn.returns, names, parent, enums, type_imports)

    if type_imports:
        sections.append(f"from ._types import {', '.join(sorted(type_imports))}")
        sections.append("")

    # Wrapper functions
    for fn, return_ann, wrap_kind in resolved:
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

        lines.append(f") -> {return_ann}:")
        lines.append(f'    """Convex {fn.fn_type}: {path}"""')

        if fn.args.fields:
            arg_names = ", ".join(f"{to_snake(f.name)}={to_snake(f.name)}" for f in fn.args.fields)
            lines.append(f"    args = {fn_names.fn_name}({arg_names})")
        else:
            lines.append(f"    args = {fn_names.fn_name}()")

        call_expr = f'{call_prefix}client.{method}("{path}", args.model_dump(by_alias=True, exclude_none=True))'
        lines.append(f"    return {_wrap_call(call_expr, return_ann, wrap_kind)}")

        sections.append("\n".join(lines))
        sections.append("")

    return "\n".join(sections).rstrip() + "\n"


def _wrap_call(call_expr: str, return_ann: str, wrap_kind: str | None) -> str:
    """Wrap the client call expression based on the resolved validation strategy."""
    if wrap_kind is None:
        return call_expr
    if wrap_kind == "model_validate":
        return f"{return_ann}.model_validate({call_expr})"
    if wrap_kind == "type_adapter":
        return f"TypeAdapter({return_ann}).validate_python({call_expr})"
    if wrap_kind == "cast":
        return f"cast({return_ann}, {call_expr})"
    raise ValueError(f"Unknown wrap_kind: {wrap_kind!r}")
