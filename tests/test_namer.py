"""Tests for namer.py — collision-free naming (pure, returns NameRegistry)."""

from __future__ import annotations

import json
from pathlib import Path

from convex_to_pydantic.converter import parse_export
from convex_to_pydantic.namer import _Namer, NameRegistry, assign_names, to_pascal, to_snake
from convex_to_pydantic.types import ConvexObject

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

    def test_with_slashes(self):
        assert to_pascal("chat/messages") == "ChatMessages"

    def test_with_deep_slashes(self):
        assert to_pascal("admin/chat/moderate") == "AdminChatModerate"


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

    def test_with_slashes(self):
        assert to_snake("chat/messages") == "chat_messages"

    def test_with_deep_slashes(self):
        assert to_snake("admin/chat/moderate") == "admin_chat_moderate"


class TestNamer:
    def test_no_collision(self):
        n = _Namer()
        assert n.assign("Foo") == "Foo"
        assert n.assign("Bar") == "Bar"

    def test_collision(self):
        n = _Namer()
        assert n.assign("Foo") == "Foo"
        assert n.assign("Foo") == "Foo2"
        assert n.assign("Foo") == "Foo3"

    def test_name_table(self):
        n = _Namer()
        assert n.name_table("messages") == "MessagesTable"

    def test_name_function_args(self):
        n = _Namer()
        assert (
            n.name_function_args("calendars", "create", "mutation") == "CalendarsCreateMutationArgs"
        )

    def test_name_function_args_nested_module(self):
        n = _Namer()
        assert n.name_function_args("chat/messages", "list", "query") == "ChatMessagesListQueryArgs"

    def test_name_function(self):
        n = _Namer()
        assert n.name_function("calendars", "create", "mutation") == "calendars_create_mutation"

    def test_name_function_nested_module(self):
        n = _Namer()
        assert n.name_function("chat/messages", "list", "query") == "chat_messages_list_query"

    def test_different_modules_no_collision(self):
        """Functions in chat/messages and api/messages get distinct names."""
        n = _Namer()
        name1 = n.name_function_args("chat/messages", "list", "query")
        name2 = n.name_function_args("api/messages", "list", "query")
        assert name1 == "ChatMessagesListQueryArgs"
        assert name2 == "ApiMessagesListQueryArgs"
        assert name1 != name2

    def test_name_nested_object(self):
        n = _Namer()
        assert n.name_nested_object("FooTable", "metadata") == "FooTableMetadata"


class TestAssignNames:
    def test_returns_registry(self):
        blob = json.loads((FIXTURES / "chat_app.json").read_text())
        export = parse_export(blob)
        registry = assign_names(export)
        assert isinstance(registry, NameRegistry)

    def test_does_not_mutate_export(self):
        blob = json.loads((FIXTURES / "chat_app.json").read_text())
        export = parse_export(blob)
        # Frozen models can't be mutated — assign_names should not try
        assign_names(export)

    def test_chat_app(self):
        blob = json.loads((FIXTURES / "chat_app.json").read_text())
        export = parse_export(blob)
        registry = assign_names(export)
        assert registry.object_name(export.tables[0].document_type) == "MessagesTable"
        fn_names = registry.function_names(export.functions[0])
        assert fn_names.class_name == "MessagesListQueryArgs"
        assert fn_names.fn_name == "messages_list_query"

    def test_kitchen_sink_nested(self):
        blob = json.loads((FIXTURES / "kitchen_sink.json").read_text())
        export = parse_export(blob)
        registry = assign_names(export)
        table = export.tables[0]
        assert registry.object_name(table.document_type) == "AnalyticsEventsTable"
        metadata_field = next(f for f in table.document_type.fields if f.name == "metadata")
        metadata_obj = metadata_field.field_type
        assert isinstance(metadata_obj, ConvexObject)
        assert registry.object_name(metadata_obj) == "AnalyticsEventsTableMetadata"
        campaign_field = next(f for f in metadata_obj.fields if f.name == "campaign")
        campaign_obj = campaign_field.field_type
        assert isinstance(campaign_obj, ConvexObject)
        assert registry.object_name(campaign_obj) == "AnalyticsEventsTableMetadataCampaign"

    def test_no_duplicate_names(self):
        blob = json.loads((FIXTURES / "auth_app.json").read_text())
        export = parse_export(blob)
        registry = assign_names(export)
        all_names = list(registry.objects.values())
        assert len(all_names) == len(set(all_names))

    def test_deterministic(self):
        """Same input always produces same names."""
        blob = json.loads((FIXTURES / "kitchen_sink.json").read_text())
        export = parse_export(blob)
        r1 = assign_names(export)
        r2 = assign_names(export)
        assert dict(r1.objects) == dict(r2.objects)

    def test_nested_modules_distinct_names(self):
        """chat/messages and api/messages produce distinct class names."""
        blob = json.loads((FIXTURES / "nested_modules.json").read_text())
        export = parse_export(blob)
        registry = assign_names(export)
        fn_names = [registry.function_names(fn) for fn in export.functions]
        class_names = [n.class_name for n in fn_names]
        assert len(class_names) == len(set(class_names)), f"Duplicate class names: {class_names}"

    def test_nested_modules_no_duplicate_names(self):
        blob = json.loads((FIXTURES / "nested_modules.json").read_text())
        export = parse_export(blob)
        registry = assign_names(export)
        all_names = list(registry.objects.values())
        assert len(all_names) == len(set(all_names))
