# Agentic Thinking - User Guide

> Note: source sessions directory is configurable via `CODEX_SESSIONS_DIR` (default: `~/.codex/sessions/`).

## What is Agentic Thinking Visualization?

Agentic Thinking Visualization is a tool that lets you **see** what an AI agent (like Claude, GPT-4, Gemini, Codex, or others) does during work on your project. Instead of waiting for the final result, you can observe each step of the agent's work in the form of an interactive 3D chart.

---

## Getting Started

### Quick start (all-in-one)

```bash
cd codex_log_tool_v2
./run_prettify.sh --serve
```

Then open: `http://127.0.0.1:8000/`

---

## Importing Sessions (Log Manager)

Before you can visualize a session, it must be imported from `~/.codex/sessions/`.

### Step 1: Open Log Manager

```
http://127.0.0.1:8000/logs/
```

Or click **Log Manager** in the top navigation.

### Step 2: Select sessions to import

The page shows all available Codex sessions from `~/.codex/sessions/`, grouped by **month**. Each row shows the file name, date, and size.

| Checkbox | What it does |
|----------|-------------|
| Month checkbox | Selects/deselects all sessions in that month |
| Individual file checkbox | Selects/deselects a single file |
| **Select All** button | Selects all available files |
| **Deselect All** button | Clears selection |

Sessions already imported are marked with a green **imported** badge and pre-checked (cannot be selected again).

### Step 3: Import

- **Import Selected** - imports only the checked files
- **Import All New** - imports all files that have not yet been imported

After importing, the sessions appear in the "Imported Sessions" list with links to the visualization.

---

## Visualizing a Session

### Step 1: Open the visualization page

```
http://127.0.0.1:8000/visualization/
```

### Step 2: Select a session

At the top of the page, you'll find a **dropdown list** with imported sessions. Select the session you want to explore.

### Step 3: Browse the chart

You'll see a **3D spiral chart**. Each colored point is one step of the agent's work:

| Color | What it means |
|-------|---------------|
| Green | Command execution (e.g., running a test) |
| Blue | Code searching |
| Orange | File editing |
| Yellow | Creating a new file |
| Red | Creating a backup |
| Gray | Note or comment |
| Purple | File reading |
| Pink | Code analysis |

### Step 4: Check the details

- **Hover** over a point to see event details
- **Click and drag** to rotate the chart
- **Scroll** to zoom in/out
- **Fullscreen** button expands the chart to full screen

---

## Reading the Chart

### Vertical axis (Z)
The higher a point on the chart, the **later** that action was performed. The first step is at the bottom, the last at the top.

### Spiral
Points are arranged in a spiral - this makes it easy to follow the **sequence** of the agent's steps.

### Events table
Below the chart, you'll find a **table** with all events. Columns:
- Step number, action type (color-coded badge), label, source, timestamp

**Filtering and searching:**
- **Stats bar** (colored pills above the table) — click any type pill to show/hide events of that type
- **Search box** — type any text to filter rows by label or detail content; click **✕ Clear** to reset

**Expanding event details:**
- Click any row to expand a detail panel below it:
  - Full label text
  - Full detail (e.g. command, patch content, or tool output)
  - Thinking / reasoning (if the agent recorded one)
  - Source and timestamp
- Click the row again to collapse it

---

## Example Usage

### Situation:
You asked an agent to fix a bug in the login system.

### What you'll see on the chart:
1. **Blue point** - agent searched for login-related code
2. **Purple point** - agent read the found file
3. **Pink point** - agent analyzed the problem
4. **Red point** - agent created a backup
5. **Orange point** - agent fixed the bug
6. **Green point** - agent ran tests

This way, you can **see exactly** what the agent did and in what order.

---

## Importing from the Command Line

You can also import sessions without using the web UI:

```bash
# Import only the newest session (default)
./run_prettify.sh

# Import ALL sessions at once
./run_prettify.sh --all

# Import a specific session file (relative path from ~/.codex/sessions/)
./run_prettify.sh --file=2026/02/12/rollout-2026-02-12T23-35-38-xxx.jsonl

# Import all and start the server
./run_prettify.sh --all --serve
```

---

## FAQ (Frequently Asked Questions)

### I don't see any points on the chart?
The session needs to be imported first. Go to **Log Manager** (`/logs/`) and import your sessions.

### Where are sessions stored?
Raw Codex logs are in `~/.codex/sessions/YYYY/MM/DD/*.jsonl`.
After import, converted JSON files are in `visualization/data/sessions_json/`.

### Which Codex versions are supported?
All sessions from **September 2025 onwards**. The parser automatically detects the JSONL format (Codex CLI changed its log format several times; all known variants are handled).

### A session shows an empty chart (no points)?
The session was probably imported with an older version of the parser. Solution:
1. Go to **Log Manager** (`/logs/`)
2. In the "Imported Sessions" table, click **Delete** next to the affected session
3. Re-import it using the checkboxes above

### Can I go back to older sessions?
Yes! All imported sessions are saved. Use the dropdown list on the visualization page or the Log Manager's "Imported Sessions" list.

### Can I import sessions from months ago?
Yes! The Log Manager shows all sessions grouped by month. Just check the desired months and click **Import Selected**.

### Do I need to install anything?
No extra tools needed. Just run `./run_prettify.sh --serve` and open the browser.

### The chart isn't loading?
1. Check if the Django server is running
2. Refresh the page (F5)
3. Make sure you've imported at least one session in Log Manager

---

## Tips

- **Rotate the chart** to see it from different perspectives
- **Use the table search** to find a specific step by keyword
- **Click a row** to see the full command/patch/output without leaving the page
- **Compare sessions** by selecting different files from the dropdown
- **Raw JSON** (at the bottom of the page) shows raw data - useful for debugging
- **Import All** in Log Manager is safe to run multiple times - already imported sessions are skipped

---

## Need Help?

If you have problems using the tool:
- **Developers**: Check **Developer Guide** (tab above)
- **Developers**: Check `codex_prettify.py` — it's the parser that converts JSONL to JSON

---

**Version**: 2.2
**Last updated**: 2026-02-15
