"""Tests for config.py — pyproject.toml configuration loading."""

from __future__ import annotations

from pathlib import Path

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
        )
        cfg = load_config(tmp_path)
        assert cfg.convex_dir == (tmp_path / "convex").resolve()
        assert cfg.output_dir == (tmp_path / "src/gen").resolve()
        assert cfg.input_json == (tmp_path / "schema.json").resolve()
        assert cfg.format is False
        assert cfg.output_mode == "tree"

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
