"""Load configuration from pyproject.toml [tool.convex-to-pydantic].

Pure module — load_config() reads a file and returns a frozen dataclass.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    """Resolved configuration with ``None`` for unset values."""

    convex_dir: Path | None = None
    output_dir: Path | None = None
    input_json: Path | None = None
    format: bool = True
    output_mode: str = "single"


def load_config(start_dir: Path | None = None) -> Config:
    """Walk up from *start_dir* to find ``pyproject.toml`` and parse our section.

    Returns a :class:`Config` with defaults for any missing keys.
    """
    start = (start_dir or Path.cwd()).resolve()
    toml_path = _find_pyproject(start)
    if toml_path is None:
        return Config()

    with toml_path.open("rb") as f:
        data = tomllib.load(f)

    section = data.get("tool", {}).get("convex-to-pydantic", {})
    if not section:
        return Config()

    root = toml_path.parent
    return Config(
        convex_dir=_resolve_path(root, section.get("convex_dir")),
        output_dir=_resolve_path(root, section.get("output_dir")),
        input_json=_resolve_path(root, section.get("input")),
        format=section.get("format", True),
        output_mode=section.get("output_mode", "single"),
    )


def _find_pyproject(start: Path) -> Path | None:
    """Walk up from *start* looking for ``pyproject.toml``."""
    current = start
    while True:
        candidate = current / "pyproject.toml"
        if candidate.is_file():
            return candidate
        parent = current.parent
        if parent == current:
            return None
        current = parent


def _resolve_path(root: Path, value: str | None) -> Path | None:
    if value is None:
        return None
    p = Path(value)
    if p.is_absolute():
        return p
    return (root / p).resolve()
