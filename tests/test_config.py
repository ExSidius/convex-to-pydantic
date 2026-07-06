"""Tests for config.py — pyproject.toml configuration loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from convex_to_pydantic.config import Config, load_config


class TestLoadConfig:
    def test_no_pyproject(self, tmp_path: Path):
        """Returns defaults when no pyproject.toml exists."""
        cfg = load_config(tmp_path)
        assert cfg == Config()

    def test_pyproject_without_section(self, tmp_path: Path):
        """Returns defaults when pyproject.toml has no [tool.convex-to-pydantic]."""
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "foo"\n')
        cfg = load_config(tmp_path)
        assert cfg == Config()

    def test_full_config(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text(
            "[tool.convex-to-pydantic]\n"
            'convex_dir = "./convex"\n'
            'output_dir = "./src/gen"\n'
            'input = "./schema.json"\n'
            "format = false\n"
            'output_mode = "tree"\n'
            'client_style = "sync"\n'
        )
        cfg = load_config(tmp_path)
        assert cfg.convex_dir == (tmp_path / "convex").resolve()
        assert cfg.output_dir == (tmp_path / "src/gen").resolve()
        assert cfg.input_json == (tmp_path / "schema.json").resolve()
        assert cfg.format is False
        assert cfg.output_mode == "tree"
        assert cfg.client_style == "sync"

    def test_client_style_defaults_to_async(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text(
            '[tool.convex-to-pydantic]\noutput_dir = "./out"\n'
        )
        cfg = load_config(tmp_path)
        assert cfg.client_style == "async"

    def test_client_style_invalid_raises(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text(
            '[tool.convex-to-pydantic]\nclient_style = "threaded"\n'
        )
        with pytest.raises(ValueError, match="client_style"):
            load_config(tmp_path)

    def test_partial_config(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text(
            '[tool.convex-to-pydantic]\noutput_dir = "./out"\n'
        )
        cfg = load_config(tmp_path)
        assert cfg.convex_dir is None
        assert cfg.output_dir == (tmp_path / "out").resolve()
        assert cfg.input_json is None
        assert cfg.format is True

    def test_walks_up_directories(self, tmp_path: Path):
        """Config is found in a parent directory."""
        (tmp_path / "pyproject.toml").write_text(
            '[tool.convex-to-pydantic]\noutput_dir = "./gen"\n'
        )
        subdir = tmp_path / "src" / "deep"
        subdir.mkdir(parents=True)
        cfg = load_config(subdir)
        assert cfg.output_dir == (tmp_path / "gen").resolve()

    def test_defaults(self):
        cfg = Config()
        assert cfg.convex_dir is None
        assert cfg.output_dir is None
        assert cfg.input_json is None
        assert cfg.format is True
        assert cfg.output_mode == "single"
        assert cfg.client_style == "async"
        assert cfg.return_type == "pydantic"

    def test_return_type_defaults_to_pydantic(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text(
            '[tool.convex-to-pydantic]\noutput_dir = "./out"\n'
        )
        cfg = load_config(tmp_path)
        assert cfg.return_type == "pydantic"

    def test_return_type_typeddict(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text(
            '[tool.convex-to-pydantic]\noutput_dir = "./out"\nreturn_type = "typeddict"\n'
        )
        cfg = load_config(tmp_path)
        assert cfg.return_type == "typeddict"

    def test_return_type_any(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text(
            '[tool.convex-to-pydantic]\noutput_dir = "./out"\nreturn_type = "any"\n'
        )
        cfg = load_config(tmp_path)
        assert cfg.return_type == "any"

    def test_return_type_invalid_raises(self, tmp_path: Path):
        (tmp_path / "pyproject.toml").write_text(
            '[tool.convex-to-pydantic]\nreturn_type = "magic"\n'
        )
        with pytest.raises(ValueError, match="return_type"):
            load_config(tmp_path)
