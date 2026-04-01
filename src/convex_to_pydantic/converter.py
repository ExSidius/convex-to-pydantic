"""Convert raw Convex JSON export dicts into the typed IR."""

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


def parse_convex_type(node: dict) -> ConvexType:
    """Convert a raw Convex type JSON node into the IR."""
    t = node["type"]

    if t == "null":
        return ConvexNull()
    if t == "boolean":
        return ConvexBoolean()
    if t in ("number", "float64"):
        return ConvexFloat64()
    if t == "int64":
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
        return ConvexUnion(variants=[parse_convex_type(v) for v in node["value"]])
    if t == "object":
        return parse_convex_object(node)

    raise ValueError(f"Unknown Convex type: {t!r}")


def parse_convex_object(node: dict) -> ConvexObject:
    """Parse an object type node with its fields."""
    fields: list[ConvexField] = []
    for field_name, field_def in node["value"].items():
        fields.append(
            ConvexField(
                name=field_name,
                field_type=parse_convex_type(field_def["fieldType"]),
                optional=field_def.get("optional", False),
            )
        )
    return ConvexObject(fields=fields)


def parse_table(table: dict) -> TableSchema:
    """Parse a table definition, prepending system fields."""
    table_name = table["tableName"]
    doc_type = parse_convex_object(table["documentType"])

    # Prepend system fields
    system_fields = [
        ConvexField(name="_id", field_type=ConvexString(), optional=False),
        ConvexField(name="_creationTime", field_type=ConvexFloat64(), optional=False),
    ]
    doc_type.fields = system_fields + doc_type.fields

    return TableSchema(table_name=table_name, document_type=doc_type)


def parse_function(fn: dict) -> FunctionSchema:
    """Parse a function definition."""
    args_node = fn.get("args")
    if args_node and args_node.get("type") == "object":
        args = parse_convex_object(args_node)
    else:
        args = ConvexObject(fields=[])

    return FunctionSchema(
        module=fn["module"],
        name=fn["name"],
        fn_type=fn["type"],
        args=args,
    )


def parse_export(blob: dict) -> ConvexExport:
    """Parse the full export blob into the IR."""
    tables = [parse_table(t) for t in blob.get("tables", [])]
    functions = [parse_function(f) for f in blob.get("functions", [])]
    return ConvexExport(tables=tables, functions=functions)
