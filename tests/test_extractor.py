"""Step 1 of 3: extractor correctness.

These tests invoke the bundled Node.js extractor (``schema_export.mjs``) as
a subprocess against real Convex project fixtures under
``tests/fixtures/convex_projects/`` and assert on the shape of the JSON
blob it emits.

They are the front half of the pipeline: Convex source tree → JSON.

The mirror tests live in:
- ``test_pipeline.py`` / ``test_converter.py`` / ``test_codegen.py`` — step
  2 (JSON → Python), driven off hand-curated JSON fixtures.
- ``test_end_to_end.py`` — step 3 (Convex source → Python), which runs
  this extractor and pipes the result through ``transform()``.

Two scenarios per fixture:

1. **Pre-deploy (``anyApi`` stub).** The fixture's checked-in
   ``_generated/api.js`` just re-exports ``anyApi`` — the exact state a
   user is in before running ``npx convex dev``. This is the bug we're
   fixing: the old extractor saw no concrete function references and
   returned empty. The new filesystem-walk extractor must find everything.

2. **Post-deploy (concrete api).** Uses the ``deployed_fixture`` factory
   to actually deploy the fixture to a self-hosted Convex backend running
   in Docker, producing an authentic concrete ``_generated/api.js``.
   We then run the extractor and verify it produces the same functions.
   Requires docker. Auto-skipped otherwise via ``requires_docker``.
"""

from __future__ import annotations

import json

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fn_key(entry: dict) -> tuple[str, str]:
    return (entry["module"], entry["name"])


def _fn_keys(blob: dict) -> set[tuple[str, str]]:
    return {_fn_key(f) for f in blob["functions"]}


def _fn_by_key(blob: dict, module: str, name: str) -> dict:
    for f in blob["functions"]:
        if f["module"] == module and f["name"] == name:
            return f
    raise AssertionError(
        f"No function {module}.{name} in output. Present: "
        f"{sorted(_fn_keys(blob))}"
    )


def _table_names(blob: dict) -> set[str]:
    return {t["tableName"] for t in blob["tables"]}


# ---------------------------------------------------------------------------
# basic/ — the primary red test
# ---------------------------------------------------------------------------


@pytest.mark.requires_pnpm
class TestBasicFixture:
    """`basic/` has one module, two functions, one table. Baseline sanity."""

    def test_emits_two_functions(self, prepared_fixture, run_extractor):
        fixture = prepared_fixture("basic")
        blob = run_extractor(fixture)
        assert _fn_keys(blob) == {("messages", "list"), ("messages", "send")}

    def test_function_types_are_correct(self, prepared_fixture, run_extractor):
        fixture = prepared_fixture("basic")
        blob = run_extractor(fixture)
        assert _fn_by_key(blob, "messages", "list")["type"] == "query"
        assert _fn_by_key(blob, "messages", "send")["type"] == "mutation"

    def test_send_args_extracted(self, prepared_fixture, run_extractor):
        """`send` declares `{ body: string, author: string }` in convex/values;
        extractor must surface both field names with string types."""
        fixture = prepared_fixture("basic")
        blob = run_extractor(fixture)
        args = _fn_by_key(blob, "messages", "send")["args"]
        assert args["type"] == "object"
        fields = args["value"]
        assert set(fields.keys()) == {"body", "author"}
        for name in ("body", "author"):
            assert fields[name]["fieldType"]["type"] == "string"

    def test_list_args_are_empty_object(self, prepared_fixture, run_extractor):
        fixture = prepared_fixture("basic")
        blob = run_extractor(fixture)
        args = _fn_by_key(blob, "messages", "list")["args"]
        assert args["type"] == "object"
        assert args["value"] == {}

    def test_messages_table_extracted(self, prepared_fixture, run_extractor):
        fixture = prepared_fixture("basic")
        blob = run_extractor(fixture)
        assert _table_names(blob) == {"messages"}
        messages = next(t for t in blob["tables"] if t["tableName"] == "messages")
        assert messages["documentType"]["type"] == "object"
        fields = messages["documentType"]["value"]
        assert set(fields.keys()) == {"body", "author"}


# ---------------------------------------------------------------------------
# nested/ — deep tree, mixed types, same-name disambiguation
# ---------------------------------------------------------------------------


@pytest.mark.requires_pnpm
class TestNestedFixture:
    """The `nested/` fixture is the integration heart of the test suite.
    It exercises: depth ≥ 3, forward-slash module paths on every platform,
    same-name files in different directories, and all three function types."""

    EXPECTED = {
        ("users", "get"): "query",
        ("users", "update"): "mutation",
        ("chat/messages", "list"): "query",
        ("chat/messages", "send"): "mutation",
        ("calendars/events/eventCrud", "list"): "query",
        ("calendars/events/eventCrud", "create"): "mutation",
        ("admin/users", "ban"): "mutation",
        ("admin/analytics/reports", "daily"): "query",
        ("admin/analytics/reports", "exportCsv"): "action",
        ("api/v1/webhooks", "stripe"): "action",
    }

    def test_all_expected_functions_discovered(self, prepared_fixture, run_extractor):
        fixture = prepared_fixture("nested")
        blob = run_extractor(fixture)
        assert _fn_keys(blob) == set(self.EXPECTED.keys())

    def test_function_types_match(self, prepared_fixture, run_extractor):
        fixture = prepared_fixture("nested")
        blob = run_extractor(fixture)
        for (mod, name), expected_type in self.EXPECTED.items():
            entry = _fn_by_key(blob, mod, name)
            assert entry["type"] == expected_type, (
                f"{mod}.{name}: expected {expected_type}, got {entry['type']}"
            )

    def test_module_paths_use_forward_slash(self, prepared_fixture, run_extractor):
        """Even on Windows, module paths must use `/`. We can't exercise
        Windows in CI but we can prove no backslash ever appears in output."""
        fixture = prepared_fixture("nested")
        blob = run_extractor(fixture)
        for f in blob["functions"]:
            assert "\\" not in f["module"], f
        assert ("chat/messages", "list") in _fn_keys(blob)
        assert ("api/v1/webhooks", "stripe") in _fn_keys(blob)

    def test_depth_three_resolved(self, prepared_fixture, run_extractor):
        """Both `calendars/events/eventCrud` and `admin/analytics/reports`
        and `api/v1/webhooks` are depth-3 module paths."""
        fixture = prepared_fixture("nested")
        blob = run_extractor(fixture)
        keys = _fn_keys(blob)
        assert ("calendars/events/eventCrud", "create") in keys
        assert ("admin/analytics/reports", "exportCsv") in keys
        assert ("api/v1/webhooks", "stripe") in keys

    def test_same_name_different_dirs_not_merged(self, prepared_fixture, run_extractor):
        """`users.ts` at the root and `admin/users.ts` must appear as
        distinct module paths."""
        fixture = prepared_fixture("nested")
        blob = run_extractor(fixture)
        keys = _fn_keys(blob)
        assert ("users", "get") in keys
        assert ("users", "update") in keys
        assert ("admin/users", "ban") in keys
        # Sanity: `ban` must NOT collapse onto root `users.ts`.
        assert ("users", "ban") not in keys

    def test_all_three_function_types_present(self, prepared_fixture, run_extractor):
        fixture = prepared_fixture("nested")
        blob = run_extractor(fixture)
        types = {f["type"] for f in blob["functions"]}
        assert types == {"query", "mutation", "action"}

    def test_non_convex_helpers_ignored(self, prepared_fixture, run_extractor):
        """`users.ts` exports a plain `formatUserName` helper in addition
        to the Convex functions. Helpers must not appear in output."""
        fixture = prepared_fixture("nested")
        blob = run_extractor(fixture)
        names_in_users = {n for (m, n) in _fn_keys(blob) if m == "users"}
        assert names_in_users == {"get", "update"}
        assert "formatUserName" not in names_in_users

    def test_schema_tables_complete(self, prepared_fixture, run_extractor):
        fixture = prepared_fixture("nested")
        blob = run_extractor(fixture)
        assert _table_names(blob) == {"users", "messages", "events"}


# ---------------------------------------------------------------------------
# mixed_js_ts/ — both extensions discoverable
# ---------------------------------------------------------------------------


@pytest.mark.requires_pnpm
class TestMixedJsTsFixture:
    """Prove `.ts` and `.js` files produce identical output shape. Both must
    be discovered even when mixed in the same tree."""

    def test_both_extensions_discovered(self, prepared_fixture, run_extractor):
        fixture = prepared_fixture("mixed_js_ts")
        blob = run_extractor(fixture)
        assert _fn_keys(blob) == {
            ("legacy", "migrate"),  # .js at root
            ("billing/stripe", "checkout"),  # .ts nested
            ("billing/invoices", "list"),  # .js nested
            ("reports/legacy/v1", "snapshot"),  # .js at depth 2
        }

    def test_js_output_shape_matches_ts(self, prepared_fixture, run_extractor):
        """A .js-defined function's entry has the same shape as a .ts one:
        same keys, same args structure."""
        fixture = prepared_fixture("mixed_js_ts")
        blob = run_extractor(fixture)
        ts_entry = _fn_by_key(blob, "billing/stripe", "checkout")
        js_entry = _fn_by_key(blob, "billing/invoices", "list")
        assert set(ts_entry.keys()) == set(js_entry.keys())
        assert set(ts_entry["args"].keys()) == set(js_entry["args"].keys())


# ---------------------------------------------------------------------------
# excluded/ — only the three keeper files survive
# ---------------------------------------------------------------------------


@pytest.mark.requires_pnpm
class TestExcludedFixture:
    def test_only_kept_files_appear(self, prepared_fixture, run_extractor):
        fixture = prepared_fixture("excluded")
        blob = run_extractor(fixture)
        assert _fn_keys(blob) == {
            ("real", "doThing"),
            ("admin/visible", "ping"),
            ("admin/nested/final", "ship"),
        }

    @pytest.mark.parametrize(
        "excluded_entry",
        [
            "schema",
            "http",
            "crons",
            "auth.config",
            "convex.config",
            "_private",
            "admin/_secret",
            "admin/nested/_draft",
        ],
    )
    def test_excluded_modules_absent(
        self, prepared_fixture, run_extractor, excluded_entry
    ):
        """None of schema/http/crons/dotted-config/underscore-prefixed files
        should appear as a module in the output."""
        fixture = prepared_fixture("excluded")
        blob = run_extractor(fixture)
        modules = {f["module"] for f in blob["functions"]}
        assert excluded_entry not in modules

    def test_helpers_file_scanned_but_yields_nothing(
        self, prepared_fixture, run_extractor
    ):
        """`helpers.ts` is NOT excluded — it's walked, but since it has no
        Convex functions, it contributes zero entries."""
        fixture = prepared_fixture("excluded")
        blob = run_extractor(fixture)
        modules = {f["module"] for f in blob["functions"]}
        assert "helpers" not in modules


# ---------------------------------------------------------------------------
# internal_functions/ — internals filtered out
# ---------------------------------------------------------------------------


@pytest.mark.requires_pnpm
class TestInternalFunctionsFixture:
    def test_only_public_mutation_visible(self, prepared_fixture, run_extractor):
        fixture = prepared_fixture("internal_functions")
        blob = run_extractor(fixture)
        assert _fn_keys(blob) == {("jobs/public", "enqueue")}

    def test_internal_mutation_not_present(self, prepared_fixture, run_extractor):
        fixture = prepared_fixture("internal_functions")
        blob = run_extractor(fixture)
        keys = _fn_keys(blob)
        assert ("jobs/secret", "process") not in keys
        assert ("jobs/secret", "fetch") not in keys


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


@pytest.mark.requires_pnpm
class TestDeterminism:
    """Two consecutive runs against the same fixture must produce byte-identical
    JSON. The extractor sorts functions by (module, name) and tables by
    tableName; this test proves the sort is actually applied."""

    def test_basic_is_deterministic(self, prepared_fixture, run_extractor):
        fixture = prepared_fixture("basic")
        a = run_extractor(fixture)
        b = run_extractor(fixture)
        assert json.dumps(a, sort_keys=False) == json.dumps(b, sort_keys=False)

    def test_nested_is_deterministic(self, prepared_fixture, run_extractor):
        fixture = prepared_fixture("nested")
        a = run_extractor(fixture)
        b = run_extractor(fixture)
        assert json.dumps(a, sort_keys=False) == json.dumps(b, sort_keys=False)

    def test_functions_are_sorted(self, prepared_fixture, run_extractor):
        fixture = prepared_fixture("nested")
        blob = run_extractor(fixture)
        keys = [(f["module"], f["name"]) for f in blob["functions"]]
        assert keys == sorted(keys)

    def test_tables_are_sorted(self, prepared_fixture, run_extractor):
        fixture = prepared_fixture("nested")
        blob = run_extractor(fixture)
        names = [t["tableName"] for t in blob["tables"]]
        assert names == sorted(names)


# ---------------------------------------------------------------------------
# Robustness: a broken module must not abort the whole extraction
# ---------------------------------------------------------------------------


@pytest.mark.requires_pnpm
class TestBrokenModuleRobustness:
    """If one file has a syntax error (user mid-edit), the extractor must
    warn to stderr and still emit the other functions. Otherwise a single
    bad save blocks the whole codegen pass."""

    def test_broken_ts_module_skipped_with_warning(
        self, prepared_fixture, run_extractor_raw, tmp_path
    ):
        fixture_src = prepared_fixture("basic")
        # Copy fixture to tmp so we can inject a broken file without
        # polluting the shared fixture dir.
        import shutil

        fixture_dir = tmp_path / "basic"
        shutil.copytree(fixture_src, fixture_dir, symlinks=True)
        broken = fixture_dir / "convex" / "broken.ts"
        broken.write_text("this is not valid typescript !!! === @@@\n")

        res = run_extractor_raw(fixture_dir)
        assert res.returncode == 0, (
            f"Extractor exited {res.returncode}; stderr:\n{res.stderr}"
        )
        blob = json.loads(res.stdout)
        # The good module's functions still surface.
        assert ("messages", "list") in _fn_keys(blob)
        assert ("messages", "send") in _fn_keys(blob)
        # And a warning mentioning the broken file was printed.
        assert "broken" in res.stderr.lower()


# ---------------------------------------------------------------------------
# CLI sanity: the extractor errors cleanly when --convex-dir is missing
# ---------------------------------------------------------------------------


class TestCliSanity:
    """These tests don't need any fixture installed — they just exercise
    the extractor's CLI error paths."""

    def test_missing_convex_dir_arg_exits_nonzero(self, run_extractor_raw, tmp_path):
        # Point at a nonexistent dir to exercise the existence check.
        res = run_extractor_raw(tmp_path / "does-not-exist")
        assert res.returncode != 0
        assert "convex directory not found" in res.stderr.lower()


# ---------------------------------------------------------------------------
# Stub-vs-concrete parity (requires docker)
# ---------------------------------------------------------------------------


@pytest.mark.requires_docker
@pytest.mark.requires_pnpm
class TestStubAndConcreteParity:
    """The whole point of the rewrite: the extractor must produce the same
    functions whether or not `npx convex deploy` has run. We prove it by
    deploying the fixture (producing a concrete `_generated/api.js`), then
    swapping the pre-deploy `anyApi` stub back in, running the extractor
    against both, and comparing."""

    def test_stub_and_concrete_match_on_basic(
        self, deployed_fixture, run_extractor, with_anyapi_stub
    ):
        fixture = deployed_fixture("basic")

        concrete = run_extractor(fixture)
        with with_anyapi_stub(fixture):
            stub = run_extractor(fixture)

        # The concrete vs. stub comparison is function-set + table-set
        # parity. (Some internal args-validator representation could
        # technically differ across versions; the functions/tables surface
        # is the invariant users depend on.)
        assert _fn_keys(concrete) == _fn_keys(stub)
        assert _table_names(concrete) == _table_names(stub)

    def test_stub_and_concrete_match_on_nested(
        self, deployed_fixture, run_extractor, with_anyapi_stub
    ):
        fixture = deployed_fixture("nested")
        concrete = run_extractor(fixture)
        with with_anyapi_stub(fixture):
            stub = run_extractor(fixture)
        assert _fn_keys(concrete) == _fn_keys(stub)
        assert _table_names(concrete) == _table_names(stub)
