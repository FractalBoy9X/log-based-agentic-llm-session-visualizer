"""Agentic Thinking Visualization views."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any, Dict, Tuple

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from .loader import (
    MAX_EVENTS,
    build_agentic_thinking_spiral,
    get_plot_div,
    list_available_sessions,
    load_agentic_thinking_log,
)
from .config import get_codex_sessions_dir_display
from .log_manager import (
    delete_imported_session,
    get_already_imported,
    group_by_month,
    import_all_sessions,
    import_sessions,
    scan_codex_sessions,
)

logger = logging.getLogger(__name__)

INSTRUCTIONS_DIR = Path(__file__).resolve().parent / "instructions"
PROJECT_ROOT = Path(__file__).resolve().parents[2]
JSON_DOWNLOAD_SCRIPT = PROJECT_ROOT / "json_downloader" / "download_jsons.sh"

def _chart_instructions() -> str:
    sessions_dir = get_codex_sessions_dir_display()
    return (
        "The spiral chart shows the sequence of tool calls performed by Codex during a session. "
        "Each point represents a single event (search, command, edit, write, backup, note, read, analyze). "
        "The Z-axis grows with each step. Hover over points to see event details. "
        f"Sessions are imported from {sessions_dir} using the Log Manager."
    )


def _base_context() -> Dict[str, Any]:
    return {
        "plot_div": "",
        "events": [],
        "raw_log": "",
        "error_message": "",
        "chart_instructions": _chart_instructions(),
        "events_truncated": False,
        "max_events": MAX_EVENTS,
        "filter_stats": {"total": 0, "filtered": 0, "remaining": 0},
        "log_path": "",
        "meta": {},
        "available_sessions": [],
        "selected_file": "",
        "fetch_status": "",
        "fetch_message": "",
    }


def home(request: HttpRequest) -> HttpResponse:
    """Home page with links to visualization and instructions."""
    return render(request, "home.html", {
        "available_sessions": list_available_sessions(),
        "codex_sessions_dir_display": get_codex_sessions_dir_display(),
    })


def _run_json_download() -> Tuple[bool, str]:
    """Run JSON download pipeline using existing shell logic."""
    if not JSON_DOWNLOAD_SCRIPT.exists():
        return False, f"Download script not found: {JSON_DOWNLOAD_SCRIPT}"

    try:
        result = subprocess.run(
            [str(JSON_DOWNLOAD_SCRIPT)],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        return False, "Download timed out after 180 seconds."
    except OSError as exc:
        return False, f"Download failed to start: {exc}"

    merged_output = "\n".join(
        line for line in f"{result.stdout}\n{result.stderr}".splitlines() if line.strip()
    )
    if result.returncode != 0:
        last_line = merged_output.splitlines()[-1] if merged_output else "Unknown error."
        return False, f"Data refresh failed: {last_line}"

    exported_line = ""
    for line in merged_output.splitlines():
        if line.startswith("Exported: "):
            exported_line = line
            break

    if exported_line:
        return True, f"Data refreshed successfully. {exported_line}"
    return True, "Data refreshed successfully."


def agentic_thinking_visualization_view(request: HttpRequest) -> HttpResponse:
    """Main visualization view - universal for all LLM agents."""
    context = _base_context()

    selected_file = ""
    if request.method == "POST" and request.POST.get("action") == "refresh_data":
        selected_file = request.POST.get("file", "").strip()
        ok, message = _run_json_download()
        context["fetch_status"] = "success" if ok else "error"
        context["fetch_message"] = message

    # Get list of available sessions
    available_sessions = list_available_sessions()
    context["available_sessions"] = available_sessions

    # Get selected file from GET parameter (if exists)
    if not selected_file:
        selected_file = request.GET.get("file", "")
    context["selected_file"] = selected_file

    try:
        events, stats, raw_log, log_path, error_message, meta = load_agentic_thinking_log(
            selected_file=selected_file if selected_file else None
        )
        context["filter_stats"] = stats
        context["raw_log"] = raw_log
        context["log_path"] = log_path
        context["error_message"] = error_message
        context["events"] = events
        context["events_truncated"] = stats["filtered"] > 0
        context["meta"] = meta

        if events:
            # Extract agent name from meta (if exists)
            agent_name = "Agent"
            if meta and "agent" in meta:
                agent_info = meta["agent"]
                if isinstance(agent_info, dict):
                    agent_type = agent_info.get("type", "agent")
                    agent_name = agent_type.capitalize()
                    # Handle special names
                    name_map = {
                        "gpt4": "GPT-4",
                        "gpt-4": "GPT-4",
                        "claude": "Claude",
                        "gemini": "Gemini",
                        "codex": "Codex",
                        "cursor": "Cursor",
                        "llama": "Llama",
                        "copilot": "Copilot",
                    }
                    agent_name = name_map.get(agent_type.lower(), agent_name)

            fig = build_agentic_thinking_spiral(events, agent_name=agent_name)
            context["plot_div"] = get_plot_div(fig)
    except Exception:
        logger.exception("Agentic thinking visualization failed")
        context["error_message"] = "Failed to load agentic thinking log."

    return render(request, "agentic_thinking_visualization.html", context)


def log_manager_view(request: HttpRequest) -> HttpResponse:
    """Log Manager for scanning and importing sessions from configured source dir."""
    context: Dict[str, Any] = {
        "import_status": "",
        "import_messages": [],
        "import_count": 0,
    }

    # Handle POST actions
    if request.method == "POST":
        action = request.POST.get("action", "")

        if action == "import_selected":
            selected = request.POST.getlist("selected_files")
            if selected:
                count, messages = import_sessions(selected)
                context["import_status"] = "success" if count > 0 else "error"
                context["import_count"] = count
                context["import_messages"] = messages
            else:
                context["import_status"] = "error"
                context["import_messages"] = ["No files selected."]

        elif action == "import_all":
            count, messages = import_all_sessions()
            context["import_status"] = "success" if count > 0 else "info"
            context["import_count"] = count
            context["import_messages"] = messages

        elif action == "delete_session":
            filename = request.POST.get("filename", "").strip()
            if filename:
                ok, msg = delete_imported_session(filename)
                context["import_status"] = "success" if ok else "error"
                context["import_messages"] = [msg]
            else:
                context["import_status"] = "error"
                context["import_messages"] = ["No filename specified."]

    # Scan available sessions
    available = scan_codex_sessions()
    already_imported = get_already_imported()
    grouped = group_by_month(available)

    # Mark which files are already imported
    for month_sessions in grouped.values():
        for s in month_sessions:
            s["already_imported"] = s["rel_path"] in already_imported

    context["grouped_sessions"] = grouped
    context["total_available"] = len(available)
    context["total_imported"] = len(already_imported)
    context["imported_sessions"] = list_available_sessions()

    return render(request, "log_manager.html", context)


def _read_markdown_file(filename: str) -> str:
    """Read markdown file from instructions directory."""
    filepath = INSTRUCTIONS_DIR / filename
    if filepath.exists():
        return filepath.read_text(encoding="utf-8")
    return f"File not found: {filename}"


def instructions_view(request: HttpRequest) -> HttpResponse:
    """Instructions page with user and developer guides."""
    active_tab = request.GET.get("tab", "user")
    if active_tab not in ("user", "developer"):
        active_tab = "user"

    context = {
        "active_tab": active_tab,
        "user_guide": _read_markdown_file("user_guide.md"),
        "developer_guide": _read_markdown_file("developer_guide.md"),
    }

    return render(request, "instructions.html", context)


__all__ = ("home", "agentic_thinking_visualization_view", "log_manager_view", "instructions_view")
