"""Agentic Thinking Data Loader - laduje dane JSON wygenerowane przez dowolnego agenta LLM."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np
import plotly.graph_objects as go
import plotly.offline as opy

# Plotly configuration
PLOTLY_BASE_CONFIG = {"displayModeBar": True, "displaylogo": False}
PRECISION_THRESHOLD = 10_000

MAX_EVENTS = 10_000
DATA_DIR = Path(__file__).resolve().parent / "data" / "sessions_json"

EVENT_COLORS = {
    "command": "#22c55e",    # zielony
    "search": "#38bdf8",     # niebieski
    "edit": "#f97316",       # pomaranczowy
    "write": "#f59e0b",      # zolty
    "backup": "#ef4444",     # czerwony
    "note": "#64748b",       # szary
    "read": "#8b5cf6",       # fioletowy
    "analyze": "#ec4899",    # rozowy
}


def _compute_spiral_positions(
    event_count: int,
    base_radius: float = 9.0,
    radius_step: float = 0.55,
    z_step: float = 2.0,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Oblicz pozycje 3D dla spirali."""
    dtype = np.float32 if event_count > PRECISION_THRESHOLD else np.float64
    indices = np.arange(event_count, dtype=dtype)
    angles = (2 * np.pi * indices) / max(event_count, 1)
    radii = base_radius + indices * radius_step

    x = np.round(np.cos(angles) * radii, 3)
    y = np.round(np.sin(angles) * radii, 3)
    z = np.round(indices * z_step, 3)

    return x, y, z


def _build_custom_z_axis(
    max_z: float, step: int = 500, z_step: float = 2.0
) -> Tuple[go.Scatter3d, go.Scatter3d]:
    """Zbuduj niestandardowa os Z z etykietami."""
    max_event_idx = int(max_z / z_step) if z_step > 0 else 0
    tick_events = list(range(0, max_event_idx + 1, step))
    if tick_events and tick_events[-1] < max_event_idx:
        tick_events.append(max_event_idx)
    elif not tick_events:
        tick_events = [0]

    tick_z = [idx * z_step for idx in tick_events]
    tick_x = [0.0] * len(tick_events)
    tick_y = [0.0] * len(tick_events)
    tick_labels = [str(idx) for idx in tick_events]

    axis_trace = go.Scatter3d(
        x=[0, 0],
        y=[0, 0],
        z=[0, max_z],
        mode="lines",
        line=dict(color="rgba(100, 116, 139, 0.6)", width=3),
        name="Events axis",
        hoverinfo="none",
        showlegend=False,
    )

    ticks_trace = go.Scatter3d(
        x=tick_x,
        y=tick_y,
        z=tick_z,
        mode="markers+text",
        marker=dict(size=4, color="#64748b", symbol="diamond"),
        text=tick_labels,
        textposition="middle left",
        textfont=dict(size=10, color="#64748b"),
        name="Scale",
        hoverinfo="text",
        hovertext=[f"Event {idx}" for idx in tick_events],
        showlegend=False,
    )

    return axis_trace, ticks_trace


def _normalize_events(raw_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalizuj zdarzenia do wspolnego formatu."""
    normalized: List[Dict[str, Any]] = []
    for idx, raw in enumerate(raw_events):
        event_type = str(raw.get("event_type") or raw.get("type") or "note").lower()
        label = (
            raw.get("label")
            or raw.get("summary")
            or raw.get("command")
            or raw.get("title")
            or raw.get("detail")
            or "Event"
        )
        # Normalize label to single-line (handles \n from any schema version,
        # including literal \uXXXX sequences that some older generators produce)
        label = re.sub(r'\s+', ' ', str(label)).strip()
        normalized.append(
            {
                "event_index": raw.get("event_index", idx),
                "event_type": event_type,
                "label": label,
                "detail": raw.get("detail", ""),
                "source": raw.get("source", ""),
                "thinking": raw.get("thinking", ""),
                "timestamp": raw.get("timestamp", ""),
            }
        )
    return normalized


def list_available_sessions() -> List[Dict[str, Any]]:
    """
    Zwroc liste dostepnych plikow JSON sesji.

    Returns:
        Lista slownikow z informacjami o plikach:
        - filename: nazwa pliku
        - path: pelna sciezka
        - modified: data modyfikacji (timestamp)
        - size: rozmiar w bajtach
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    sessions = []

    # Ignoruj pliki macOS resource fork (._*)
    for path in sorted(DATA_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        if path.name.startswith("._"):
            continue
        stat = path.stat()
        sessions.append({
            "filename": path.name,
            "path": str(path),
            "modified": stat.st_mtime,
            "size": stat.st_size,
        })

    return sessions


def load_agentic_thinking_log(
    max_events: int = MAX_EVENTS,
    selected_file: str | None = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, int], str, str, str, Dict[str, Any]]:
    """
    Zaladuj plik JSON z logiem agenta LLM.

    Args:
        max_events: Maksymalna liczba zdarzen do zaladowania
        selected_file: Nazwa pliku do zaladowania (opcjonalnie). Jesli None, laduje najnowszy.

    Returns:
        Tuple[events, stats, raw_log, log_path, error_message, meta]
        - events: Lista znormalizowanych zdarzen
        - stats: Statystyki (total, filtered, remaining)
        - raw_log: Surowy tekst JSON
        - log_path: Sciezka do zaladowanego pliku
        - error_message: Komunikat bledu (jesli wystapil)
        - meta: Metadane sesji (label, generated_at, source, description, agent)
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Ignoruj pliki macOS resource fork (._*)
    log_files = sorted(
        (p for p in DATA_DIR.glob("*.json") if not p.name.startswith("._")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    if not log_files:
        return (
            [],
            {"total": 0, "filtered": 0, "remaining": 0},
            "",
            "",
            "No JSON files found. Use Log Manager to import sessions or place files in data/sessions_json/",
            {},
        )

    # Wybierz plik do zaladowania
    if selected_file:
        # Szukaj pliku po nazwie
        matching = [p for p in log_files if p.name == selected_file]
        if matching:
            log_path = matching[0]
        else:
            return (
                [],
                {"total": 0, "filtered": 0, "remaining": 0},
                "",
                "",
                f"File not found: {selected_file}",
                {},
            )
    else:
        # Domyslnie najnowszy plik
        log_path = log_files[0]
    raw_text = log_path.read_text(encoding="utf-8", errors="replace")

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as e:
        return (
            [],
            {"total": 0, "filtered": 0, "remaining": 0},
            raw_text,
            str(log_path),
            f"Invalid JSON format: {e}",
            {},
        )

    # Wyciagnij metadane
    meta = data.get("meta", {})

    # Wyciagnij zdarzenia
    if isinstance(data, dict):
        raw_events = data.get("events", [])
    elif isinstance(data, list):
        raw_events = data
        meta = {}
    else:
        raw_events = []

    events = _normalize_events(raw_events)
    total = len(events)

    if total > max_events:
        events = events[:max_events]

    stats = {
        "total": total,
        "filtered": total - len(events),
        "remaining": len(events),
    }

    return events, stats, raw_text, str(log_path), "", meta


def build_agentic_thinking_spiral(events: List[Dict[str, Any]], agent_name: str = "Agent") -> go.Figure:
    """Zbuduj spiralny wykres 3D dla zdarzen agenta LLM."""
    event_count = len(events)
    z_step = 2.0

    x, y, z = _compute_spiral_positions(event_count, z_step=z_step)
    max_z = float(z[-1]) if len(z) > 0 else 0

    axis_trace, ticks_trace = _build_custom_z_axis(max_z, step=5, z_step=z_step)

    # Utworz linie laczace punkty
    edge_x = (
        np.empty(event_count * 3 - 2, dtype=np.float32)
        if event_count > 1
        else np.array([], dtype=np.float32)
    )
    edge_y = (
        np.empty(event_count * 3 - 2, dtype=np.float32)
        if event_count > 1
        else np.array([], dtype=np.float32)
    )
    edge_z = (
        np.empty(event_count * 3 - 2, dtype=np.float32)
        if event_count > 1
        else np.array([], dtype=np.float32)
    )

    if event_count > 1:
        for idx in range(event_count - 1):
            base = idx * 3
            edge_x[base] = x[idx]
            edge_x[base + 1] = x[idx + 1]
            edge_x[base + 2] = np.nan
            edge_y[base] = y[idx]
            edge_y[base + 1] = y[idx + 1]
            edge_y[base + 2] = np.nan
            edge_z[base] = z[idx]
            edge_z[base + 1] = z[idx + 1]
            edge_z[base + 2] = np.nan

    line_trace = go.Scatter3d(
        x=edge_x.tolist(),
        y=edge_y.tolist(),
        z=edge_z.tolist(),
        mode="lines",
        line=dict(color="rgba(148, 163, 184, 0.3)", width=1.5),
        name="Flow",
        hoverinfo="none",
        showlegend=True,
    )

    traces: List[go.Scatter3d] = [axis_trace, ticks_trace, line_trace]
    types = sorted({event.get("event_type", "note") for event in events})

    # Utworz slady dla kazdego typu zdarzenia
    for etype in types:
        type_indices = [i for i, e in enumerate(events) if e.get("event_type") == etype]
        if not type_indices:
            continue

        color = EVENT_COLORS.get(etype, "#94a3b8")
        type_x = x[type_indices].tolist()
        type_y = y[type_indices].tolist()
        type_z = z[type_indices].tolist()

        hover_text = []
        for i in type_indices:
            event = events[i]
            label = str(event.get("label", ""))[:120]
            detail = str(event.get("detail", ""))[:300]
            thinking = str(event.get("thinking", ""))[:300]
            source = str(event.get("source", ""))
            timestamp = str(event.get("timestamp", ""))
            meta_parts = [p for p in [source, timestamp] if p]
            meta = " | ".join(meta_parts)

            # Build hover text with optional thinking field
            hover_parts = [f"<b>#{event.get('event_index', i)} - {etype.upper()}</b>", label]
            if detail:
                hover_parts.append(f"<i>{detail}</i>")
            if thinking:
                hover_parts.append(f"<b>Thinking:</b> {thinking}")
            if meta:
                hover_parts.append(meta)
            hover_text.append("<br>".join(hover_parts))

        marker_trace = go.Scatter3d(
            x=type_x,
            y=type_y,
            z=type_z,
            mode="markers",
            marker=dict(
                size=7, color=color, line=dict(color="#0f172a", width=0.5), opacity=0.9
            ),
            name=etype.upper(),
            hovertext=hover_text,
            hoverinfo="text",
            showlegend=True,
        )
        traces.append(marker_trace)

    layout = go.Layout(
        title=f"{agent_name} Thinking Spiral ({event_count:,} events)",
        margin=dict(l=0, r=0, b=0, t=40),
        legend=dict(
            yanchor="top",
            y=0.99,
            xanchor="left",
            x=0.01,
            bgcolor="rgba(255, 255, 255, 0.7)",
        ),
        scene=dict(
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
            zaxis=dict(visible=False),
            camera=dict(eye=dict(x=1.5, y=1.2, z=1.0)),
            aspectmode="data",
        ),
    )

    return go.Figure(data=traces, layout=layout)


def get_plot_div(fig: go.Figure) -> str:
    """Konwertuj wykres Plotly do HTML div."""
    return opy.plot(fig, output_type="div", auto_open=False, config=PLOTLY_BASE_CONFIG)


__all__ = [
    "MAX_EVENTS",
    "DATA_DIR",
    "EVENT_COLORS",
    "list_available_sessions",
    "load_agentic_thinking_log",
    "build_agentic_thinking_spiral",
    "get_plot_div",
]
