"""Tests for tree output mode — per-module file generation."""

from __future__ import annotations

import json
from pathlib import Path

from convex_to_pydantic.pipeline import transform

FIXTURES = Path(__file__).parent / "fixtures"


def _tree(fixture_name: str) -> dict[str, str]:
    """Helper: load fixture, run tree pipeline, return tree_files dict."""
    blob = json.loads((FIXTURES / fixture_name).read_text())
    result = transform(blob, output_mode="tree")
    return result.tree_files


def _tree_sync(fixture_name: str) -> dict[str, str]:
    """Helper: run tree pipeline in sync client mode."""
    blob = json.loads((FIXTURES / fixture_name).read_text())
    result = transform(blob, output_mode="tree", client_style="sync")
    return result.tree_files


class TestTreeChatApp:
    def test_has_tables_file(self):
        files = _tree("chat_app.json")
        assert "_tables.py" in files

    def test_has_module_file(self):
        files = _tree("chat_app.json")
        assert "messages.py" in files

    def test_has_barrel(self):
        files = _tree("chat_app.json")
        assert "__init__.py" in files

    def test_tables_file_has_model(self):
        files = _tree("chat_app.json")
        assert "class MessagesTable(BaseModel):" in files["_tables.py"]

    def test_module_file_has_constructor(self):
        files = _tree("chat_app.json")
        assert "def messages_list_query(" in files["messages.py"]
        assert "def messages_send_mutation(" in files["messages.py"]

    def test_module_file_has_client_wrapper(self):
        files = _tree("chat_app.json")
        assert "async def messages_list_query_call(" in files["messages.py"]
        assert "async def messages_send_mutation_call(" in files["messages.py"]

    def test_all_files_valid_python(self):
        files = _tree("chat_app.json")
        for path, content in files.items():
            compile(content, path, "exec")

    def test_barrel_re_exports(self):
        files = _tree("chat_app.json")
        barrel = files["__init__.py"]
        assert "from ._tables import *" in barrel
        assert "from .messages import *" in barrel


class TestTreeNestedModules:
    def test_nested_module_paths(self):
        files = _tree("nested_modules.json")
        assert "chat/messages.py" in files
        assert "api/messages.py" in files
        assert "admin/chat/moderate.py" in files

    def test_nested_module_content(self):
        files = _tree("nested_modules.json")
        assert "def chat_messages_list_query(" in files["chat/messages.py"]
        assert "def api_messages_list_query(" in files["api/messages.py"]
        assert "def admin_chat_moderate_ban_mutation(" in files["admin/chat/moderate.py"]

    def test_client_wrappers_in_modules(self):
        files = _tree("nested_modules.json")
        assert 'client.query("chat/messages:list"' in files["chat/messages.py"]
        assert 'client.mutation("api/messages:delete"' in files["api/messages.py"]

    def test_barrel_imports_nested(self):
        files = _tree("nested_modules.json")
        barrel = files["__init__.py"]
        assert "from .admin.chat.moderate import *" in barrel
        assert "from .api.messages import *" in barrel
        assert "from .chat.messages import *" in barrel

    def test_all_files_valid_python(self):
        files = _tree("nested_modules.json")
        for path, content in files.items():
            compile(content, path, "exec")


class TestTreeAllFixtures:
    def test_all_fixtures_produce_valid_python(self):
        for fixture in FIXTURES.glob("*.json"):
            if fixture.name == "large_export.json":
                continue  # skip large fixture for speed
            files = _tree(fixture.name)
            for path, content in files.items():
                compile(content, f"{fixture.stem}/{path}", "exec")


class TestTreeSyncClient:
    def test_module_file_has_sync_wrappers(self):
        files = _tree_sync("chat_app.json")
        module = files["messages.py"]
        assert "def messages_list_query_call(" in module
        assert "def messages_send_mutation_call(" in module
        assert "async def" not in module
        assert "await " not in module

    def test_sync_client_method_calls(self):
        files = _tree_sync("chat_app.json")
        module = files["messages.py"]
        assert 'return client.query("messages:list"' in module
        assert 'return client.mutation("messages:send"' in module

    def test_nested_modules_sync(self):
        files = _tree_sync("nested_modules.json")
        for path in ("chat/messages.py", "api/messages.py", "admin/chat/moderate.py"):
            content = files[path]
            assert "async def" not in content, f"async found in {path}"
            assert "await " not in content, f"await found in {path}"

    def test_all_fixtures_sync_compile(self):
        for fixture in FIXTURES.glob("*.json"):
            if fixture.name == "large_export.json":
                continue
            files = _tree_sync(fixture.name)
            for path, content in files.items():
                compile(content, f"{fixture.stem}/{path}", "exec")


class TestTreeTypedReturns:
    """Tree mode honors `return_type` per-module: same wrappers, validation,
    and TypedDict / Pydantic class emission as single mode."""

    def _tree(self, return_type: str) -> dict[str, str]:
        blob = json.loads((FIXTURES / "typed_returns.json").read_text())
        result = transform(blob, output_mode="tree", return_type=return_type)
        return result.tree_files

    def test_pydantic_typed_returns_in_module(self):
        files = self._tree("pydantic")
        module = files["posts.py"]
        assert ") -> PostsGetQueryReturns:" in module
        assert "PostsGetQueryReturns.model_validate(" in module
        assert "class PostsGetQueryReturns(BaseModel):" in module

    def test_pydantic_scalar_return_uses_type_adapter(self):
        files = self._tree("pydantic")
        module = files["posts.py"]
        assert "from pydantic import TypeAdapter" in module
        assert "TypeAdapter(float).validate_python(" in module

    def test_typeddict_emits_typeddict_class(self):
        files = self._tree("typeddict")
        module = files["posts.py"]
        assert "class PostsGetQueryReturns(TypedDict):" in module
        assert "publishedAt: NotRequired[float | None]" in module

    def test_typeddict_uses_cast(self):
        files = self._tree("typeddict")
        module = files["posts.py"]
        assert "cast(PostsGetQueryReturns, await client.query(" in module
        assert "TypeAdapter" not in module

    def test_any_mode_returns_any(self):
        files = self._tree("any")
        module = files["posts.py"]
        assert module.count(") -> Any:") == 5
        assert "PostsGetQueryReturns" not in module

    def test_compiles_all_modes(self):
        for mode in ("pydantic", "typeddict", "any"):
            files = self._tree(mode)
            for path, content in files.items():
                compile(content, path, "exec")
