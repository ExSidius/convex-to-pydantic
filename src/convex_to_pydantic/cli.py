"""CLI entry point for convex-to-pydantic."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import click

from .codegen.client_file import generate_client_file
from .codegen.types_file import generate_types_file
from .converter import parse_export
from .extractor.runner import extract, extract_from_json
from .namer import assign_names


def _run_pipeline(
    convex_dir: Path | None,
    input_json: Path | None,
    output_dir: Path,
) -> None:
    """Run the full extraction → codegen pipeline."""
    # Step 1: Extract
    if input_json:
        blob = extract_from_json(input_json)
    elif convex_dir:
        blob = extract(convex_dir)
    else:
        raise click.UsageError("Either --convex-dir or --input must be provided.")

    # Step 2: Convert to IR
    export = parse_export(blob)

    # Step 3: Assign names
    assign_names(export)

    # Step 4: Generate files
    types_content = generate_types_file(export)
    client_content = generate_client_file(export)

    # Step 5: Write files
    output_dir.mkdir(parents=True, exist_ok=True)

    types_path = output_dir / "_types.py"
    client_path = output_dir / "_client.py"

    types_path.write_text(types_content)
    client_path.write_text(client_content)

    # Step 6: Format with ruff if available
    ruff = shutil.which("ruff")
    if ruff:
        subprocess.run(
            [ruff, "format", str(types_path), str(client_path)],
            capture_output=True,
            check=False,
        )

    click.echo(f"Generated {types_path}")
    click.echo(f"Generated {client_path}")
    click.echo(
        f"  {len(export.tables)} table(s), {len(export.functions)} function(s)"
    )


@click.group()
def main() -> None:
    """Pydantic codegen from Convex schemas."""


@main.command()
@click.option(
    "--convex-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Path to your Convex directory (e.g. ./convex).",
)
@click.option(
    "--input",
    "input_json",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to a pre-exported JSON file (alternative to --convex-dir).",
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    required=True,
    help="Directory to write _types.py and _client.py.",
)
def generate(
    convex_dir: Path | None,
    input_json: Path | None,
    output_dir: Path,
) -> None:
    """Generate Pydantic models from Convex schema."""
    _run_pipeline(convex_dir, input_json, output_dir)


@main.command()
@click.option(
    "--convex-dir",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    required=True,
    help="Path to your Convex directory (e.g. ./convex).",
)
@click.option(
    "--output-dir",
    type=click.Path(path_type=Path),
    required=True,
    help="Directory to write _types.py and _client.py.",
)
def watch(convex_dir: Path, output_dir: Path) -> None:
    """Watch Convex directory and regenerate on changes."""
    from .watcher import watch as do_watch

    click.echo(f"Watching {convex_dir} for changes...")

    # Run once immediately
    _run_pipeline(convex_dir, None, output_dir)

    def on_change() -> None:
        click.echo("Change detected, regenerating...")
        try:
            _run_pipeline(convex_dir, None, output_dir)
        except Exception as e:
            click.echo(f"Error: {e}", err=True)

    do_watch(convex_dir, on_change)
