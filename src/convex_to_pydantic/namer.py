"""Collision-free PascalCase naming for all generated classes and functions."""

from __future__ import annotations

import keyword
import re

from .types import (
    ConvexArray,
    ConvexExport,
    ConvexObject,
    ConvexRecord,
    ConvexType,
    ConvexUnion,
)


def to_pascal(s: str) -> str:
    """Convert a string to PascalCase."""
    # Split on underscores, hyphens, dots, colons, and camelCase boundaries
    parts = re.sub(r"([a-z])([A-Z])", r"\1_\2", s)
    parts = re.split(r"[_\-.:]+", parts)
    return "".join(p.capitalize() for p in parts if p)


def to_snake(s: str) -> str:
    """Convert a string to snake_case."""
    # Strip leading underscores (system fields like _id, _creationTime)
    stripped = s.lstrip("_")

    # Handle camelCase boundaries
    stripped = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", stripped)
    stripped = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", stripped)
    result = re.sub(r"[_\-.:]+", "_", stripped).lower()

    if keyword.iskeyword(result) or result in ("id", "type"):
        result = result + "_"
    return result


class Namer:
    def __init__(self) -> None:
        self._used: set[str] = set()

    def assign(self, preferred: str) -> str:
        """Return preferred name if free, else append 2, 3, ..."""
        if preferred not in self._used:
            self._used.add(preferred)
            return preferred
        i = 2
        while f"{preferred}{i}" in self._used:
            i += 1
        name = f"{preferred}{i}"
        self._used.add(name)
        return name

    def name_table(self, table_name: str) -> str:
        return self.assign(to_pascal(table_name) + "Table")

    def name_function_args(self, module: str, fn_name: str, fn_type: str) -> str:
        return self.assign(
            to_pascal(module) + to_pascal(fn_name) + to_pascal(fn_type) + "Args"
        )

    def name_function(self, module: str, fn_name: str, fn_type: str) -> str:
        return to_snake(module) + "_" + to_snake(fn_name) + "_" + to_snake(fn_type)

    def name_nested_object(self, parent_name: str, field_name: str) -> str:
        return self.assign(parent_name + to_pascal(field_name))


def _walk_and_name_type(namer: Namer, parent_name: str, field_name: str, t: ConvexType) -> None:
    """Recursively walk a type tree, naming any ConvexObject nodes."""
    if isinstance(t, ConvexObject):
        if not t.class_name:
            t.class_name = namer.name_nested_object(parent_name, field_name)
        for f in t.fields:
            _walk_and_name_type(namer, t.class_name, f.name, f.field_type)
    elif isinstance(t, ConvexArray):
        _walk_and_name_type(namer, parent_name, field_name + "Item", t.element)
    elif isinstance(t, ConvexUnion):
        for i, v in enumerate(t.variants):
            _walk_and_name_type(namer, parent_name, f"{field_name}Variant{i}", v)
    elif isinstance(t, ConvexRecord):
        _walk_and_name_type(namer, parent_name, field_name + "Key", t.keys)
        _walk_and_name_type(namer, parent_name, field_name + "Value", t.values)


def assign_names(export: ConvexExport) -> None:
    """Walk the entire IR and assign class_name to every ConvexObject."""
    namer = Namer()

    for table in export.tables:
        table.document_type.class_name = namer.name_table(table.table_name)
        for f in table.document_type.fields:
            _walk_and_name_type(namer, table.document_type.class_name, f.name, f.field_type)

    for fn in export.functions:
        fn.class_name = namer.name_function_args(fn.module, fn.name, fn.fn_type)
        fn.fn_name = namer.name_function(fn.module, fn.name, fn.fn_type)
        fn.args.class_name = fn.class_name
        for f in fn.args.fields:
            _walk_and_name_type(namer, fn.class_name, f.name, f.field_type)
