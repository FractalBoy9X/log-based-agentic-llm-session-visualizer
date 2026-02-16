"""Template context processors for visualization app."""

from __future__ import annotations

from .config import get_codex_sessions_dir_display


def app_runtime_settings(_request):
    """Expose runtime settings in all templates."""
    return {
        "codex_sessions_dir_display": get_codex_sessions_dir_display(),
    }
