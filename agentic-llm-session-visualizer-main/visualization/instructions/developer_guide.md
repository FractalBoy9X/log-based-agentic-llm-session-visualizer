# Agentic Thinking - Developer Guide

> Note: session source path is configurable via `CODEX_SESSIONS_DIR` (default: `~/.codex/sessions/`).

---

## System Architecture

```
codex_log_tool_v2/
├── run_prettify.sh              # CLI: --serve | --all | --file=... | --download-only
├── codex_prettify.py            # JSONL parser and JSON exporter
├── requirements.txt             # Python dependencies (Django, Plotly, NumPy)
├── json_downloader/
│   ├── download_jsons.sh        # Wrapper for run_prettify.sh --download-only
│   └── raw_jsonl/               # Copies of source JSONL files
└── agentic-llm-session-visualizer-main/
    ├── manage.py
    ├── agentic_app/
    │   ├── settings.py
    │   └── urls.py              # Routes: / | /visualization/ | /logs/ | /instructions/
    ├── templates/
    │   ├── base.html            # Navigation (Home, Visualization, Log Manager, Instructions)
    │   ├── home.html
    │   ├── agentic_thinking_visualization.html
    │   ├── log_manager.html     # NEW: session import UI with checkboxes
    │   └── instructions.html
    └── visualization/
        ├── loader.py            # JSON loading from data/sessions_json/, chart generation
        ├── views.py             # Django views (+ log_manager_view)
        ├── log_manager.py       # NEW: scan ~/.codex/sessions/, import JSONL -> JSON
        ├── instructions/
        │   ├── user_guide.md
        │   └── developer_guide.md
        └── data/
            └── sessions_json/   # Imported JSON files (visualizer reads from here)
                └── .import_mapping.json  # Tracks which JSONL files have been imported
```

---

## What's New in v2.2

### Data quality (`codex_prettify.py`)

**`_build_viz_label()`** — tool call events now show a command/content preview:

| Before | After |
|--------|-------|
| `"Tool: apply_patch"` | `"apply_patch: *** Begin Patch\n*** Update File: foo.py"` |
| `"Tool: shell"` | `"shell: ls -la /some/path"` |

Logic (priority order):
1. `ev.data["input"]` is valid JSON with `"command"` list → join list elements
2. Has `"patch"`/`"content"`/`"input"` key → first line of that value
3. Raw string input → first line
4. Fallback (no input) → `"Tool: {name}"` (unchanged)

**`_map_event_to_viz()`** — `detail` for `custom_tool_call` now stores `ev.data["input"][:500]` instead of `ev.message` (which was just the tool name).

> Improvements apply to newly imported sessions. Re-import existing sessions via Log Manager to update their data.

### Visualization UX (`agentic_thinking_visualization.html`)

| Feature | Description |
|---------|-------------|
| **Stats bar** | Colored pills with per-type counts; clickable to toggle visibility |
| **Search** | Filters rows by label + detail content in real time |
| **Expandable rows** | Click row → detail panel (full label, detail, thinking, meta) |
| **Simplified columns** | 7 → 5 columns (Detail + Thinking moved into expand) |
| **Taller table** | `max-height` 400px → 640px |

### Hover tooltip limits (`loader.py`)

| Field | Before | After |
|-------|--------|-------|
| `label` | 80 chars | 120 chars |
| `detail` | 120 chars | 300 chars |
| `thinking` | 200 chars | 300 chars |

---

## URL Routes

| URL | View | Description |
|-----|------|-------------|
| `/` | `home` | Home page with session list |
| `/visualization/` | `agentic_thinking_visualization_view` | 3D spiral chart |
| `/logs/` | `log_manager_view` | Log Manager with import UI |
| `/instructions/` | `instructions_view` | User/developer guides |

---

## JSONL Format Support

`codex_prettify.py` handles all Codex CLI log formats automatically:

| Period | Format | Key features |
|--------|--------|--------------|
| Sep 2025 | **v1 (flat)** | Direct top-level fields: `type: "message"/"reasoning"/"function_call"` |
| Oct 2025+ | **v2 (payload wrapper)** | Envelope `{timestamp, type, payload: {...}}`, types: `session_meta/response_item/event_msg/turn_context` |
| Oct 2025 – Jan 2026 | **v2 without task_started** | Older Codex versions omit `task_started`/`task_complete`; `user_message` used as turn boundary |

**Detection logic (`_detect_v1_format`):** checks if any of the first 10 records has `type` in `{"message", "reasoning", "function_call", "function_call_output"}`.

**v1 normalization (`normalize_v1_stream`):** converts v1 flat records to `NormalizedEvent` objects. Synthetic `task_started` events are injected for each user message to create turn structure.

**Fallback turn boundary (`build_session`):** when no `task_started` events are present (pre-v0.100 Codex), `event_msg/user_message` acts as an implicit turn delimiter.

---

## Components

### 1. `loader.py` - Data Loading

**Key change in v2:** `DATA_DIR` now points to `data/sessions_json/` (previously `data/`).

**Main functions:**

```python
load_agentic_thinking_log(max_events=MAX_EVENTS, selected_file=None)
```
- Scans `data/sessions_json/` for `.json` files
- Loads selected file or newest (by modification date)
- Normalizes events to common format
- Returns: `(events, stats, raw_log, log_path, error_message, meta)`

```python
build_agentic_thinking_spiral(events: List[Dict], agent_name: str = "Agent") -> go.Figure
```
- Generates Plotly 3D spiral chart
- Maps event types to colors
- Configures layout, hover info, z-axis labels

```python
list_available_sessions() -> List[Dict]
```
- Returns list of JSON sessions from `data/sessions_json/`
- Used to populate the session dropdown in the UI

**Constants:**

```python
MAX_EVENTS = 10000  # Event limit (configurable)

DATA_DIR = Path(__file__).parent / "data" / "sessions_json"

EVENT_COLORS = {
    "command": "#22c55e",   # Green
    "search": "#38bdf8",    # Blue
    "edit": "#f97316",      # Orange
    "write": "#f59e0b",     # Yellow
    "backup": "#ef4444",    # Red
    "note": "#64748b",      # Gray
    "read": "#8b5cf6",      # Purple
    "analyze": "#ec4899",   # Pink
}
```

---

### 2. `log_manager.py` - Session Import (NEW in v2)

Handles scanning and importing Codex sessions from `~/.codex/sessions/`.

**Codex session structure:**
```
~/.codex/sessions/
└── YYYY/
    └── MM/
        └── DD/
            └── rollout-YYYY-MM-DDTHH-MM-SS-<uuid>.jsonl
```

**Key functions:**

```python
scan_codex_sessions() -> List[Dict]
```
- Uses `rglob("*.jsonl")` to scan recursively through `YYYY/MM/DD/` subdirectories
- Returns list with fields: `filename`, `rel_path`, `path`, `modified`, `modified_date`,
  `size`, `size_kb`, `month_key`
- `rel_path` = relative path from `~/.codex/sessions/` (e.g., `"2026/02/12/rollout-xxx.jsonl"`)

```python
group_by_month(sessions) -> OrderedDict[str, List[Dict]]
```
- Groups sessions by month key (`"YYYY-MM"`)
- Preserves insertion order (newest month first)

```python
import_session(rel_path: str) -> Tuple[bool, str]
```
- Converts a single JSONL file to JSON using `codex_prettify.py`
- Stores mapping in `.import_mapping.json`

```python
import_sessions(rel_paths: List[str]) -> Tuple[int, List[str]]
import_all_sessions() -> Tuple[int, List[str]]
```
- Batch import functions; `import_all_sessions()` skips already imported files

```python
get_already_imported() -> Set[str]
```
- Reads `.import_mapping.json` to find already imported `rel_path` values

---

### 3. `views.py` - Django Views

**New view in v2:**

```python
def log_manager_view(request: HttpRequest) -> HttpResponse:
```

| POST action | What it does |
|-------------|-------------|
| `import_selected` | Imports files from `selected_files` (list of `rel_path`) |
| `import_all` | Imports all not-yet-imported sessions |

**Context passed to `log_manager.html`:**

| Key | Type | Description |
|-----|------|-------------|
| `grouped_sessions` | `OrderedDict` | Sessions grouped by month |
| `total_available` | `int` | Total JSONL files in `~/.codex/sessions/` |
| `total_imported` | `int` | Number of already imported sessions |
| `imported_sessions` | `List[Dict]` | Sessions ready for visualization |
| `import_status` | `str` | `"success"`, `"error"`, or `"info"` |
| `import_messages` | `List[str]` | Result messages for each file |
| `import_count` | `int` | Number successfully imported |

---

### 4. HTML Templates

**`log_manager.html`** - New in v2:
- Stats bar (available / imported / ready)
- Action bar: Import Selected, Import All New, Select All, Deselect All
- Month groups (collapsible) with checkboxes
- File rows with `rel_path` as checkbox value, `filename` as display text
- Imported Sessions table with links to visualization and **Delete** button per row

**Template: `base.html`** - Updated navigation:
```html
<a href="{% url 'log_manager' %}">Log Manager</a>
```

---

## Import Mapping

The file `data/sessions_json/.import_mapping.json` tracks which JSONL files have been imported:

```json
{
  "2026/02/12/rollout-2026-02-12T23-35-38-xxx.jsonl": "session_20260212_233538_some_task.json",
  "2025/11/03/rollout-2025-11-03T12-18-21-xxx.jsonl": "session_20251103_121821_another_task.json"
}
```

Keys are `rel_path` values (relative to `~/.codex/sessions/`).
Values are output JSON filenames in `sessions_json/`.

---

## Data Flow

```
~/.codex/sessions/YYYY/MM/DD/*.jsonl
    │
    │  scan_codex_sessions() [rglob]
    ▼
Log Manager UI (grouped by month, checkboxes)
    │
    │  import_session(rel_path) → codex_prettify.py --viz-json
    ▼
visualization/data/sessions_json/*.json
    │
    │  load_agentic_thinking_log()
    ▼
build_agentic_thinking_spiral() → Plotly 3D figure
    │
    ▼
Browser: /visualization/
```

---

## CLI Reference

```bash
# Import newest session only
./run_prettify.sh

# Import ALL sessions (recursive scan)
./run_prettify.sh --all

# Import specific file (rel_path from ~/.codex/sessions/)
./run_prettify.sh --file=2026/02/12/rollout-2026-02-12T23-35-38-xxx.jsonl

# Import newest and start server
./run_prettify.sh --serve

# Import all and start server
./run_prettify.sh --all --serve

# Only import, no server (used by json_downloader/download_jsons.sh)
./run_prettify.sh --download-only
```

---

## Extending the System

### Adding New Event Type

1. **Update `EVENT_COLORS` in `loader.py`:**

```python
EVENT_COLORS = {
    # ... existing ...
    "deploy": "#14b8a6",  # Teal
}
```

2. **Add CSS in `agentic_thinking_visualization.html`:**

```css
.event-type-deploy { background: #14b8a6; }
```

3. **Agent uses new type in JSON:**

```json
{ "event_type": "deploy", "label": "Deploy to staging", "detail": "kubectl apply -f deployment.yaml" }
```

---

### Adding Event Type Filtering

In `loader.py`:

```python
def load_agentic_thinking_log(
    max_events=MAX_EVENTS,
    selected_file=None,
    filter_types=None  # New parameter
):
    # ...
    if filter_types:
        events = [e for e in events if e.get("event_type") in filter_types]
```

In `views.py`:

```python
filter_types = request.GET.getlist("types")  # ?types=search&types=edit
events, ... = load_agentic_thinking_log(filter_types=filter_types or None)
```

---

### Adding CSV Export Endpoint

In `views.py`:

```python
import csv
from django.http import HttpResponse

def export_csv(request: HttpRequest) -> HttpResponse:
    selected_file = request.GET.get("file", "")
    events, _, _, _, _, meta = load_agentic_thinking_log(selected_file=selected_file)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="session.csv"'

    writer = csv.DictWriter(response, fieldnames=[
        'event_index', 'event_type', 'label', 'detail', 'source', 'timestamp'
    ])
    writer.writeheader()
    writer.writerows(events)
    return response
```

In `urls.py`:

```python
path('visualization/export/', views.export_csv, name='export_csv'),
```

---

## Troubleshooting

### Log Manager shows 0 sessions

Check if `~/.codex/sessions/` exists and contains `.jsonl` files:
```bash
find ~/.codex/sessions/ -name "*.jsonl" | wc -l
```

The directory may have nested structure `YYYY/MM/DD/` - the tool handles this automatically.

### Import fails with "File not found"

The `rel_path` passed to `import_session()` must be relative to `~/.codex/sessions/`, e.g.:
```
2026/02/12/rollout-2026-02-12T23-35-38-xxx.jsonl   # correct
rollout-2026-02-12T23-35-38-xxx.jsonl              # incorrect (missing year/month/day)
```

### Chart doesn't render

1. Check that `sessions_json/` contains `.json` files
2. Check browser console (F12) for JS errors
3. Verify Plotly is installed: `python3 -m pip show plotly`

### JSON file not loading

1. Validate JSON: `python3 -m json.tool file.json`
2. Check that file is not a macOS resource fork (`._*.json` files are ignored automatically)

### Imported session shows 0 events / empty chart

The session was imported with an older version of the parser. Fix:
1. Go to **Log Manager** → delete the session (the Delete button)
2. Re-import it — the parser now handles all JSONL formats correctly

Alternatively, from the command line:
```bash
# Re-import a specific file (delete old JSON first, then re-import)
./run_prettify.sh --file=2025/10/09/rollout-2025-10-09T13-38-05-xxx.jsonl
```

---

## Performance

| Parameter | Value | Notes |
|-----------|-------|-------|
| `MAX_EVENTS` | 10,000 | Configurable in `loader.py` |
| Max file size | ~5MB | Recommended for smooth rendering |
| Max label length | 80 chars | Truncated in visualization |
| Scan timeout | 120s per file | Configurable in `import_session()` |

---

**Version**: 2.2
**Last updated**: 2026-02-15
