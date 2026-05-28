"""Tests for codegen — _types.py and _client.py generation.

All tests go through the pure pipeline: blob → transform → strings.
No IO involved.
"""

from __future__ import annotations

import json
import sys
import types as _pytypes
from pathlib import Path

from convex_to_pydantic.pipeline import transform

FIXTURES = Path(__file__).parent / "fixtures"


def _generate(fixture_name: str) -> tuple[str, str]:
    """Helper: load fixture, run pure pipeline, return (types, client)."""
    blob = json.loads((FIXTURES / fixture_name).read_text())
    result = transform(blob)
    return result.types_content, result.client_content


def _generate_sync(fixture_name: str) -> tuple[str, str]:
    """Helper: load fixture, run pure pipeline in sync mode, return (types, client)."""
    blob = json.loads((FIXTURES / fixture_name).read_text())
    result = transform(blob, client_style="sync")
    return result.types_content, result.client_content


_EXEC_PKG_COUNTER = 0


def _exec_client(client_str: str, types_str: str) -> dict:
    """Exec a generated `_client.py` in a synthetic package so its
    `from ._types import ...` resolves. Returns the client namespace."""
    global _EXEC_PKG_COUNTER
    _EXEC_PKG_COUNTER += 1
    pkg_name = f"_c2p_test_pkg_{_EXEC_PKG_COUNTER}"

    pkg = _pytypes.ModuleType(pkg_name)
    pkg.__path__ = []  # type: ignore[attr-defined]
    sys.modules[pkg_name] = pkg

    types_mod = _pytypes.ModuleType(f"{pkg_name}._types")
    exec(compile(types_str, "_types.py", "exec"), types_mod.__dict__)
    sys.modules[f"{pkg_name}._types"] = types_mod

    try:
        client_ns: dict = {"__name__": f"{pkg_name}._client", "__package__": pkg_name}
        exec(compile(client_str, "_client.py", "exec"), client_ns)
        return client_ns
    finally:
        sys.modules.pop(f"{pkg_name}._types", None)
        sys.modules.pop(pkg_name, None)


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

    def test_system_fields_are_optional(self):
        """System fields are server-assigned; clients must be able to construct
        a table model without providing them."""
        types, _ = _generate("chat_app.json")
        assert "id_: str | None = Field(default=None, alias='_id')" in types
        assert "creation_time: float | None = Field(default=None, alias='_creationTime')" in types

    def test_table_model_constructible_without_system_fields(self):
        """Exec the generated module and instantiate a table model with only
        user-provided fields — mirrors the JSONL-export / fixture use case."""
        types, _ = _generate("chat_app.json")
        ns: dict = {}
        exec(compile(types, "_types.py", "exec"), ns)
        MessagesTable = ns["MessagesTable"]
        doc = MessagesTable(author="alice", body="hi")
        assert doc.id_ is None
        assert doc.creation_time is None
        # And parsing a server document with system fields still works.
        full = MessagesTable.model_validate(
            {"_id": "abc", "_creationTime": 1.0, "author": "alice", "body": "hi"}
        )
        assert full.id_ == "abc"
        assert full.creation_time == 1.0

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


class TestSyncClient:
    """Sync client_style: emit plain `def` wrappers without `await`."""

    def test_client_has_sync_wrappers(self):
        _, client = _generate_sync("chat_app.json")
        assert "def messages_list_query_call(" in client
        assert "def messages_send_mutation_call(" in client

    def test_no_async_keyword(self):
        _, client = _generate_sync("chat_app.json")
        assert "async def" not in client
        assert "await " not in client

    def test_sync_client_calls(self):
        _, client = _generate_sync("chat_app.json")
        assert 'return client.query("messages:list"' in client
        assert 'return client.mutation("messages:send"' in client

    def test_sync_action_wrapper(self):
        _, client = _generate_sync("ai_app.json")
        assert 'return client.action("embeddings:search"' in client
        assert "async def" not in client

    def test_types_identical_to_async(self):
        """Switching client_style must not change _types.py."""
        for fixture in FIXTURES.glob("*.json"):
            async_types, _ = _generate(fixture.name)
            sync_types, _ = _generate_sync(fixture.name)
            assert async_types == sync_types, f"types differ for {fixture.name}"

    def test_all_fixtures_sync_compile(self):
        for fixture in FIXTURES.glob("*.json"):
            _, client = _generate_sync(fixture.name)
            compile(client, f"{fixture.stem}/_client.py", "exec")


class TestLiteralInFnArgs:
    """Regression: `str | Literal["portfolio"]` in function args must import Literal.

    Previously `_client.py` hardcoded `from typing import Any, TYPE_CHECKING`,
    so any fn whose rendered arg type emitted `Literal[...]` produced a file
    that failed at import with `NameError: name 'Literal' is not defined`.
    """

    def test_client_imports_literal(self):
        _, client = _generate("literal_in_fn_args.json")
        assert "from typing import Any, Literal, TYPE_CHECKING" in client

    def test_client_emits_literal_annotation(self):
        _, client = _generate("literal_in_fn_args.json")
        assert 'Literal["portfolio"]' in client or "Literal['portfolio']" in client

    def test_client_executes(self):
        """Exec the generated module in a synthetic package and force
        annotation resolution — this is what catches the original bug
        (NameError on unimported `Literal`). Without `get_type_hints`, the
        `from __future__ import annotations` directive keeps annotations as
        lazy strings and the missing name is never looked up."""
        import typing

        types, client = _generate("literal_in_fn_args.json")
        ns = _exec_client(client, types)
        fn = ns["portfolio_get_query_call"]
        # ConvexClient is a TYPE_CHECKING-only forward ref; stub it so
        # annotation resolution doesn't fail on that unrelated symbol.
        typing.get_type_hints(fn, localns={"ConvexClient": object})


class TestTypedReturnsPydantic:
    """Pydantic mode: typed return annotations + Model.model_validate / TypeAdapter wrapping."""

    def _generate(self, return_type: str) -> tuple[str, str]:
        blob = json.loads((FIXTURES / "typed_returns.json").read_text())
        result = transform(blob, return_type=return_type)
        return result.types_content, result.client_content

    def test_object_return_annotation(self):
        _, client = self._generate("pydantic")
        assert "async def posts_get_query_call(" in client
        assert ") -> PostsGetQueryReturns:" in client

    def test_object_return_model_validate(self):
        _, client = self._generate("pydantic")
        assert 'PostsGetQueryReturns.model_validate(await client.query("posts:get"' in client

    def test_scalar_return_uses_type_adapter(self):
        _, client = self._generate("pydantic")
        assert ") -> float:" in client
        assert "TypeAdapter(float).validate_python(" in client

    def test_list_of_primitive_return(self):
        _, client = self._generate("pydantic")
        assert ") -> list[str]:" in client
        assert "TypeAdapter(list[str]).validate_python(" in client

    def test_list_of_object_return(self):
        _, client = self._generate("pydantic")
        assert ") -> list[PostsListQueryReturnsItem]:" in client
        assert "TypeAdapter(list[PostsListQueryReturnsItem]).validate_python(" in client

    def test_undeclared_returns_falls_back_to_any(self):
        _, client = self._generate("pydantic")
        # `posts:create` has no `returns:` validator — annotation is Any and
        # the call is not wrapped.
        idx = client.index("async def posts_create_mutation_call(")
        snippet = client[idx : idx + 600]
        assert ") -> Any:" in snippet
        assert ".model_validate(" not in snippet
        assert "TypeAdapter(" not in snippet

    def test_return_model_emitted_in_types(self):
        types, _ = self._generate("pydantic")
        assert "class PostsGetQueryReturns(BaseModel):" in types
        assert "class PostsListQueryReturnsItem(BaseModel):" in types

    def test_return_model_has_forbid_extra(self):
        types, _ = self._generate("pydantic")
        # Both args and returns share the same strict config.
        get_returns_idx = types.index("class PostsGetQueryReturns(")
        snippet = types[get_returns_idx : get_returns_idx + 300]
        assert 'extra="forbid"' in snippet

    def test_no_constructor_for_returns(self):
        types, _ = self._generate("pydantic")
        # Returns are received, not constructed — no helper function should
        # be emitted with the *_returns naming.
        assert "def posts_get_query_returns(" not in types
        assert "def posts_list_query_returns(" not in types

    def test_type_adapter_imported_only_when_needed(self):
        _, client = self._generate("pydantic")
        assert "from pydantic import TypeAdapter" in client

    def test_return_classes_in_type_imports(self):
        _, client = self._generate("pydantic")
        import_line = next(ln for ln in client.splitlines() if ln.startswith("from ._types"))
        assert "PostsGetQueryReturns" in import_line
        assert "PostsListQueryReturnsItem" in import_line

    def test_compiles(self):
        types, client = self._generate("pydantic")
        compile(types, "_types.py", "exec")
        compile(client, "_client.py", "exec")


class TestTypedReturnsTypedDict:
    """TypedDict mode: TypedDict definitions + cast() at call sites."""

    def _generate(self) -> tuple[str, str]:
        blob = json.loads((FIXTURES / "typed_returns.json").read_text())
        result = transform(blob, return_type="typeddict")
        return result.types_content, result.client_content

    def test_emits_typeddict_classes(self):
        types, _ = self._generate()
        assert "class PostsGetQueryReturns(TypedDict):" in types
        assert "class PostsListQueryReturnsItem(TypedDict):" in types

    def test_typeddict_imports(self):
        types, _ = self._generate()
        assert "TypedDict" in types
        assert "NotRequired" in types

    def test_optional_field_uses_not_required(self):
        types, _ = self._generate()
        idx = types.index("class PostsGetQueryReturns(TypedDict):")
        snippet = types[idx : idx + 400]
        assert "publishedAt: NotRequired[float | None]" in snippet

    def test_typeddict_keys_not_renamed(self):
        # TypedDict can't rename keys, so `id` stays `id` (matching the JSON wire),
        # unlike the Pydantic model which would alias to `id_`.
        types, _ = self._generate()
        idx = types.index("class PostsGetQueryReturns(TypedDict):")
        snippet = types[idx : idx + 400]
        assert "id: str" in snippet
        assert "id_:" not in snippet

    def test_client_uses_cast(self):
        _, client = self._generate()
        assert "from typing import" in client
        assert "cast" in client
        assert "cast(PostsGetQueryReturns, await client.query(" in client
        assert "cast(list[PostsListQueryReturnsItem], await client.query(" in client

    def test_scalar_return_uses_cast(self):
        _, client = self._generate()
        assert "cast(float, await client.query(" in client
        assert "cast(list[str], await client.query(" in client

    def test_undeclared_returns_falls_back_to_any(self):
        _, client = self._generate()
        idx = client.index("async def posts_create_mutation_call(")
        snippet = client[idx : idx + 600]
        assert ") -> Any:" in snippet
        assert "cast(" not in snippet

    def test_no_type_adapter_import(self):
        _, client = self._generate()
        assert "TypeAdapter" not in client

    def test_compiles(self):
        types, client = self._generate()
        compile(types, "_types.py", "exec")
        compile(client, "_client.py", "exec")


class TestTypedReturnsAny:
    """`any` mode preserves today's `-> Any` behavior — no return classes generated."""

    def _generate(self) -> tuple[str, str]:
        blob = json.loads((FIXTURES / "typed_returns.json").read_text())
        result = transform(blob, return_type="any")
        return result.types_content, result.client_content

    def test_all_calls_return_any(self):
        _, client = self._generate()
        # Five functions, all annotated `-> Any`.
        assert client.count(") -> Any:") == 5

    def test_no_return_classes_in_types(self):
        types, _ = self._generate()
        assert "PostsGetQueryReturns" not in types
        assert "PostsListQueryReturnsItem" not in types

    def test_no_typeadapter_or_cast(self):
        _, client = self._generate()
        assert "TypeAdapter" not in client
        assert "cast(" not in client


class TestMissingReturnsWarning:
    """`missing_returns` lists every function lacking a `returns:` validator,
    but only when `return_type` is non-`any`."""

    def test_collects_missing_in_pydantic_mode(self):
        blob = json.loads((FIXTURES / "typed_returns.json").read_text())
        result = transform(blob, return_type="pydantic")
        assert result.missing_returns == ("posts:create",)

    def test_collects_missing_in_typeddict_mode(self):
        blob = json.loads((FIXTURES / "typed_returns.json").read_text())
        result = transform(blob, return_type="typeddict")
        assert result.missing_returns == ("posts:create",)

    def test_empty_in_any_mode(self):
        blob = json.loads((FIXTURES / "typed_returns.json").read_text())
        result = transform(blob, return_type="any")
        assert result.missing_returns == ()

    def test_existing_fixtures_have_no_returns(self):
        # None of the legacy fixtures declare `returns:`, so every function
        # surfaces in the warning under pydantic mode.
        blob = json.loads((FIXTURES / "chat_app.json").read_text())
        result = transform(blob, return_type="pydantic")
        assert set(result.missing_returns) == {"messages:list", "messages:send"}


class TestReturnTypeValidation:
    def test_invalid_return_type_raises(self):
        import pytest as _pytest

        with _pytest.raises(ValueError, match="return_type"):
            transform({"tables": [], "functions": []}, return_type="bogus")


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

    def test_all_clients_execute(self):
        """Exec each generated _client.py and resolve annotations so missing
        imports (e.g. forgotten `Literal`) surface here rather than downstream
        at import time. Annotation resolution is required — `from __future__
        import annotations` keeps annotations as lazy strings otherwise."""
        import typing

        # Stub the TYPE_CHECKING-only ConvexClient forward reference.
        localns = {"ConvexClient": object}
        for fixture in FIXTURES.glob("*.json"):
            types, client = _generate(fixture.name)
            ns = _exec_client(client, types)
            for name, obj in list(ns.items()):
                if callable(obj) and name.endswith("_call"):
                    typing.get_type_hints(obj, localns=localns)

    def test_transform_is_deterministic(self):
        """Same input always produces identical output."""
        for fixture in FIXTURES.glob("*.json"):
            blob = json.loads(fixture.read_text())
            r1 = transform(blob)
            r2 = transform(blob)
            assert r1.types_content == r2.types_content
            assert r1.client_content == r2.client_content
