# Codex Log Tool v2

An improved version of the tool for visualizing LLM agent logs.

## What's New in v2.2

- **Better data quality** — tool calls (e.g., `apply_patch`, `shell`) now show a preview of the command/patch instead of just the tool name
- **Stats bar** in the events table — colored pills with the number of events per type; clicking hides/shows a given type
- **Search bar** above the table — filters rows by label/detail content in real time
- **Expandable rows** — clicking a row opens a panel with full content (label, detail, thinking, metadata)
- **Simplified table** — 7 → 5 columns (Detail and Thinking moved to the expand panel)
- **Larger hover tooltip** in the 3D spiral (label 80→120, detail 120→300 characters)

## What's New in v2.1

- **Support for older JSONL formats** — automatic detection and parsing of 3 versions of Codex CLI logs (September 2025, October–January 2026, February 2026+)
- **Empty session fix** — all imports with 0 events have been fixed

## What's New in v2.0

- **Log Manager** (`/logs/`) — a new page for managing logs:
  - Scanning the directory from `CODEX_SESSIONS_DIR` (default `~/.codex/sessions/`) and displaying available JSONL files
  - Grouping by months with checkboxes
  - Importing selected or ALL sessions with a single click
  - Marking already imported files
- **Better file organization** — JSONs in `visualization/data/sessions_json/`
- **New CLI options** — `--all` (import all) and `--file=NAME` (import a specific one)

## Structure

```text
codex_log_tool_v2/
├── run_prettify.sh          # Main script (--serve, --all, --file=...)
├── codex_prettify.py         # Parser and converter JSONL -> JSON
├── jsonl_deminify.py         # Helper deminifier
├── requirements.txt
├── json_downloader/
│   ├── download_jsons.sh     # Downloading (wrapper for run_prettify.sh)
│   └── raw_jsonl/            # Raw JSONL files
└── agentic-llm-session-visualizer-main/
    ├── manage.py
    ├── agentic_app/          # Django configuration
    ├── templates/            # HTML templates
    │   ├── base.html
    │   ├── home.html
    │   ├── agentic_thinking_visualization.html
    │   ├── log_manager.html  # NEW - log management
    │   └── instructions.html
    └── visualization/
        ├── loader.py         # JSON data loading
        ├── views.py          # Django views
        ├── log_manager.py    # NEW - log scanning and importing
        ├── data/
        │   └── sessions_json/  # Processed JSONs (visualization reads from here)
        └── instructions/
```

## Quick Start

```bash
cd codex_log_tool_v2
cp .env.example .env
./run_prettify.sh --serve
```

Then open: `http://127.0.0.1:8000/`

## Configuration via Environment Variables

The project uses environment variables (no hardcoded paths/secrets).

The easiest way:

```bash
cp .env.example .env
```

Key variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `CODEX_SESSIONS_DIR` | Directory with `.jsonl` files | `~/.codex/sessions` |
| `DJANGO_HOST` | Dev server host | `127.0.0.1` |
| `DJANGO_PORT` | Dev server port | `8000` |
| `DJANGO_DEBUG` | Debug mode | `true` |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated list of hosts | — |
| `DJANGO_SECRET_KEY` | Django secret key (must be changed outside of local dev) | — |

## Importing Logs

### Via the Web Interface (recommended)

1. Open `http://127.0.0.1:8000/logs/`
2. Select sessions to import using checkboxes (by month or individually)
3. Click **Import Selected** or **Import All New**

### Via CLI

```bash
# Import the latest log (default behavior)
./run_prettify.sh

# Import ALL logs
./run_prettify.sh --all

# Import a specific file
./run_prettify.sh --file=2026/02/14/rollout-2026-02-14T14-00-36-019c5c3d.jsonl

# Import + start the server
./run_prettify.sh --all --serve
```

### Via the Dedicated Script

```bash
./json_downloader/download_jsons.sh          # latest
./json_downloader/download_jsons.sh --all    # all
```

## Manual Visualizer Setup

```bash
cd codex_log_tool_v2
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd agentic-llm-session-visualizer-main
python manage.py runserver
```

## Pages

| URL | Description |
|-----|-------------|
| `/` | Home page with session list |
| `/visualization/` | 3D spiral visualization |
| `/logs/` | **NEW** — log management (import, checkboxes) |
| `/instructions/` | Usage instructions |
