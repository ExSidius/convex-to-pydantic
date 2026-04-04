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
