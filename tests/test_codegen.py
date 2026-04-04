"""Tests for codegen — _types.py and _client.py generation.

All tests go through the pure pipeline: blob → transform → strings.
No IO involved.
"""

from __future__ import annotations

import json
from pathlib import Path

from convex_to_pydantic.pipeline import transform

FIXTURES = Path(__file__).parent / "fixtures"


def _generate(fixture_name: str) -> tuple[str, str]:
    """Helper: load fixture, run pure pipeline, return (types, client)."""
    blob = json.loads((FIXTURES / fixture_name).read_text())
    result = transform(blob)
    return result.types_content, result.client_content


# ---------------------------------------------------------------------------
# Chat app (simple baseline)
# ---------------------------------------------------------------------------


class TestChatApp:
    def test_types_has_messages_table(self):
        types, _ = _generate("chat_app.json")
        assert "class MessagesTable(BaseModel):" in types

    def test_types_has_system_fields(self):
        types, _ = _generate("chat_app.json")
        assert "id_: str" in types
        assert "creation_time: float" in types

    def test_types_has_constructor(self):
        types, _ = _generate("chat_app.json")
        assert "def messages_list_query(" in types
        assert "def messages_send_mutation(" in types

    def test_client_has_wrappers(self):
        _, client = _generate("chat_app.json")
        assert "async def messages_list_query_call(" in client
        assert "async def messages_send_mutation_call(" in client
        assert 'client.query("messages:list"' in client
        assert 'client.mutation("messages:send"' in client

    def test_empty_args_constructor(self):
        types, _ = _generate("chat_app.json")
        assert "def messages_list_query() -> MessagesListQueryArgs:" in types

    def test_table_model_before_constructor(self):
        """Table model and its constructor should be grouped together."""
        types, _ = _generate("chat_app.json")
        assert types.index("class MessagesTable(") < types.index("def messages_table(")

    def test_section_comments(self):
        types, _ = _generate("chat_app.json")
        assert "# --- Table: messages ---" in types
        assert "# --- Function: messages:list (query) ---" in types
        assert "# --- Function: messages:send (mutation) ---" in types


# ---------------------------------------------------------------------------
# Auth app (optional fields, id types, string literal unions)
# ---------------------------------------------------------------------------


class TestAuthApp:
    def test_types_has_all_tables(self):
        types, _ = _generate("auth_app.json")
        assert "class UsersTable(BaseModel):" in types
        assert "class SessionsTable(BaseModel):" in types
        assert "class AccountsTable(BaseModel):" in types
        assert "class VerificationTokensTable(BaseModel):" in types
        assert "class AuthenticatorsTable(BaseModel):" in types

    def test_nullable_field(self):
        types, _ = _generate("auth_app.json")
        assert "email_verified: float | None" in types

    def test_optional_field(self):
        types, _ = _generate("auth_app.json")
        assert "image: str | None = None" in types

    def test_id_type_comment(self):
        types, _ = _generate("auth_app.json")
        assert "# Id[users]" in types

    def test_str_enum_generated(self):
        types, _ = _generate("auth_app.json")
        assert "StrEnum" in types
        assert 'EMAIL = "email"' in types
        assert 'OIDC = "oidc"' in types
        assert 'OAUTH = "oauth"' in types
        assert 'WEBAUTHN = "webauthn"' in types

    def test_alias_for_camel_case(self):
        types, _ = _generate("auth_app.json")
        assert "alias='sessionToken'" in types or 'alias="sessionToken"' in types
        assert "alias='userId'" in types or 'alias="userId"' in types


# ---------------------------------------------------------------------------
# AI app (arrays, nullable IDs)
# ---------------------------------------------------------------------------


class TestAiApp:
    def test_array_type(self):
        types, _ = _generate("ai_app.json")
        assert "embedding: list[float]" in types

    def test_nullable_id(self):
        types, _ = _generate("ai_app.json")
        assert "embedding_id: str | None" in types

    def test_action_client_wrapper(self):
        _, client = _generate("ai_app.json")
        assert 'client.action("embeddings:search"' in client


# ---------------------------------------------------------------------------
# Kitchen sink (all edge cases)
# ---------------------------------------------------------------------------


class TestKitchenSink:
    def test_str_enum(self):
        types, _ = _generate("kitchen_sink.json")
        assert "StrEnum" in types
        assert 'CLICK = "click"' in types
        assert 'VIEW = "view"' in types
        assert 'PURCHASE = "purchase"' in types

    def test_int64_type(self):
        types, _ = _generate("kitchen_sink.json")
        assert "timestamp: int" in types
        assert "# int64" in types

    def test_any_type(self):
        types, _ = _generate("kitchen_sink.json")
        assert "payload: Any" in types

    def test_record_type(self):
        types, _ = _generate("kitchen_sink.json")
        assert "tags: dict[str, str]" in types

    def test_bytes_type(self):
        types, _ = _generate("kitchen_sink.json")
        assert "attachment: bytes | None" in types

    def test_nested_object(self):
        types, _ = _generate("kitchen_sink.json")
        assert "class AnalyticsEventsTableMetadata(BaseModel):" in types
        assert "class AnalyticsEventsTableMetadataCampaign(BaseModel):" in types

    def test_nested_object_field_reference(self):
        types, _ = _generate("kitchen_sink.json")
        assert "metadata: AnalyticsEventsTableMetadata" in types

    def test_nested_models_grouped_with_table(self):
        """Nested objects appear before their parent table, in the same group."""
        types, _ = _generate("kitchen_sink.json")
        campaign_pos = types.index("class AnalyticsEventsTableMetadataCampaign(")
        metadata_pos = types.index("class AnalyticsEventsTableMetadata(")
        table_pos = types.index("class AnalyticsEventsTable(")
        constructor_pos = types.index("def analytics_events_table(")
        assert campaign_pos < metadata_pos < table_pos < constructor_pos

    def test_mixed_literal_null_union(self):
        types, _ = _generate("kitchen_sink.json")
        assert "Literal[True] | Literal[False] | None" in types

    def test_single_literal(self):
        types, _ = _generate("kitchen_sink.json")
        assert "priority: Literal[1]" in types

    def test_nested_arrays(self):
        types, _ = _generate("kitchen_sink.json")
        assert "list[list[float]]" in types

    def test_function_with_record_arg(self):
        types, _ = _generate("kitchen_sink.json")
        assert "properties: dict[str, Any] | None" in types

    def test_function_with_int64_arg(self):
        types, _ = _generate("kitchen_sink.json")
        assert "count: int," in types

    def test_empty_args_function(self):
        types, _ = _generate("kitchen_sink.json")
        assert "def analytics_export_action() -> AnalyticsExportActionArgs:" in types

    def test_action_wrapper(self):
        _, client = _generate("kitchen_sink.json")
        assert 'client.action("analytics:export"' in client

    def test_types_file_is_valid_python(self):
        types, _ = _generate("kitchen_sink.json")
        compile(types, "_types.py", "exec")

    def test_client_file_is_valid_python(self):
        _, client = _generate("kitchen_sink.json")
        compile(client, "_client.py", "exec")

    def test_types_file_executes(self):
        types, _ = _generate("kitchen_sink.json")
        exec(compile(types, "_types.py", "exec"), {"__name__": "__test__"})


# ---------------------------------------------------------------------------
# Nested modules (subdirectory handling)
# ---------------------------------------------------------------------------


class TestNestedModules:
    def test_chat_messages_function_names(self):
        types, _ = _generate("nested_modules.json")
        assert "def chat_messages_list_query(" in types
        assert "def chat_messages_send_mutation(" in types

    def test_api_messages_function_names(self):
        types, _ = _generate("nested_modules.json")
        assert "def api_messages_list_query(" in types
        assert "def api_messages_delete_mutation(" in types

    def test_deep_nested_module(self):
        types, _ = _generate("nested_modules.json")
        assert "def admin_chat_moderate_ban_mutation(" in types

    def test_client_paths_preserve_slashes(self):
        _, client = _generate("nested_modules.json")
        assert 'client.query("chat/messages:list"' in client
        assert 'client.mutation("chat/messages:send"' in client
        assert 'client.query("api/messages:list"' in client
        assert 'client.mutation("api/messages:delete"' in client
        assert 'client.mutation("admin/chat/moderate:ban"' in client

    def test_no_name_collisions_between_modules(self):
        types, _ = _generate("nested_modules.json")
        assert "class ChatMessagesListQueryArgs(BaseModel):" in types
        assert "class ApiMessagesListQueryArgs(BaseModel):" in types

    def test_types_file_is_valid_python(self):
        types, _ = _generate("nested_modules.json")
        compile(types, "_types.py", "exec")

    def test_client_file_is_valid_python(self):
        _, client = _generate("nested_modules.json")
        compile(client, "_client.py", "exec")


# ---------------------------------------------------------------------------
# Cross-fixture: all fixtures produce valid Python
# ---------------------------------------------------------------------------


class TestAllFixturesValid:
    def test_all_types_compile(self):
        for fixture in FIXTURES.glob("*.json"):
            types, client = _generate(fixture.name)
            compile(types, f"{fixture.stem}/_types.py", "exec")
            compile(client, f"{fixture.stem}/_client.py", "exec")

    def test_all_types_execute(self):
        for fixture in FIXTURES.glob("*.json"):
            types, _ = _generate(fixture.name)
            exec(compile(types, f"{fixture.stem}/_types.py", "exec"), {"__name__": "__test__"})

    def test_transform_is_deterministic(self):
        """Same input always produces identical output."""
        for fixture in FIXTURES.glob("*.json"):
            blob = json.loads(fixture.read_text())
            r1 = transform(blob)
            r2 = transform(blob)
            assert r1.types_content == r2.types_content
            assert r1.client_content == r2.client_content
