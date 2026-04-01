"""CLI entry point — the thin IO shell.

All business logic lives in pipeline.py (pure). This module only handles:
- Argument parsing (typer)
- File IO (read JSON, write generated files)
- Subprocess calls (ruff formatting)
- Console output + watch-mode status reporting
"""

from __future__ import annotations

import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Optional

import typer

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


def _write_generated(output_dir: Path, generated: GeneratedFiles) -> None:
    """Write generated files and optionally format with ruff."""
    output_dir.mkdir(parents=True, exist_ok=True)

    types_path = output_dir / "_types.py"
    client_path = output_dir / "_client.py"

    types_path.write_text(generated.types_content)
    client_path.write_text(generated.client_content)

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
                regenerated=False, skipped_at="source_hash",
                num_tables=0, num_functions=0,
                extract_ms=0, transform_ms=0,
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
            regenerated=False, skipped_at="blob_hash",
            num_tables=0, num_functions=0,
            extract_ms=extract_ms, transform_ms=0,
            total_ms=_elapsed_ms(t_start),
        )

    # Pure transform
    t_transform = time.monotonic()
    generated = transform(blob)
    transform_ms = _elapsed_ms(t_transform)

    # Write files
    _write_generated(output_dir, generated)

    # Update hashes
    if source_digest is None and convex_dir:
        source_files = collect_source_files(convex_dir)
        source_digest = files_hash(source_files)
    write_stored_hashes(output_dir, source_digest or "", new_blob_hash)

    return PipelineResult(
        regenerated=True, skipped_at="",
        num_tables=generated.num_tables,
        num_functions=generated.num_functions,
        extract_ms=extract_ms, transform_ms=transform_ms,
        total_ms=_elapsed_ms(t_start),
    )


def _elapsed_ms(start: float) -> float:
    return (time.monotonic() - start) * 1000


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
            exists=True,
            file_okay=False,
            help="Path to your Convex directory (e.g. ./convex).",
        ),
    ] = None,
    input_json: Annotated[
        Optional[Path],
        typer.Option(
            "--input",
            exists=True,
            dir_okay=False,
            help="Path to a pre-exported JSON file (alternative to --convex-dir).",
        ),
    ] = None,
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            help="Directory to write _types.py and _client.py.",
        ),
    ] = ...,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Regenerate even if schema is unchanged."),
    ] = False,
) -> None:
    """Generate Pydantic models from Convex schema."""
    result = _run_pipeline(convex_dir, input_json, output_dir, force=force)
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
        Path,
        typer.Option(
            "--convex-dir",
            exists=True,
            file_okay=False,
            help="Path to your Convex directory (e.g. ./convex).",
        ),
    ] = ...,
    output_dir: Annotated[
        Path,
        typer.Option(
            "--output-dir",
            help="Directory to write _types.py and _client.py.",
        ),
    ] = ...,
) -> None:
    """Watch Convex directory and regenerate on changes."""
    from .watcher import watch as do_watch

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
        except Exception as e:
            typer.echo(f"  Error: {e}", err=True)

    do_watch(convex_dir, on_change)


def main() -> None:
    app()
