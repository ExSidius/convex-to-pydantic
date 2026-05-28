"""Convert raw Convex JSON export dicts into the typed IR.

All functions are pure — they take dicts and return immutable IR values.
"""

from __future__ import annotations

from .types import (
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

_SYSTEM_FIELDS = (
    ConvexField(name="_id", field_type=ConvexString(), optional=True),
    ConvexField(name="_creationTime", field_type=ConvexFloat64(), optional=True),
)


def parse_convex_type(node: dict) -> ConvexType:
    """Convert a raw Convex type JSON node into the IR."""
    t = node["type"]

    if t == "null":
        return ConvexNull()
    if t == "boolean":
        return ConvexBoolean()
    if t in ("number", "float64"):
        return ConvexFloat64()
    if t in ("int64", "bigint"):
        return ConvexInt64()
    if t == "string":
        return ConvexString()
    if t == "bytes":
        return ConvexBytes()
    if t == "any":
        return ConvexAny()
    if t == "id":
        return ConvexId(table_name=node["tableName"])
    if t == "literal":
        return ConvexLiteral(value=node["value"])
    if t == "array":
        return ConvexArray(element=parse_convex_type(node["value"]))
    if t == "record":
        return ConvexRecord(
            keys=parse_convex_type(node["keys"]),
            values=parse_convex_type(node["values"]),
        )
    if t == "union":
        return ConvexUnion(variants=tuple(parse_convex_type(v) for v in node["value"]))
    if t == "object":
        return parse_convex_object(node)

    raise ValueError(f"Unknown Convex type: {t!r}")


def parse_convex_object(node: dict) -> ConvexObject:
    """Parse an object type node with its fields."""
    fields = tuple(
        ConvexField(
            name=field_name,
            field_type=parse_convex_type(field_def["fieldType"]),
            optional=field_def.get("optional", False),
        )
        for field_name, field_def in node["value"].items()
    )
    return ConvexObject(fields=fields)


def parse_table(table: dict) -> TableSchema:
    """Parse a table definition, prepending system fields."""
    doc_type = parse_convex_object(table["documentType"])
    return TableSchema(
        table_name=table["tableName"],
        document_type=ConvexObject(fields=_SYSTEM_FIELDS + doc_type.fields),
    )


def parse_function(fn: dict) -> FunctionSchema:
    """Parse a function definition."""
    args_node = fn.get("args")
    if args_node and args_node.get("type") == "object":
        args = parse_convex_object(args_node)
    else:
        args = ConvexObject(fields=())

    returns_node = fn.get("returns")
    returns = parse_convex_type(returns_node) if returns_node else None

    return FunctionSchema(
        module=fn["module"],
        name=fn["name"],
        fn_type=fn["type"],
        args=args,
        returns=returns,
    )


def parse_export(blob: dict) -> ConvexExport:
    """Parse the full export blob into the IR."""
    tables = tuple(parse_table(t) for t in blob.get("tables", []))
    functions = tuple(parse_function(f) for f in blob.get("functions", []))
    return ConvexExport(tables=tables, functions=functions)
