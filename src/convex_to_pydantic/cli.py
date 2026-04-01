"""CLI entry point — the thin IO shell.

All business logic lives in pipeline.py (pure). This module only handles:
- Argument parsing (typer)
- File IO (read JSON, write generated files)
- Subprocess calls (ruff formatting)
- Console output
"""

from __future__ import annotations

import shutil
import subprocess
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
) -> bool:
    """Run the full extraction → codegen pipeline.

    Returns True if files were regenerated, False if skipped.
    """
    stored_source, stored_blob = read_stored_hashes(output_dir)

    # Pre-flight: check source files hash to avoid Node.js call
    source_digest: str | None = None
    if convex_dir and not force:
        source_files = collect_source_files(convex_dir)
        source_digest = files_hash(source_files)
        if source_digest == stored_source:
            return False

    # Extract
    if input_json:
        blob = extract_from_json(input_json)
    elif convex_dir:
        blob = extract(convex_dir)
    else:
        raise typer.BadParameter("Either --convex-dir or --input must be provided.")

    # Check blob hash
    new_blob_hash = blob_hash(blob)
    if not force and new_blob_hash == stored_blob:
        # Source files changed but extraction result is the same (e.g. comments only)
        if source_digest:
            write_stored_hashes(output_dir, source_digest, new_blob_hash)
        return False

    # Pure transform
    generated = transform(blob)

    # Write files (IO)
    _write_generated(output_dir, generated)

    # Update hashes
    if source_digest is None and convex_dir:
        source_files = collect_source_files(convex_dir)
        source_digest = files_hash(source_files)
    write_stored_hashes(output_dir, source_digest or "", new_blob_hash)

    typer.echo(f"Generated {output_dir / '_types.py'}")
    typer.echo(f"Generated {output_dir / '_client.py'}")
    typer.echo(f"  {generated.num_tables} table(s), {generated.num_functions} function(s)")
    return True


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
    regenerated = _run_pipeline(convex_dir, input_json, output_dir, force=force)
    if not regenerated:
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
    _run_pipeline(convex_dir, None, output_dir, force=True)

    def on_change() -> None:
        typer.echo("Change detected, checking for updates...")
        try:
            regenerated = _run_pipeline(convex_dir, None, output_dir)
            if not regenerated:
                typer.echo("  Schema unchanged, no regeneration needed.")
        except Exception as e:
            typer.echo(f"Error: {e}", err=True)

    do_watch(convex_dir, on_change)


def main() -> None:
    app()
