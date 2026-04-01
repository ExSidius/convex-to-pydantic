"""Tests for namer.py — collision-free naming."""

from __future__ import annotations

import json
from pathlib import Path

from convex_to_pydantic.converter import parse_export
from convex_to_pydantic.namer import Namer, assign_names, to_pascal, to_snake

FIXTURES = Path(__file__).parent / "fixtures"


class TestToPascal:
    def test_snake_case(self):
        assert to_pascal("hello_world") == "HelloWorld"

    def test_camel_case(self):
        assert to_pascal("helloWorld") == "HelloWorld"

    def test_single_word(self):
        assert to_pascal("hello") == "Hello"

    def test_already_pascal(self):
        assert to_pascal("HelloWorld") == "HelloWorld"

    def test_with_dots(self):
        assert to_pascal("foo.bar") == "FooBar"

    def test_with_hyphens(self):
        assert to_pascal("my-component") == "MyComponent"


class TestToSnake:
    def test_camel_case(self):
        assert to_snake("helloWorld") == "hello_world"

    def test_pascal_case(self):
        assert to_snake("HelloWorld") == "hello_world"

    def test_already_snake(self):
        assert to_snake("hello_world") == "hello_world"

    def test_keyword(self):
        assert to_snake("class") == "class_"

    def test_id_keyword(self):
        assert to_snake("id") == "id_"

    def test_type_keyword(self):
        assert to_snake("type") == "type_"

    def test_system_field_id(self):
        assert to_snake("_id") == "id_"

    def test_system_field_creation_time(self):
        assert to_snake("_creationTime") == "creation_time"


class TestNamer:
    def test_no_collision(self):
        n = Namer()
        assert n.assign("Foo") == "Foo"
        assert n.assign("Bar") == "Bar"

    def test_collision(self):
        n = Namer()
        assert n.assign("Foo") == "Foo"
        assert n.assign("Foo") == "Foo2"
        assert n.assign("Foo") == "Foo3"

    def test_name_table(self):
        n = Namer()
        assert n.name_table("messages") == "MessagesTable"

    def test_name_function_args(self):
        n = Namer()
        assert n.name_function_args("calendars", "create", "mutation") == "CalendarsCreateMutationArgs"

    def test_name_function(self):
        n = Namer()
        assert n.name_function("calendars", "create", "mutation") == "calendars_create_mutation"

    def test_name_nested_object(self):
        n = Namer()
        assert n.name_nested_object("FooTable", "metadata") == "FooTableMetadata"


class TestAssignNames:
    def test_chat_app(self):
        blob = json.loads((FIXTURES / "chat_app.json").read_text())
        export = parse_export(blob)
        assign_names(export)
        assert export.tables[0].document_type.class_name == "MessagesTable"
        assert export.functions[0].class_name == "MessagesListQueryArgs"
        assert export.functions[0].fn_name == "messages_list_query"

    def test_kitchen_sink_nested(self):
        blob = json.loads((FIXTURES / "kitchen_sink.json").read_text())
        export = parse_export(blob)
        assign_names(export)
        table = export.tables[0]
        assert table.document_type.class_name == "AnalyticsEventsTable"
        # Find the nested metadata object
        metadata_field = next(f for f in table.document_type.fields if f.name == "metadata")
        metadata_obj = metadata_field.field_type
        assert metadata_obj.class_name == "AnalyticsEventsTableMetadata"
        # Find the doubly-nested campaign object
        campaign_field = next(f for f in metadata_obj.fields if f.name == "campaign")
        campaign_obj = campaign_field.field_type
        assert campaign_obj.class_name == "AnalyticsEventsTableMetadataCampaign"

    def test_no_duplicate_names(self):
        """All assigned names should be unique."""
        blob = json.loads((FIXTURES / "auth_app.json").read_text())
        export = parse_export(blob)
        assign_names(export)
        names = [t.document_type.class_name for t in export.tables]
        names += [f.class_name for f in export.functions]
        assert len(names) == len(set(names))
