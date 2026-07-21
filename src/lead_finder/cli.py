"""Typer CLI entry point."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from lead_finder.config import AppConfig, load_config
from lead_finder.logging_config import setup_logging

app = typer.Typer(
    name="lead-finder",
    help="Local Business Website Lead Finder — internal lead-generation tool.",
    no_args_is_help=True,
)
console = Console()


def _resolve_config(config: Path) -> AppConfig:
    return load_config(config)


def _not_implemented(command: str) -> None:
    console.print(
        f"[yellow]{command} is not implemented yet (Stage 2+).[/yellow]",
        highlight=False,
    )
    raise typer.Exit(code=0)


@app.command("validate-config")
def validate_config(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to YAML configuration file."),
    ] = Path("config.yaml"),
) -> None:
    """Validate configuration file and environment settings."""
    app_config = _resolve_config(config)
    setup_logging(app_config)
    console.print("[green]Configuration is valid.[/green]")
    console.print(f"Project: {app_config.project.name}")
    console.print(f"Location: {app_config.search.location}")
    console.print(f"Queries: {len(app_config.search.queries)}")


@app.command()
def estimate(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to YAML configuration file."),
    ] = Path("config.yaml"),
) -> None:
    """Estimate API usage and run scope (placeholder)."""
    _resolve_config(config)
    _not_implemented("estimate")


@app.command()
def collect(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to YAML configuration file."),
    ] = Path("config.yaml"),
    force_refresh: Annotated[
        bool,
        typer.Option("--force-refresh", help="Ignore cached Places responses."),
    ] = False,
) -> None:
    """Collect businesses from Google Places (placeholder)."""
    _resolve_config(config)
    if force_refresh:
        console.print("Force refresh requested.", highlight=False)
    _not_implemented("collect")


@app.command("check-websites")
def check_websites(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to YAML configuration file."),
    ] = Path("config.yaml"),
    force_refresh: Annotated[
        bool,
        typer.Option("--force-refresh", help="Re-check websites ignoring cache."),
    ] = False,
) -> None:
    """Check business websites (placeholder)."""
    _resolve_config(config)
    if force_refresh:
        console.print("Force refresh requested.", highlight=False)
    _not_implemented("check-websites")


@app.command()
def export(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to YAML configuration file."),
    ] = Path("config.yaml"),
) -> None:
    """Export results to CSV files (placeholder)."""
    _resolve_config(config)
    _not_implemented("export")


@app.command()
def run(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to YAML configuration file."),
    ] = Path("config.yaml"),
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Estimate and validate without API calls."),
    ] = False,
    force_refresh: Annotated[
        bool,
        typer.Option("--force-refresh", help="Ignore cached data."),
    ] = False,
) -> None:
    """Run the full pipeline (placeholder)."""
    _resolve_config(config)
    if dry_run:
        console.print("Dry run mode enabled.", highlight=False)
    if force_refresh:
        console.print("Force refresh requested.", highlight=False)
    _not_implemented("run")


def main() -> None:
    """Console script entry point."""
    app()


if __name__ == "__main__":
    main()
