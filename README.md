# Local Business Website Lead Finder

Internal Python CLI tool for discovering local businesses via the Google Places API and identifying those with missing or broken websites.

**Status:** Stage 1 — project foundation (configuration, logging, database, CLI placeholders).

## Setup

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
cp config.example.yaml config.yaml
```

Set `GOOGLE_MAPS_API_KEY` in `.env` before running collection (Stage 2+).

## Stage 1 CLI (placeholders)

```bash
lead-finder validate-config --config config.yaml
lead-finder estimate --config config.yaml
lead-finder collect --config config.yaml
lead-finder check-websites --config config.yaml
lead-finder export --config config.yaml
lead-finder run --config config.yaml
```

## Development

```bash
pytest
ruff check src tests
mypy
```
