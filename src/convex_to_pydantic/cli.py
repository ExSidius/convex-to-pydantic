"""CLI entry point for convex-to-pydantic."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Annotated, Optional

import typer

from .codegen.client_file import generate_client_file
from .codegen.types_file import generate_types_file
from .converter import parse_export
from .extractor.runner import extract, extract_from_json
from .hasher import content_hash, read_hash, write_hash
from .namer import assign_names

app = typer.Typer(
    name="convex-to-pydantic",
    help="Pydantic codegen from Convex schemas.",
    no_args_is_help=True,
)


def _run_pipeline(
    convex_dir: Path | None,
    input_json: Path | None,
    output_dir: Path,
    *,
    force: bool = False,
) -> bool:
    """Run the full extraction → codegen pipeline.

    Returns True if files were regenerated, False if skipped (unchanged).
    """
    # Step 1: Extract
    if input_json:
        blob = extract_from_json(input_json)
    elif convex_dir:
        blob = extract(convex_dir)
    else:
        raise typer.BadParameter("Either --convex-dir or --input must be provided.")

    # Step 2: Check staleness — skip if content hash is unchanged
    new_hash = content_hash(blob)
    if not force and read_hash(output_dir) == new_hash:
        return False

    # Step 3: Convert to IR
    export = parse_export(blob)

    # Step 4: Assign names
    assign_names(export)

    # Step 5: Generate files
    types_content = generate_types_file(export)
    client_content = generate_client_file(export)

    # Step 6: Write files
    output_dir.mkdir(parents=True, exist_ok=True)

    types_path = output_dir / "_types.py"
    client_path = output_dir / "_client.py"

    types_path.write_text(types_content)
    client_path.write_text(client_content)

    # Step 7: Write content hash
    write_hash(output_dir, new_hash)

    # Step 8: Format with ruff if available
    ruff = shutil.which("ruff")
    if ruff:
        subprocess.run(
            [ruff, "format", str(types_path), str(client_path)],
            capture_output=True,
            check=False,
        )

    typer.echo(f"Generated {types_path}")
    typer.echo(f"Generated {client_path}")
    typer.echo(
        f"  {len(export.tables)} table(s), {len(export.functions)} function(s)"
    )
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

    # Run once immediately (force first run)
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
