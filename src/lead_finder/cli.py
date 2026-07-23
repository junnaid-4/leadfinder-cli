"""Typer CLI entry point."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console

from lead_finder.config import AppConfig, EnvSettings, load_config
from lead_finder.database import init_database
from lead_finder.logging_config import setup_logging
from lead_finder.models import SearchRunStatus
from lead_finder.places_client import (
    FIELD_MASK,
    PlacesClient,
    build_places_cache_key,
)

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
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Estimate and validate without API calls."),
    ] = False,
) -> None:
    """Collect businesses from Google Places."""
    app_config = _resolve_config(config)
    setup_logging(app_config)

    try:
        env = EnvSettings()
        api_key = env.require_api_key()
        has_api_key = True
    except Exception:
        has_api_key = False
        api_key = ""

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

    if not has_api_key:
        console.print("[red]API key is missing but required for collection.[/red]")
        raise typer.Exit(code=1)

    db = init_database(app_config.database_path())
    run_id = db.create_search_run(
        app_config.project.name, app_config.search.location, dry_run=False
    )

    total_discovered = 0
    total_duplicates = 0
    api_requests = 0
    cached_used = 0
    failed_queries = 0

    location = app_config.search.location
    client = PlacesClient(api_key)

    async def _run_collection() -> None:
        nonlocal total_discovered, total_duplicates, api_requests
        nonlocal cached_used, failed_queries

        for query_base in app_config.search.queries:
            if total_discovered >= app_config.search.max_total_results:
                break
            if api_requests >= app_config.search.max_api_requests:
                break

            query = f"{query_base} in {location}"
            page_token = None
            query_results = 0

            while True:
                if query_results >= app_config.search.max_results_per_query:
                    break
                if total_discovered >= app_config.search.max_total_results:
                    break
                if api_requests >= app_config.search.max_api_requests:
                    break

                cache_key = build_places_cache_key(
                    query=query,
                    location=location,
                    field_mask=FIELD_MASK,
                    page_token=page_token,
                )
                cached_data = None

                if not force_refresh:
                    cached_data = db.get_cached_api_response(cache_key)

                if cached_data:
                    data = json.loads(cached_data)
                    cached_used += 1
                else:
                    try:
                        data = await client.search_text(query, page_token)
                        api_requests += 1

                        expires_dt = datetime.now(tz=UTC) + timedelta(
                            days=app_config.cache.places_ttl_days
                        )
                        expires = expires_dt.strftime("%Y-%m-%d %H:%M:%S")
                        db.save_cached_api_response(
                            cache_key, "searchText", json.dumps(data), expires
                        )
                    except Exception as e:
                        console.print(f"[red]Error fetching query '{query}': {e}[/red]")
                        failed_queries += 1
                        break

                places = data.get("places", [])
                if not places:
                    break

                for place in places:
                    if (
                        total_discovered >= app_config.search.max_total_results
                        or query_results >= app_config.search.max_results_per_query
                    ):
                        break

                    place_id = place.get("id")
                    if not place_id:
                        continue

                    name = place.get("displayName", {}).get("text", "Unknown")
                    is_new = db.insert_or_update_business(
                        place_id, name, query_base, location, place
                    )
                    if is_new:
                        total_discovered += 1
                        query_results += 1
                    else:
                        total_duplicates += 1

                page_token = data.get("nextPageToken")
                if not page_token:
                    break

            db.add_search_query_log(run_id, query_base, location, query_results)

    try:
        asyncio.run(_run_collection())
        status = SearchRunStatus.COMPLETED
    except Exception as e:
        console.print(f"[red]Fatal error during collection: {e}[/red]")
        status = SearchRunStatus.FAILED

    db.update_search_run(run_id, status.value, total_discovered, total_duplicates, api_requests)

    console.print("\n[bold]Collection Summary[/bold]")
    console.print(f"Queries processed: {len(app_config.search.queries)}")
    console.print(f"Live API requests used: {api_requests}")
    console.print(f"Cached responses used: {cached_used}")
    console.print(f"Unique businesses saved: {total_discovered}")
    console.print(f"Duplicates merged: {total_duplicates}")
    console.print(f"Failed queries: {failed_queries}")
    console.print(f"Database path: {app_config.database_path()}")


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
    """Check business websites for availability and classify them."""
    app_config = _resolve_config(config)
    setup_logging(app_config)

    if not app_config.website_check.enabled:
        console.print("[yellow]Website checking is disabled in configuration.[/yellow]")
        return

    db = init_database(app_config.database_path())
    businesses = db.get_businesses_needing_checks(force_refresh=force_refresh)

    if not businesses:
        console.print("No businesses need website checking.")
        return

    console.print(f"Checking {len(businesses)} websites...")

    from lead_finder.website_checker import WebsiteChecker, WebsiteStatus

    checker = WebsiteChecker(app_config.website_check)
    counts = {status: 0 for status in WebsiteStatus}

    async def _process_all() -> None:
        async def _check_and_save(business_row: Any) -> None:
            b_id = business_row["id"]
            name = business_row["business_name"]
            url = business_row["website_url"]
            try:
                result = await checker.check_website(b_id, url)
                db.save_website_check_result(
                    business_id=result.business_id,
                    original_url=result.original_url,
                    normalized_url=result.normalized_url,
                    final_url=result.final_url,
                    status=result.status.value,
                    http_status=result.http_status,
                    redirect_count=result.redirect_count,
                    response_time_ms=result.response_time_ms,
                    content_type=result.content_type,
                    error_type=result.error_type,
                    error_message=result.error_message,
                )
                counts[result.status] += 1
            except Exception as e:
                console.print(f"[red]Error checking {name}: {e}[/red]")
                counts[WebsiteStatus.UNKNOWN_ERROR] += 1

        tasks = [_check_and_save(row) for row in businesses]
        await asyncio.gather(*tasks)
        await checker.close()

    try:
        asyncio.run(_process_all())
    except KeyboardInterrupt:
        console.print("\n[yellow]Website checking interrupted.[/yellow]")

    summary_labels = {
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
    console.print(f"Businesses processed: {len(businesses)}")
    for status, label in summary_labels.items():
        count = counts[status]
        if count > 0:
            console.print(f"{label}: {count}")

    console.print(f"Database path: {app_config.database_path()}")


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
