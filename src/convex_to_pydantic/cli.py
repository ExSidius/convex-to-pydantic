"""CLI entry point — the thin IO shell.

All business logic lives in pipeline.py (pure). This module only handles:
- Argument parsing (typer)
- File IO (read JSON, write generated files)
- Subprocess calls (ruff formatting)
- Console output + watch-mode status reporting
"""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Optional

import typer

from .config import load_config
from .extractor.runner import extract, extract_from_json
from .hasher import (
    blob_hash,
    collect_source_files,
    files_hash,
    read_stored_hashes,
    write_stored_hashes,
)
from .pipeline import GeneratedFiles, transform

app = typer.Typer(
    name="convex-to-pydantic",
    help="Pydantic codegen from Convex schemas.",
    no_args_is_help=True,
)


@dataclass(frozen=True)
class PipelineResult:
    """What happened during a pipeline run — for status reporting."""

    regenerated: bool
    skipped_at: str  # "source_hash" | "blob_hash" | "" (not skipped)
    num_tables: int
    num_functions: int
    extract_ms: float
    transform_ms: float
    total_ms: float


def _write_generated(
    output_dir: Path, generated: GeneratedFiles, *, do_format: bool = True
) -> None:
    """Write generated files and optionally format with ruff."""
    output_dir.mkdir(parents=True, exist_ok=True)

    if generated.tree_files:
        # Tree mode: write per-module files
        written_paths = []
        for rel_path, content in generated.tree_files.items():
            file_path = output_dir / rel_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content)
            written_paths.append(str(file_path))
        if do_format and written_paths:
            ruff = shutil.which("ruff")
            if ruff:
                subprocess.run(
                    [ruff, "format", *written_paths],
                    capture_output=True,
                    check=False,
                )
    else:
        # Single mode: write _types.py + _client.py
        types_path = output_dir / "_types.py"
        client_path = output_dir / "_client.py"

        types_path.write_text(generated.types_content)
        client_path.write_text(generated.client_content)

        if do_format:
            ruff = shutil.which("ruff")
            if ruff:
                subprocess.run(
                    [ruff, "format", str(types_path), str(client_path)],
                    capture_output=True,
                    check=False,
                )


def _run_pipeline(
    convex_dir: Path | None,
    input_json: Path | None,
    output_dir: Path,
    *,
    force: bool = False,
    do_format: bool = True,
    output_mode: str = "single",
) -> PipelineResult:
    """Run the full extraction → codegen pipeline."""
    t_start = time.monotonic()
    stored_source, stored_blob = read_stored_hashes(output_dir)

    # Layer 1: source-file hash (skip Node.js entirely)
    source_digest: str | None = None
    if convex_dir and not force:
        source_files = collect_source_files(convex_dir)
        source_digest = files_hash(source_files)
        if source_digest == stored_source:
            return PipelineResult(
                regenerated=False,
                skipped_at="source_hash",
                num_tables=0,
                num_functions=0,
                extract_ms=0,
                transform_ms=0,
                total_ms=_elapsed_ms(t_start),
            )

    # Extract
    t_extract = time.monotonic()
    if input_json:
        blob = extract_from_json(input_json)
    elif convex_dir:
        blob = extract(convex_dir)
    else:
        raise typer.BadParameter("Either --convex-dir or --input must be provided.")
    extract_ms = _elapsed_ms(t_extract)

    # Layer 2: blob hash (skip codegen)
    new_blob_hash = blob_hash(blob)
    if not force and new_blob_hash == stored_blob:
        if source_digest:
            write_stored_hashes(output_dir, source_digest, new_blob_hash)
        return PipelineResult(
            regenerated=False,
            skipped_at="blob_hash",
            num_tables=0,
            num_functions=0,
            extract_ms=extract_ms,
            transform_ms=0,
            total_ms=_elapsed_ms(t_start),
        )

    # Pure transform
    t_transform = time.monotonic()
    generated = transform(blob, output_mode=output_mode)
    transform_ms = _elapsed_ms(t_transform)

    # Write files
    _write_generated(output_dir, generated, do_format=do_format)

    # Update hashes
    if source_digest is None and convex_dir:
        source_files = collect_source_files(convex_dir)
        source_digest = files_hash(source_files)
    write_stored_hashes(output_dir, source_digest or "", new_blob_hash)

    return PipelineResult(
        regenerated=True,
        skipped_at="",
        num_tables=generated.num_tables,
        num_functions=generated.num_functions,
        extract_ms=extract_ms,
        transform_ms=transform_ms,
        total_ms=_elapsed_ms(t_start),
    )


def _format_string(content: str) -> str:
    """Format Python source code via ruff, falling back to identity."""
    ruff = shutil.which("ruff")
    if not ruff:
        return content
    result = subprocess.run(
        [ruff, "format", "--stdin-filename=_.py", "-"],
        input=content,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else content


def _elapsed_ms(start: float) -> float:
    return (time.monotonic() - start) * 1000


def _run_check(
    convex_dir: Path | None,
    input_json: Path | None,
    output_dir: Path,
    *,
    do_format: bool = True,
) -> None:
    """Check if generated files are up-to-date. Exits 0 if matching, 1 if stale."""
    # Extract
    if input_json:
        blob = extract_from_json(input_json)
    elif convex_dir:
        blob = extract(convex_dir)
    else:
        raise typer.BadParameter("Either --convex-dir or --input must be provided.")

    # Transform
    generated = transform(blob)

    # Format the generated content to match what _write_generated would produce
    expected_types = (
        _format_string(generated.types_content) if do_format else generated.types_content
    )
    expected_client = (
        _format_string(generated.client_content) if do_format else generated.client_content
    )

    # Compare to on-disk files
    types_path = output_dir / "_types.py"
    client_path = output_dir / "_client.py"

    if not types_path.exists() or not client_path.exists():
        typer.echo(
            "Generated files not found. Run 'convex-to-pydantic generate' first.",
            err=True,
        )
        raise typer.Exit(1)

    on_disk_types = types_path.read_text()
    on_disk_client = client_path.read_text()

    stale_files = []
    if on_disk_types != expected_types:
        stale_files.append("_types.py")
    if on_disk_client != expected_client:
        stale_files.append("_client.py")

    if stale_files:
        typer.echo(
            f"Out of date: {', '.join(stale_files)}. Run 'convex-to-pydantic generate' to update.",
            err=True,
        )
        raise typer.Exit(1)

    typer.echo("Generated files are up-to-date.")
    raise typer.Exit(0)


def _print_result(result: PipelineResult, output_dir: Path) -> None:
    """Print a human-friendly status line for a pipeline run."""
    if result.regenerated:
        typer.echo(
            f"  Generated _types.py + _client.py "
            f"({result.num_tables} table(s), {result.num_functions} function(s)) "
            f"in {result.total_ms:.0f}ms "
            f"[extract {result.extract_ms:.0f}ms, codegen {result.transform_ms:.0f}ms]"
        )
    elif result.skipped_at == "source_hash":
        typer.echo(f"  Skipped — source files unchanged ({result.total_ms:.0f}ms)")
    elif result.skipped_at == "blob_hash":
        typer.echo(
            f"  Skipped — schema unchanged after extraction "
            f"({result.total_ms:.0f}ms, extract {result.extract_ms:.0f}ms)"
        )


@app.command()
def generate(
    convex_dir: Annotated[
        Optional[Path],
        typer.Option(
            "--convex-dir",
            help="Path to your Convex directory (e.g. ./convex).",
        ),
    ] = None,
    input_json: Annotated[
        Optional[Path],
        typer.Option(
            "--input",
            help="Path to a pre-exported JSON file (alternative to --convex-dir).",
        ),
    ] = None,
    output_dir: Annotated[
        Optional[Path],
        typer.Option(
            "--output-dir",
            help="Directory to write _types.py and _client.py.",
        ),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Regenerate even if schema is unchanged."),
    ] = False,
    no_format: Annotated[
        bool,
        typer.Option("--no-format", help="Skip ruff formatting of generated files."),
    ] = False,
    check: Annotated[
        bool,
        typer.Option("--check", help="Check if generated files are up-to-date (exit 1 if stale)."),
    ] = False,
) -> None:
    """Generate Pydantic models from Convex schema."""
    cfg = load_config()
    convex_dir = convex_dir or cfg.convex_dir
    input_json = input_json or cfg.input_json
    output_dir = output_dir or cfg.output_dir
    do_format = cfg.format and not no_format

    output_mode = cfg.output_mode

    if output_dir is None:
        raise typer.BadParameter("--output-dir is required (or set output_dir in pyproject.toml).")

    if check:
        _run_check(convex_dir, input_json, output_dir, do_format=do_format)
        return

    result = _run_pipeline(
        convex_dir,
        input_json,
        output_dir,
        force=force,
        do_format=do_format,
        output_mode=output_mode,
    )
    if result.regenerated:
        typer.echo(f"Generated {output_dir / '_types.py'}")
        typer.echo(f"Generated {output_dir / '_client.py'}")
        typer.echo(
            f"  {result.num_tables} table(s), {result.num_functions} function(s) "
            f"in {result.total_ms:.0f}ms"
        )
    else:
        typer.echo("Schema unchanged, skipping regeneration. Use --force to override.")


@app.command()
def watch(
    convex_dir: Annotated[
        Optional[Path],
        typer.Option(
            "--convex-dir",
            help="Path to your Convex directory (e.g. ./convex).",
        ),
    ] = None,
    output_dir: Annotated[
        Optional[Path],
        typer.Option(
            "--output-dir",
            help="Directory to write _types.py and _client.py.",
        ),
    ] = None,
) -> None:
    """Watch Convex directory and regenerate on changes."""
    from .watcher import watch as do_watch

    cfg = load_config()
    convex_dir = convex_dir or cfg.convex_dir
    output_dir = output_dir or cfg.output_dir

    if convex_dir is None:
        raise typer.BadParameter("--convex-dir is required (or set convex_dir in pyproject.toml).")
    if output_dir is None:
        raise typer.BadParameter("--output-dir is required (or set output_dir in pyproject.toml).")

    typer.echo(f"Watching {convex_dir} for changes...")
    result = _run_pipeline(convex_dir, None, output_dir, force=True)
    _print_result(result, output_dir)
    typer.echo("Ready. Waiting for changes... (Ctrl-C to stop)\n")

    def on_change() -> None:
        ts = time.strftime("%H:%M:%S")
        typer.echo(f"[{ts}] Change detected")
        try:
            result = _run_pipeline(convex_dir, None, output_dir)
            _print_result(result, output_dir)
        except (OSError, json.JSONDecodeError, ValueError, RuntimeError) as e:
            typer.echo(f"  Error: {e}", err=True)

    do_watch(convex_dir, on_change)


def main() -> None:
    app()
