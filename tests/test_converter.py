"""Tests for converter.py — JSON dict → IR conversion."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from convex_to_pydantic.converter import (
    parse_convex_type,
    parse_export,
    parse_function,
    parse_table,
)
from convex_to_pydantic.types import (
    ConvexAny,
    ConvexArray,
    ConvexBoolean,
    ConvexBytes,
    ConvexFloat64,
    ConvexId,
    ConvexInt64,
    ConvexLiteral,
    ConvexNull,
    ConvexObject,
    ConvexRecord,
    ConvexString,
    ConvexUnion,
)

FIXTURES = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Primitive types
# ---------------------------------------------------------------------------


class TestParseConvexType:
    def test_null(self):
        assert isinstance(parse_convex_type({"type": "null"}), ConvexNull)

    def test_boolean(self):
        assert isinstance(parse_convex_type({"type": "boolean"}), ConvexBoolean)

    def test_number(self):
        result = parse_convex_type({"type": "number"})
        assert isinstance(result, ConvexFloat64)

    def test_float64(self):
        result = parse_convex_type({"type": "float64"})
        assert isinstance(result, ConvexFloat64)

    def test_int64(self):
        assert isinstance(parse_convex_type({"type": "int64"}), ConvexInt64)

    def test_bigint_canonical_name(self):
        """Convex canonical JSON uses 'bigint' not 'int64'."""
        assert isinstance(parse_convex_type({"type": "bigint"}), ConvexInt64)

    def test_string(self):
        assert isinstance(parse_convex_type({"type": "string"}), ConvexString)

    def test_bytes(self):
        assert isinstance(parse_convex_type({"type": "bytes"}), ConvexBytes)

    def test_any(self):
        assert isinstance(parse_convex_type({"type": "any"}), ConvexAny)

    def test_id(self):
        result = parse_convex_type({"type": "id", "tableName": "users"})
        assert isinstance(result, ConvexId)
        assert result.table_name == "users"

    def test_literal_string(self):
        result = parse_convex_type({"type": "literal", "value": "hello"})
        assert isinstance(result, ConvexLiteral)
        assert result.value == "hello"

    def test_literal_int(self):
        result = parse_convex_type({"type": "literal", "value": 42})
        assert isinstance(result, ConvexLiteral)
        assert result.value == 42

    def test_literal_bool(self):
        result = parse_convex_type({"type": "literal", "value": True})
        assert isinstance(result, ConvexLiteral)
        assert result.value is True

    def test_array(self):
        result = parse_convex_type({"type": "array", "value": {"type": "string"}})
        assert isinstance(result, ConvexArray)
        assert isinstance(result.element, ConvexString)

    def test_nested_array(self):
        result = parse_convex_type(
            {
                "type": "array",
                "value": {"type": "array", "value": {"type": "number"}},
            }
        )
        assert isinstance(result, ConvexArray)
        assert isinstance(result.element, ConvexArray)
        assert isinstance(result.element.element, ConvexFloat64)

    def test_record(self):
        result = parse_convex_type(
            {
                "type": "record",
                "keys": {"type": "string"},
                "values": {"type": "any"},
            }
        )
        assert isinstance(result, ConvexRecord)
        assert isinstance(result.keys, ConvexString)
        assert isinstance(result.values, ConvexAny)

    def test_union(self):
        result = parse_convex_type(
            {
                "type": "union",
                "value": [{"type": "string"}, {"type": "null"}],
            }
        )
        assert isinstance(result, ConvexUnion)
        assert len(result.variants) == 2

    def test_object(self):
        result = parse_convex_type(
            {
                "type": "object",
                "value": {
                    "name": {"fieldType": {"type": "string"}, "optional": False},
                    "age": {"fieldType": {"type": "number"}, "optional": True},
                },
            }
        )
        assert isinstance(result, ConvexObject)
        assert len(result.fields) == 2
        assert result.fields[0].name == "name"
        assert not result.fields[0].optional
        assert result.fields[1].name == "age"
        assert result.fields[1].optional

    def test_empty_object(self):
        result = parse_convex_type({"type": "object", "value": {}})
        assert isinstance(result, ConvexObject)
        assert len(result.fields) == 0

    def test_unknown_type_raises(self):
        with pytest.raises(ValueError, match="Unknown Convex type"):
            parse_convex_type({"type": "unknown_type"})

    def test_results_are_immutable(self):
        result = parse_convex_type({"type": "string"})
        with pytest.raises(Exception):
            result.type = "int64"  # type: ignore


# ---------------------------------------------------------------------------
# Table parsing
# ---------------------------------------------------------------------------


class TestParseTable:
    def test_prepends_system_fields(self):
        table = {
            "tableName": "messages",
            "documentType": {
                "type": "object",
                "value": {
                    "body": {"fieldType": {"type": "string"}, "optional": False},
                },
            },
        }
        result = parse_table(table)
        assert result.table_name == "messages"
        assert result.document_type.fields[0].name == "_id"
        assert result.document_type.fields[1].name == "_creationTime"
        assert result.document_type.fields[2].name == "body"

    def test_system_field_types(self):
        table = {
            "tableName": "t",
            "documentType": {"type": "object", "value": {}},
        }
        result = parse_table(table)
        assert isinstance(result.document_type.fields[0].field_type, ConvexString)
        assert isinstance(result.document_type.fields[1].field_type, ConvexFloat64)

    def test_result_is_immutable(self):
        table = {
            "tableName": "t",
            "documentType": {"type": "object", "value": {}},
        }
        result = parse_table(table)
        with pytest.raises(Exception):
            result.table_name = "other"


# ---------------------------------------------------------------------------
# Function parsing
# ---------------------------------------------------------------------------


class TestParseFunction:
    def test_basic(self):
        fn = {
            "module": "messages",
            "name": "send",
            "type": "mutation",
            "args": {
                "type": "object",
                "value": {
                    "body": {"fieldType": {"type": "string"}, "optional": False},
                },
            },
        }
        result = parse_function(fn)
        assert result.module == "messages"
        assert result.name == "send"
        assert result.fn_type == "mutation"
        assert len(result.args.fields) == 1

    def test_empty_args(self):
        fn = {
            "module": "messages",
            "name": "list",
            "type": "query",
            "args": {"type": "object", "value": {}},
        }
        result = parse_function(fn)
        assert len(result.args.fields) == 0

    def test_no_args_key(self):
        fn = {"module": "m", "name": "n", "type": "query"}
        result = parse_function(fn)
        assert len(result.args.fields) == 0


# ---------------------------------------------------------------------------
# Full export parsing — fixtures
# ---------------------------------------------------------------------------


class TestParseExport:
    def test_chat_app(self):
        blob = json.loads((FIXTURES / "chat_app.json").read_text())
        export = parse_export(blob)
        assert len(export.tables) == 1
        assert len(export.functions) == 2
        assert export.tables[0].table_name == "messages"

    def test_auth_app(self):
        blob = json.loads((FIXTURES / "auth_app.json").read_text())
        export = parse_export(blob)
        assert len(export.tables) == 5
        assert len(export.functions) == 2
        accounts = next(t for t in export.tables if t.table_name == "accounts")
        type_field = next(f for f in accounts.document_type.fields if f.name == "type")
        assert isinstance(type_field.field_type, ConvexUnion)

    def test_ai_app(self):
        blob = json.loads((FIXTURES / "ai_app.json").read_text())
        export = parse_export(blob)
        assert len(export.tables) == 2
        embeddings = next(t for t in export.tables if t.table_name == "embeddings")
        emb_field = next(f for f in embeddings.document_type.fields if f.name == "embedding")
        assert isinstance(emb_field.field_type, ConvexArray)

    def test_kitchen_sink(self):
        blob = json.loads((FIXTURES / "kitchen_sink.json").read_text())
        export = parse_export(blob)
        assert len(export.tables) == 1
        assert len(export.functions) == 3
        table = export.tables[0]
        fields_by_name = {f.name: f for f in table.document_type.fields}
        assert isinstance(fields_by_name["timestamp"].field_type, ConvexInt64)
        assert isinstance(fields_by_name["payload"].field_type, ConvexAny)
        assert isinstance(fields_by_name["tags"].field_type, ConvexRecord)
        assert isinstance(fields_by_name["metadata"].field_type, ConvexObject)
        assert isinstance(fields_by_name["nestedArrays"].field_type, ConvexArray)
        assert fields_by_name["attachment"].optional is True

    def test_export_is_immutable(self):
        blob = json.loads((FIXTURES / "chat_app.json").read_text())
        export = parse_export(blob)
        with pytest.raises(Exception):
            export.tables = ()
