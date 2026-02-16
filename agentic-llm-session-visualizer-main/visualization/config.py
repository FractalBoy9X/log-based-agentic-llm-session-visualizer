"""Configuration helpers for environment-driven runtime settings."""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_CODEX_SESSIONS_DIR = Path.home() / ".codex" / "sessions"


def get_codex_sessions_dir() -> Path:
    """Return source directory for raw Codex JSONL sessions."""
    configured = os.getenv("CODEX_SESSIONS_DIR", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return DEFAULT_CODEX_SESSIONS_DIR


def format_path_for_display(path: Path) -> str:
    """Return a user-friendly path, preferring ~ for the current home dir."""
    resolved = path.expanduser().resolve()
    home = Path.home().resolve()
    try:
        rel = resolved.relative_to(home)
    except ValueError:
        return str(resolved)
    if str(rel) == ".":
        return "~"
    return f"~/{rel.as_posix()}"


def get_codex_sessions_dir_display() -> str:
    """Return session path formatted for UI/docs in templates."""
    return format_path_for_display(get_codex_sessions_dir())
