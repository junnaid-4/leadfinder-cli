"""Typer CLI entry point."""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

from lead_finder.config import AppConfig, EnvSettings, load_config
from lead_finder.database import init_database
from lead_finder.exporter import export_to_csv, export_to_xlsx
from lead_finder.lead_scoring import SCORING_VERSION, LeadPriority
from lead_finder.logging_config import setup_logging
from lead_finder.pipeline import (
    ExportFormat,
    WebsiteCheckStageError,
    check_business_websites,
    collect_businesses,
    export_lead_files,
    prepare_export_rows,
    score_businesses,
)
from lead_finder.website_checker import WebsiteStatus

app = typer.Typer(
    name="lead-finder",
    help="Local Business Website Lead Finder — internal lead-generation tool.",
    no_args_is_help=True,
)
console = Console()


class RunFormat(StrEnum):
    """Supported full-pipeline export selections."""

    CSV = "csv"
    XLSX = "xlsx"
    BOTH = "both"


def _resolve_config(config: Path) -> AppConfig:
    return load_config(config)


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
def collect(
    config: Annotated[
        Path, typer.Option("--config", "-c", help="Path to YAML configuration file.")
    ] = Path("config.yaml"),
    force_refresh: Annotated[
        bool, typer.Option("--force-refresh", help="Ignore cached Places responses.")
    ] = False,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Estimate and validate without API calls.")
    ] = False,
) -> None:
    """Collect businesses from Google Places."""
    app_config = _resolve_config(config)
    try:
        api_key = EnvSettings().require_api_key()
        has_api_key = True
    except ValueError:
        api_key = ""
        has_api_key = False

    if dry_run:
        console.print("[yellow]DRY RUN MODE ENABLED[/yellow]")
        console.print("Configuration valid: Yes")
        console.print(f"API key available: {'Yes' if has_api_key else 'No'}")
        console.print(f"Queries: {app_config.search.queries}")
        console.print(f"Location: {app_config.search.location}")
        console.print(f"Max Results Per Query: {app_config.search.max_results_per_query}")
        console.print(f"Max Total Results: {app_config.search.max_total_results}")
        console.print(f"Max API Requests: {app_config.search.max_api_requests}")
        console.print("No network requests will be made.")
        return
    setup_logging(app_config)
    if not has_api_key:
        console.print("[red]API key is missing but required for collection.[/red]")
        raise typer.Exit(1)

    summary = collect_businesses(app_config, api_key, force_refresh=force_refresh)
    console.print("\n[bold]Collection Summary[/bold]")
    console.print(f"Queries processed: {len(app_config.search.queries)}")
    console.print(f"Live API requests used: {summary.api_requests}")
    console.print(f"Cached responses used: {summary.cached_responses}")
    console.print(f"Unique businesses saved: {summary.discovered}")
    console.print(f"Duplicates merged: {summary.duplicates}")
    console.print(f"Failed queries: {summary.failed_queries}")
    console.print(f"Database path: {app_config.database_path()}")


@app.command("check-websites")
def check_websites(
    config: Annotated[
        Path, typer.Option("--config", "-c", help="Path to YAML configuration file.")
    ] = Path("config.yaml"),
    force_refresh: Annotated[
        bool, typer.Option("--force-refresh", help="Re-check websites ignoring cache.")
    ] = False,
) -> None:
    """Check business websites for availability and classify them."""
    app_config = _resolve_config(config)
    setup_logging(app_config)
    if not app_config.website_check.enabled:
        console.print("[yellow]Website checking is disabled in configuration.[/yellow]")
        return
    try:
        summary = check_business_websites(app_config, force_refresh=force_refresh)
    except WebsiteCheckStageError as exc:
        console.print(f"[red]Website checking failed: {exc}[/red]")
        raise typer.Exit(1) from exc
    if summary.processed == 0:
        console.print("No businesses need website checking.")
        return
    console.print(f"Website checks completed: {summary.processed}")
    labels = {
        WebsiteStatus.NO_WEBSITE: "No website",
        WebsiteStatus.WORKING: "Working",
        WebsiteStatus.UNREACHABLE: "Unreachable",
        WebsiteStatus.TIMEOUT: "Timeout",
        WebsiteStatus.DNS_ERROR: "DNS errors",
        WebsiteStatus.SSL_ERROR: "SSL errors",
        WebsiteStatus.HTTP_ERROR: "HTTP errors",
        WebsiteStatus.BLOCKED: "Blocked",
        WebsiteStatus.INVALID_URL: "Invalid URLs",
        WebsiteStatus.REDIRECT_LOOP: "Redirect loop",
        WebsiteStatus.UNKNOWN_ERROR: "Other failures",
    }
    console.print("\n[bold]Website Check Summary[/bold]")
    console.print(f"Businesses processed: {summary.processed}")
    for status, label in labels.items():
        if summary.counts[status]:
            console.print(f"{label}: {summary.counts[status]}")
    console.print(f"Database path: {app_config.database_path()}")


@app.command()
def score_leads(
    config: Annotated[
        Path, typer.Option("--config", "-c", help="Path to YAML configuration file.")
    ] = Path("config.yaml"),
    force_refresh: Annotated[
        bool, typer.Option("--force-refresh", help="Score already scored businesses again.")
    ] = False,
) -> None:
    """Calculate and assign lead scores to businesses."""
    app_config = _resolve_config(config)
    setup_logging(app_config)
    summary = score_businesses(app_config, force_refresh=force_refresh)
    console.print("\n[bold]Lead Scoring Summary[/bold]")
    console.print(f"Businesses considered: {summary.considered}")
    console.print(f"Businesses scored: {summary.scored}")
    console.print(f"Skipped existing scores: {summary.skipped_existing}")
    console.print(f"Unscorable businesses: {summary.unscorable}")
    console.print(f"Failed records: {summary.failed}")
    console.print("")
    console.print(f"Very high priority: {summary.priority_counts[LeadPriority.VERY_HIGH]}")
    console.print(f"High priority: {summary.priority_counts[LeadPriority.HIGH]}")
    console.print(f"Medium priority: {summary.priority_counts[LeadPriority.MEDIUM]}")
    console.print(f"Low priority: {summary.priority_counts[LeadPriority.LOW]}")
    console.print(f"Very low priority: {summary.priority_counts[LeadPriority.VERY_LOW]}")
    console.print("")
    console.print(f"Average score: {summary.average_score:.1f}")
    console.print(f"Highest score: {summary.highest_score}")
    console.print(f"Database path: {app_config.database_path()}")
    console.print(f"Scoring version: {SCORING_VERSION}")


@app.command()
def explain_score(
    business_id: int,
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to YAML configuration file."),
    ] = Path("config.yaml"),
) -> None:
    """Explain the latest lead score for a business."""
    app_config = _resolve_config(config)
    setup_logging(app_config)

    db = init_database(app_config.database_path())

    try:
        # Get business name
        b_cursor = db.execute("SELECT business_name FROM businesses WHERE id = ?", (business_id,))
        b_row = b_cursor.fetchone()
        if not b_row:
            console.print(f"Business ID {business_id} not found.", style="red")
            raise typer.Exit(1)

        b_name = b_row["business_name"]

        # Get latest score
        s_cursor = db.execute(
            """
            SELECT final_score, priority, scoring_version, score_breakdown_json
            FROM lead_scores
            WHERE business_id = ?
            ORDER BY scored_at DESC, id DESC
            LIMIT 1
            """,
            (business_id,),
        )
        s_row = s_cursor.fetchone()
        if not s_row:
            console.print(
                f"No score found for business '{b_name}' (ID {business_id}).", style="yellow"
            )
            raise typer.Exit()

        console.print(f"[bold]Business:[/bold] {b_name}")
        console.print(f"[bold]Latest score:[/bold] {s_row['final_score']}")
        console.print(f"[bold]Priority:[/bold] {s_row['priority']}")
        console.print(f"[bold]Scoring version:[/bold] {s_row['scoring_version']}")
        console.print("\n[bold]Score Breakdown:[/bold]")

        components = json.loads(s_row["score_breakdown_json"])
        for comp in components:
            rule = comp.get("rule", "unknown")
            points = comp.get("points", 0)
            explanation = comp.get("explanation", "")
            sign = "+" if points >= 0 else ""
            console.print(f"- {explanation} ({rule}): {sign}{points}")

    finally:
        db.close()


@app.command()
def run(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to YAML configuration file."),
    ] = Path("config.yaml"),
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Validate and show the plan without side effects.")
    ] = False,
    force_refresh: Annotated[
        bool, typer.Option("--force-refresh", help="Ignore cached collection and analysis data.")
    ] = False,
    overwrite: Annotated[
        bool, typer.Option("--overwrite", help="Replace existing pipeline export files.")
    ] = False,
    fmt: Annotated[
        RunFormat, typer.Option("--format", help="Export format: csv, xlsx, or both.")
    ] = RunFormat.BOTH,
    output_dir: Annotated[
        Path | None, typer.Option("--output-dir", help="Override the export directory.")
    ] = None,
) -> None:
    """Run collection, website checking, scoring, and export."""
    app_config = _resolve_config(config)
    if dry_run:
        console.print("[bold yellow]DRY RUN — no files or network requests[/bold yellow]")
        console.print("[bold]Planned stages[/bold]")
        console.print("1. Validate configuration")
        console.print("2. Collect businesses from Google Places")
        console.print("3. Check business websites")
        console.print("4. Calculate lead scores")
        console.print(f"5. Export leads ({fmt.value})")
        console.print(f"Queries: {len(app_config.search.queries)}")
        console.print(f"Maximum results per query: {app_config.search.max_results_per_query}")
        console.print(f"Maximum total results: {app_config.search.max_total_results}")
        console.print(f"Maximum API requests: {app_config.search.max_api_requests}")
        console.print(
            f"Export directory: {(output_dir or app_config.export_directory()).resolve()}"
        )
        return

    setup_logging(app_config)
    try:
        console.rule("[bold]1/4 Collect businesses")
        api_key = EnvSettings().require_api_key()
        collection = collect_businesses(app_config, api_key, force_refresh=force_refresh)
        if collection.failed_queries:
            raise RuntimeError(
                f"Collection failed for {collection.failed_queries} configured queries"
            )
        console.print(f"Businesses discovered: {collection.discovered}")

        console.rule("[bold]2/4 Check websites")
        checks = check_business_websites(app_config, force_refresh=force_refresh)
        console.print(f"Businesses checked: {checks.processed}")

        console.rule("[bold]3/4 Score leads")
        scoring = score_businesses(app_config, force_refresh=force_refresh)
        if scoring.failed:
            raise RuntimeError(f"Failed to score {scoring.failed} businesses")
        console.print(f"Businesses scored: {scoring.scored}")

        console.rule("[bold]4/4 Export leads")
        export_format: ExportFormat = fmt.value
        exports = export_lead_files(
            app_config, fmt=export_format, output_dir=output_dir, overwrite=overwrite
        )
        if exports.rows_exported == 0:
            raise RuntimeError("No scored leads were available to export")
    except Exception as exc:
        console.print(f"[red]Pipeline failed: {exc}[/red]")
        raise typer.Exit(1) from exc

    console.print("\n[bold green]Pipeline completed successfully[/bold green]")
    console.print(f"Businesses discovered: {collection.discovered}")
    console.print(f"Website checks completed: {checks.processed}")
    console.print(f"Businesses scored: {scoring.scored}")
    console.print(f"Rows exported: {exports.rows_exported}")
    for path in exports.output_paths:
        console.print(f"Output file: {path}")
    console.print(f"Database path: {app_config.database_path()}")


@app.command()
def demo(
    config: Annotated[
        Path, typer.Option("--config", "-c", help="Path to demo YAML configuration.")
    ],
    overwrite: Annotated[
        bool, typer.Option("--overwrite", help="Safely recreate existing demo artifacts.")
    ] = False,
) -> None:
    """Create a deterministic fictional demo without API keys or network access."""
    from lead_finder.demo_data import run_demo

    app_config = _resolve_config(config)
    try:
        summary = run_demo(app_config, project_root=config.resolve().parent, overwrite=overwrite)
    except FileExistsError:
        console.print(
            "[red]Demo data or output already exists. Use --overwrite to recreate it.[/red]"
        )
        raise typer.Exit(1) from None
    except Exception as exc:
        console.print(f"[red]Demo failed: {exc}[/red]")
        raise typer.Exit(1) from exc

    console.print("\n[bold green]LeadFinder Fictional Demo Complete[/bold green]")
    console.print(f"Businesses inserted: {summary.businesses_inserted}")
    console.print(f"Businesses scored: {summary.scoring.scored}")
    console.print("[bold]Priority counts[/bold]")
    for priority, count in summary.scoring.priority_counts.items():
        console.print(f"{priority.replace('_', ' ').title()}: {count}")
    console.print(f"Database path: {summary.database_path}")
    paths = {path.suffix: path for path in summary.exports.output_paths}
    console.print(f"CSV path: {paths['.csv']}")
    console.print(f"XLSX path: {paths['.xlsx']}")


@app.command("export-leads")
def export_leads(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to YAML configuration file."),
    ] = Path("config.yaml"),
    fmt: Annotated[
        str | None,
        typer.Option("--format", help="Export format (csv or xlsx)."),
    ] = None,
    output: Annotated[
        Path | None,
        typer.Option("--output", "-o", help="Output file path."),
    ] = None,
    min_score: Annotated[
        int | None,
        typer.Option("--min-score", help="Minimum lead score to include."),
    ] = None,
    priority: Annotated[
        list[str] | None,
        typer.Option("--priority", help="Priorities to include."),
    ] = None,
    limit: Annotated[
        int | None,
        typer.Option("--limit", help="Maximum number of rows to export."),
    ] = None,
    include_unscored: Annotated[
        bool | None,
        typer.Option("--include-unscored/--exclude-unscored", help="Include unscored businesses."),
    ] = None,
    overwrite: Annotated[
        bool,
        typer.Option("--overwrite", help="Overwrite the output file if it exists."),
    ] = False,
) -> None:
    """Export leads to a CSV or XLSX file."""
    app_config = _resolve_config(config)
    setup_logging(app_config)

    export_cfg = app_config.export

    # Resolve format
    resolved_format = fmt.lower() if fmt is not None else export_cfg.default_format
    if resolved_format not in ("csv", "xlsx"):
        console.print(
            f"Error: Invalid format '{resolved_format}'. Must be 'csv' or 'xlsx'.",
            style="red",
        )
        raise typer.Exit(1)

    # Resolve output path
    if output is None:
        out_name = f"leads.{resolved_format}"
        output_path = app_config.export_directory() / out_name
    else:
        output_path = output

    if output_path.is_dir():
        console.print(
            "Error: Output path is a directory, not a file.",
            style="red",
        )
        raise typer.Exit(1)
    # Apply default suffix if missing
    if not output_path.suffix:
        output_path = output_path.with_suffix(f".{resolved_format}")

    # Check format and suffix mismatch
    if (resolved_format == "csv" and output_path.suffix.lower() != ".csv") or (
        resolved_format == "xlsx" and output_path.suffix.lower() != ".xlsx"
    ):
        console.print(
            "Error: Output file suffix does not match the chosen format.",
            style="red",
        )
        raise typer.Exit(1)

    output_path = output_path.resolve()
    # Create missing parent directories
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_path.exists() and not overwrite:
        console.print(
            f"Error: Output file '{output_path}' already exists. Use --overwrite.",
            style="red",
        )
        raise typer.Exit(1)

    # Resolve filtering parameters
    resolved_min_score = min_score if min_score is not None else export_cfg.minimum_score
    resolved_priorities = [p.lower() for p in priority] if priority else export_cfg.priorities
    resolved_include_unscored = (
        include_unscored if include_unscored is not None else export_cfg.include_unscored
    )

    selection = prepare_export_rows(
        app_config,
        minimum_score=resolved_min_score,
        priorities=resolved_priorities,
        include_unscored=resolved_include_unscored,
        limit=limit,
    )
    candidates_count = selection.considered
    export_rows = selection.rows

    if not export_rows:
        console.print("No businesses matched the export filters.", style="yellow")
        console.print(f"Businesses considered: {candidates_count}")
        console.print("Rows matching filters: 0")
        raise typer.Exit()

    # Write output
    try:
        if resolved_format == "csv":
            export_to_csv(export_rows, output_path)
        else:
            export_to_xlsx(export_rows, output_path)
    except Exception as e:
        console.print(f"Failed to export: {e}", style="red")
        raise typer.Exit(1) from e

    unscored_included = sum(1 for r in export_rows if r.final_score is None)
    filtered_out = candidates_count - len(export_rows)
    pri_text = ", ".join(resolved_priorities) if resolved_priorities else "all"

    console.print("Export completed successfully.", style="green")
    console.print(f"Businesses considered: {candidates_count}")
    console.print(f"Rows exported: {len(export_rows)}")
    console.print(f"Unscored rows included: {unscored_included}")
    console.print(f"Filtered-out rows: {filtered_out}")
    console.print(f"Minimum score filter: {resolved_min_score}")
    console.print(f"Included priorities: {pri_text}")
    console.print(f"Format: {resolved_format}")
    typer.echo(f"Output file: {output_path}")
    typer.echo(f"Database path: {app_config.database_path().resolve()}")


def main() -> None:
    """Console script entry point."""
    app()


if __name__ == "__main__":
    main()
