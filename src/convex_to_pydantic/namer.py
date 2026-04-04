"""Collision-free PascalCase naming for all generated classes and functions.

Pure module — assign_names() takes an immutable ConvexExport and returns
a NameRegistry (keyed by object identity) without mutating anything.
"""

from __future__ import annotations

import keyword
import re
from dataclasses import dataclass, field

from .types import (
    ConvexArray,
    ConvexExport,
    ConvexObject,
    ConvexRecord,
    ConvexType,
    ConvexUnion,
    FunctionSchema,
)


def to_pascal(s: str) -> str:
    """Convert a string to PascalCase."""
    parts = re.sub(r"([a-z])([A-Z])", r"\1_\2", s)
    parts = re.split(r"[_\-./:]+", parts)
    return "".join(p.capitalize() for p in parts if p)


def to_snake(s: str) -> str:
    """Convert a string to snake_case."""
    stripped = s.lstrip("_")
    stripped = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", stripped)
    stripped = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", stripped)
    result = re.sub(r"[_\-./:]+", "_", stripped).lower()
    if keyword.iskeyword(result) or result in ("id", "type"):
        result = result + "_"
    return result


@dataclass(frozen=True)
class FunctionNames:
    """Names for a single Convex function."""

    class_name: str  # e.g. "CalendarsCreateMutationArgs"
    fn_name: str  # e.g. "calendars_create_mutation"


@dataclass
class NameRegistry:
    """Maps IR objects to their assigned names. Keyed by id() of the object."""

    objects: dict[int, str] = field(default_factory=dict)
    functions: dict[int, FunctionNames] = field(default_factory=dict)

    def object_name(self, obj: ConvexObject) -> str:
        return self.objects[id(obj)]

    def function_names(self, fn: FunctionSchema) -> FunctionNames:
        return self.functions[id(fn)]


class _Namer:
    """Stateful name allocator — internal, used only during assign_names()."""

    def __init__(self) -> None:
        self._used: set[str] = set()

    def assign(self, preferred: str) -> str:
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
        return self.assign(to_pascal(module) + to_pascal(fn_name) + to_pascal(fn_type) + "Args")

    def name_function(self, module: str, fn_name: str, fn_type: str) -> str:
        return to_snake(module) + "_" + to_snake(fn_name) + "_" + to_snake(fn_type)

    def name_nested_object(self, parent_name: str, field_name: str) -> str:
        return self.assign(parent_name + to_pascal(field_name))


def _walk_and_name_type(
    namer: _Namer,
    registry: NameRegistry,
    parent_name: str,
    field_name: str,
    t: ConvexType,
) -> None:
    """Recursively walk a type tree, registering names for ConvexObject nodes."""
    if isinstance(t, ConvexArray):
        _walk_and_name_type(namer, registry, parent_name, field_name + "Item", t.element)
        return
    if isinstance(t, ConvexUnion):
        for i, v in enumerate(t.variants):
            _walk_and_name_type(namer, registry, parent_name, f"{field_name}Variant{i}", v)
        return
    if isinstance(t, ConvexRecord):
        _walk_and_name_type(namer, registry, parent_name, field_name + "Key", t.keys)
        _walk_and_name_type(namer, registry, parent_name, field_name + "Value", t.values)
        return
    if not isinstance(t, ConvexObject):
        return
    if id(t) in registry.objects:
        return
    name = namer.name_nested_object(parent_name, field_name)
    registry.objects[id(t)] = name
    for f in t.fields:
        _walk_and_name_type(namer, registry, name, f.name, f.field_type)


def assign_names(export: ConvexExport) -> NameRegistry:
    """Walk the entire IR and build a name registry. Pure — does not mutate export."""
    namer = _Namer()
    registry = NameRegistry()

    for table in export.tables:
        table_class = namer.name_table(table.table_name)
        registry.objects[id(table.document_type)] = table_class
        for f in table.document_type.fields:
            _walk_and_name_type(namer, registry, table_class, f.name, f.field_type)

    for fn in export.functions:
        class_name = namer.name_function_args(fn.module, fn.name, fn.fn_type)
        fn_name = namer.name_function(fn.module, fn.name, fn.fn_type)
        registry.functions[id(fn)] = FunctionNames(class_name=class_name, fn_name=fn_name)
        registry.objects[id(fn.args)] = class_name
        for f in fn.args.fields:
            _walk_and_name_type(namer, registry, class_name, f.name, f.field_type)

    return registry
