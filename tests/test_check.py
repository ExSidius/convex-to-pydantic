"""Tests for --check mode (dry-run validation)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import typer

from convex_to_pydantic.cli import _format_string, _run_check
from convex_to_pydantic.pipeline import transform

FIXTURES = Path(__file__).parent / "fixtures"


def _write_fixture_output(fixture: str, output_dir: Path) -> None:
    """Generate and write output files for a fixture, formatted."""
    blob = json.loads((FIXTURES / fixture).read_text())
    generated = transform(blob)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "_types.py").write_text(_format_string(generated.types_content))
    (output_dir / "_client.py").write_text(_format_string(generated.client_content))


class TestCheck:
    def test_up_to_date(self, tmp_path: Path):
        """Check passes when files match."""
        _write_fixture_output("chat_app.json", tmp_path)
        with pytest.raises(typer.Exit) as exc_info:
            _run_check(
                None,
                FIXTURES / "chat_app.json",
                tmp_path,
            )
        assert exc_info.value.exit_code == 0

    def test_stale_types(self, tmp_path: Path):
        """Check fails when _types.py is modified."""
        _write_fixture_output("chat_app.json", tmp_path)
        # Corrupt _types.py
        types_path = tmp_path / "_types.py"
        types_path.write_text("# stale\n")
        with pytest.raises(typer.Exit) as exc_info:
            _run_check(
                None,
                FIXTURES / "chat_app.json",
                tmp_path,
            )
        assert exc_info.value.exit_code == 1

    def test_stale_client(self, tmp_path: Path):
        """Check fails when _client.py is modified."""
        _write_fixture_output("chat_app.json", tmp_path)
        (tmp_path / "_client.py").write_text("# stale\n")
        with pytest.raises(typer.Exit) as exc_info:
            _run_check(
                None,
                FIXTURES / "chat_app.json",
                tmp_path,
            )
        assert exc_info.value.exit_code == 1

    def test_missing_files(self, tmp_path: Path):
        """Check fails when files don't exist."""
        with pytest.raises(typer.Exit) as exc_info:
            _run_check(
                None,
                FIXTURES / "chat_app.json",
                tmp_path,
            )
        assert exc_info.value.exit_code == 1


class TestFormatString:
    def test_formats_python(self):
        raw = "x=1\n"
        formatted = _format_string(raw)
        assert formatted == "x = 1\n"

    def test_identity_on_already_formatted(self):
        code = "x = 1\n"
        assert _format_string(code) == code
