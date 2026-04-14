"""Step 3 of 3: end-to-end Convex source → Python.

Chains the two halves we test independently elsewhere:

    step 1: Convex source tree → JSON blob   (test_extractor.py)
    step 2: JSON blob → Python file contents (test_pipeline.py, etc.)
    step 3: Convex source tree → Python      (this file)

Step 3 exists because shape-level agreement between the two halves isn't
the same as behavioral agreement: the extractor can produce JSON that
passes its own assertions yet trips the converter's parser, or miss a
field the codegen downstream assumes is present. These tests run the real
extractor against real fixtures, pipe the result straight through
``transform()``, and check the resulting Python compiles and contains the
expected Pydantic models / client wrappers.

They don't re-assert everything that test_extractor.py or test_pipeline.py
already cover — just enough to prove the seam between the two halves is
intact.
"""

from __future__ import annotations

import ast

import pytest

from convex_to_pydantic.pipeline import GeneratedFiles, transform


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _compile_and_parse(source: str, filename: str) -> ast.Module:
    """Assert the generated source compiles AND return the parsed AST
    so tests can assert on declared names without executing the module
    (execution would require the real convex-to-pydantic runtime client)."""
    compile(source, filename, "exec")
    return ast.parse(source, filename)


def _top_level_names(tree: ast.Module) -> set[str]:
    """All top-level `class Foo` and `def foo` / `async def foo` names."""
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
    return names


def _extract_and_transform(fixture_dir, run_extractor) -> GeneratedFiles:
    blob = run_extractor(fixture_dir)
    return transform(blob)


# ---------------------------------------------------------------------------
# basic/
# ---------------------------------------------------------------------------


@pytest.mark.requires_pnpm
class TestBasicEndToEnd:
    def test_produces_generated_files(self, prepared_fixture, run_extractor):
        fixture = prepared_fixture("basic")
        result = _extract_and_transform(fixture, run_extractor)
        assert result.num_tables == 1
        assert result.num_functions == 2

    def test_types_py_compiles(self, prepared_fixture, run_extractor):
        fixture = prepared_fixture("basic")
        result = _extract_and_transform(fixture, run_extractor)
        _compile_and_parse(result.types_content, "_types.py")

    def test_client_py_compiles(self, prepared_fixture, run_extractor):
        fixture = prepared_fixture("basic")
        result = _extract_and_transform(fixture, run_extractor)
        _compile_and_parse(result.client_content, "_client.py")

    def test_types_contains_messages_model(self, prepared_fixture, run_extractor):
        """The `messages` table should turn into a Pydantic model class."""
        fixture = prepared_fixture("basic")
        result = _extract_and_transform(fixture, run_extractor)
        tree = _compile_and_parse(result.types_content, "_types.py")
        names = _top_level_names(tree)
        # The namer may prefix / pluralize; we just assert some Messages-like
        # identifier made it through.
        assert any("Message" in n for n in names), (
            f"No Message-ish class in generated types. Got: {sorted(names)}"
        )

    def test_client_references_messages_module(self, prepared_fixture, run_extractor):
        """The client file must reference the `messages` module path so
        calls route correctly."""
        fixture = prepared_fixture("basic")
        result = _extract_and_transform(fixture, run_extractor)
        # `messages:list` or `"messages/list"` depending on how the client
        # spells it — check both forms.
        body = result.client_content
        assert "messages" in body, body[:400]


# ---------------------------------------------------------------------------
# nested/
# ---------------------------------------------------------------------------


@pytest.mark.requires_pnpm
class TestNestedEndToEnd:
    def test_counts_match_fixture(self, prepared_fixture, run_extractor):
        fixture = prepared_fixture("nested")
        result = _extract_and_transform(fixture, run_extractor)
        assert result.num_tables == 3
        assert result.num_functions == 10

    def test_single_mode_compiles(self, prepared_fixture, run_extractor):
        fixture = prepared_fixture("nested")
        result = _extract_and_transform(fixture, run_extractor)
        _compile_and_parse(result.types_content, "_types.py")
        _compile_and_parse(result.client_content, "_client.py")

    def test_tree_mode_compiles(self, prepared_fixture, run_extractor):
        """Tree mode emits one Python file per Convex module. Every
        generated file must compile — otherwise the extractor produced
        something the codegen layer can't handle."""
        fixture = prepared_fixture("nested")
        blob = run_extractor(fixture)
        result = transform(blob, output_mode="tree")
        assert result.tree_files, "tree mode produced no files"
        for relpath, content in result.tree_files.items():
            _compile_and_parse(content, relpath)

    def test_tree_mirrors_module_paths(self, prepared_fixture, run_extractor):
        """Tree-mode output paths mirror the Convex module hierarchy: the
        nested fixture's `admin/analytics/reports` should produce
        `admin/analytics/reports.py`."""
        fixture = prepared_fixture("nested")
        blob = run_extractor(fixture)
        result = transform(blob, output_mode="tree")
        assert "admin/analytics/reports.py" in result.tree_files
        assert "calendars/events/eventCrud.py" in result.tree_files
        assert "api/v1/webhooks.py" in result.tree_files

    def test_same_name_modules_do_not_collide(self, prepared_fixture, run_extractor):
        """`users.ts` at root and `admin/users.ts` must survive all the
        way to Python as distinct modules, not a single merged file."""
        fixture = prepared_fixture("nested")
        blob = run_extractor(fixture)
        result = transform(blob, output_mode="tree")
        assert "users.py" in result.tree_files
        assert "admin/users.py" in result.tree_files
        # And the root users.py must contain a `get`-ish wrapper, not the
        # `ban`-ish one, and vice versa.
        assert "ban" not in result.tree_files["users.py"]
        assert "ban" in result.tree_files["admin/users.py"]


# ---------------------------------------------------------------------------
# mixed_js_ts/
# ---------------------------------------------------------------------------


@pytest.mark.requires_pnpm
class TestMixedJsTsEndToEnd:
    def test_counts_match_fixture(self, prepared_fixture, run_extractor):
        fixture = prepared_fixture("mixed_js_ts")
        result = _extract_and_transform(fixture, run_extractor)
        assert result.num_tables == 1  # invoices
        assert result.num_functions == 4

    def test_compiles(self, prepared_fixture, run_extractor):
        fixture = prepared_fixture("mixed_js_ts")
        result = _extract_and_transform(fixture, run_extractor)
        _compile_and_parse(result.types_content, "_types.py")
        _compile_and_parse(result.client_content, "_client.py")

    def test_tree_mode_handles_js_at_depth(self, prepared_fixture, run_extractor):
        """A `.js` file at `reports/legacy/v1.js` must end up as
        `reports/legacy/v1.py` in tree mode (same as a `.ts` equivalent)."""
        fixture = prepared_fixture("mixed_js_ts")
        blob = run_extractor(fixture)
        result = transform(blob, output_mode="tree")
        assert "reports/legacy/v1.py" in result.tree_files
        for relpath, content in result.tree_files.items():
            _compile_and_parse(content, relpath)


# ---------------------------------------------------------------------------
# excluded/
# ---------------------------------------------------------------------------


@pytest.mark.requires_pnpm
class TestExcludedEndToEnd:
    def test_only_kept_modules_surface_in_python(
        self, prepared_fixture, run_extractor
    ):
        fixture = prepared_fixture("excluded")
        blob = run_extractor(fixture)
        result = transform(blob, output_mode="tree")
        assert "real.py" in result.tree_files
        assert "admin/visible.py" in result.tree_files
        assert "admin/nested/final.py" in result.tree_files

    def test_excluded_modules_not_in_output(self, prepared_fixture, run_extractor):
        fixture = prepared_fixture("excluded")
        blob = run_extractor(fixture)
        result = transform(blob, output_mode="tree")
        # A leaked `_private` / `http` / etc. module would appear as a
        # file here.
        for forbidden in (
            "http.py",
            "crons.py",
            "schema.py",
            "auth.config.py",
            "convex.config.py",
            "_private.py",
            "helpers.py",
            "admin/_secret.py",
            "admin/nested/_draft.py",
        ):
            assert forbidden not in result.tree_files, (
                f"Excluded module leaked into tree output: {forbidden}"
            )


# ---------------------------------------------------------------------------
# internal_functions/
# ---------------------------------------------------------------------------


@pytest.mark.requires_pnpm
class TestInternalFunctionsEndToEnd:
    def test_only_public_function_in_generated_python(
        self, prepared_fixture, run_extractor
    ):
        fixture = prepared_fixture("internal_functions")
        result = _extract_and_transform(fixture, run_extractor)
        assert result.num_functions == 1

        # Internal function names must not leak into the client module.
        # `process` and `fetch` are the internal mutation/query names.
        body = result.client_content
        # `enqueue` is the public one; it should appear.
        assert "enqueue" in body
        # The `jobs/secret` module should not have contributed anything.
        assert "jobs/secret" not in body
        assert "jobs.secret" not in body


# ---------------------------------------------------------------------------
# Parity under the anyApi-stub swap (requires docker)
# ---------------------------------------------------------------------------


@pytest.mark.requires_docker
@pytest.mark.requires_pnpm
class TestStubAndConcreteEndToEndParity:
    """The generated Python must be identical whether the fixture's
    `_generated/api.js` is Convex's `anyApi` stub (user hasn't run
    `convex dev`) or the concrete post-deploy file. This test is the
    closest thing we have to "full reproduction of the reported bug"."""

    def test_basic_python_identical_stub_vs_concrete(
        self, deployed_fixture, run_extractor, with_anyapi_stub
    ):
        fixture = deployed_fixture("basic")
        concrete = _extract_and_transform(fixture, run_extractor)
        with with_anyapi_stub(fixture):
            stub = _extract_and_transform(fixture, run_extractor)
        assert concrete.num_functions == stub.num_functions
        assert concrete.num_tables == stub.num_tables
        assert concrete.types_content == stub.types_content
        assert concrete.client_content == stub.client_content
