#!/usr/bin/env python3
"""
codex_prettify.py

Parser i prettifier logow agenta Codex (GPT).

Obsluguje:
- NDJSON (1 JSON na linie) oraz sklejone obiekty JSON
- Normalizacja do NormalizedEvent
- Pretty output (kolorowy terminal) -- domyslny tryb
- JSONL / JSON / CSV / split-outputs -- kompatybilnosc wsteczna
- Filtrowanie (po turnie, roli, typie, podtypie)
- Podsumowanie sesji (--summary)

Uzycie:
  python3 codex_prettify.py session.jsonl
  python3 codex_prettify.py session.jsonl --summary
  python3 codex_prettify.py session.jsonl --turn 2 --no-color
  python3 codex_prettify.py session.jsonl --jsonl out.jsonl
  cat session.jsonl | python3 codex_prettify.py -
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import shutil
import sys
import textwrap
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import (
    Any, Dict, Generator, Iterable, List, Optional, Set, TextIO, Union,
)

JSONDict = Dict[str, Any]

# ---------------------------------------------------------------------------
# Layer 1: Parsing (reuse from codex_log_parser.py)
# ---------------------------------------------------------------------------

def _iso_to_epoch_ms(ts: Optional[str]) -> Optional[int]:
    if not ts or not isinstance(ts, str):
        return None
    try:
        if ts.endswith("Z"):
            dt = datetime.fromisoformat(ts[:-1]).replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


def _iso_short_time(ts: Optional[str]) -> str:
    """Extract HH:MM:SS from ISO timestamp."""
    if not ts:
        return "??:??:??"
    try:
        if ts.endswith("Z"):
            dt = datetime.fromisoformat(ts[:-1]).replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(ts)
        return dt.strftime("%H:%M:%S")
    except Exception:
        return ts[:19] if len(ts) >= 19 else ts


def iter_json_objects(stream: TextIO) -> Generator[JSONDict, None, None]:
    """
    Read JSON objects from a stream.
    Supports NDJSON/JSONL and concatenated (back-to-back) JSON objects.
    """
    decoder = json.JSONDecoder()
    buf = ""

    def skip_ws(s: str, j: int) -> int:
        while j < len(s) and s[j].isspace():
            j += 1
        return j

    for line in stream:
        if not line:
            continue
        buf += line
        i = skip_ws(buf, 0)

        while i < len(buf):
            try:
                obj, end = decoder.raw_decode(buf, i)
            except json.JSONDecodeError:
                break
            if isinstance(obj, dict):
                yield obj
            i = skip_ws(buf, end)

        if i > 0:
            buf = buf[i:]

        if len(buf) > 50_000_000:
            raise RuntimeError("Buffer exceeded 50MB while parsing. Input may be malformed.")

    if buf.strip():
        i = skip_ws(buf, 0)
        while i < len(buf):
            try:
                obj, end = decoder.raw_decode(buf, i)
            except json.JSONDecodeError:
                break
            if isinstance(obj, dict):
                yield obj
            i = skip_ws(buf, end)


# ---------------------------------------------------------------------------
# Layer 2: Normalization
# ---------------------------------------------------------------------------

@dataclass
class NormalizedEvent:
    ts: Optional[str]
    ts_ms: Optional[int]
    kind: str
    subkind: Optional[str]
    role: Optional[str]
    turn_id: Optional[str]
    message: Optional[str]
    data: JSONDict


def normalize_record(rec: JSONDict) -> NormalizedEvent:
    ts = rec.get("timestamp")
    ts_ms = _iso_to_epoch_ms(ts if isinstance(ts, str) else None)

    kind_raw = rec.get("type")
    kind = kind_raw if isinstance(kind_raw, str) else "unknown"

    payload = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
    subkind = payload.get("type") if isinstance(payload.get("type"), str) else None

    turn_id = payload.get("turn_id") or rec.get("turn_id")
    if not isinstance(turn_id, str):
        turn_id = None

    role: Optional[str] = None
    msg: Optional[str] = None
    data: JSONDict = {}

    if kind == "response_item":
        if subkind == "message":
            role_val = payload.get("role")
            role = role_val if isinstance(role_val, str) else None

            content = payload.get("content")
            if isinstance(content, list):
                for c in content:
                    if isinstance(c, dict):
                        for key in ("text", "output_text", "input_text", "message"):
                            t = c.get(key)
                            if isinstance(t, str) and t.strip():
                                msg = t.strip()
                                break
                        if msg:
                            break
            data = payload

        elif subkind == "reasoning":
            summary = payload.get("summary")
            if isinstance(summary, list):
                for s in summary:
                    if isinstance(s, dict):
                        t = s.get("text")
                        if isinstance(t, str) and t.strip():
                            msg = t.strip()
                            break
            data = payload

        elif subkind in ("custom_tool_call", "function_call"):
            name = payload.get("name", "tool")
            msg = f"{name}"
            # Normalize: function_call uses 'arguments', custom_tool_call uses 'input'
            if subkind == "function_call":
                data = {**payload, "input": payload.get("arguments", "")}
                subkind = "custom_tool_call"
            else:
                data = payload

        elif subkind in ("custom_tool_call_output", "function_call_output"):
            raw_output = payload.get("output")
            if isinstance(raw_output, str):
                try:
                    parsed = json.loads(raw_output)
                    if isinstance(parsed, dict):
                        msg = parsed.get("output", raw_output)
                    else:
                        msg = raw_output
                except (json.JSONDecodeError, TypeError):
                    msg = raw_output
            data = payload
            if subkind == "function_call_output":
                subkind = "custom_tool_call_output"

        else:
            data = payload

    elif kind == "event_msg":
        if subkind in ("agent_message", "user_message"):
            m = payload.get("message")
            msg = m if isinstance(m, str) else None
        elif subkind == "agent_reasoning":
            t = payload.get("text")
            msg = t if isinstance(t, str) else None
        elif subkind == "task_complete":
            lm = payload.get("last_agent_message")
            msg = lm if isinstance(lm, str) else None
        elif subkind == "task_started":
            msg = None
        elif subkind == "token_count":
            msg = None
        data = payload

    elif kind == "turn_context":
        data = {
            "turn_id": payload.get("turn_id"),
            "cwd": payload.get("cwd"),
            "model": payload.get("model"),
            "approval_policy": payload.get("approval_policy"),
            "sandbox_policy": payload.get("sandbox_policy"),
            "collaboration_mode": payload.get("collaboration_mode"),
            "effort": payload.get("effort"),
            "personality": payload.get("personality"),
            "truncation_policy": payload.get("truncation_policy"),
            "summary": payload.get("summary"),
        }

    elif kind == "session_meta":
        data = payload

    else:
        data = payload if payload else rec

    if role is None and subkind == "user_message":
        role = "user"
    if role is None and subkind == "agent_message":
        role = "assistant"

    return NormalizedEvent(
        ts=ts if isinstance(ts, str) else None,
        ts_ms=ts_ms,
        kind=kind,
        subkind=subkind,
        role=role,
        turn_id=turn_id,
        message=msg,
        data=data if isinstance(data, dict) else {"value": data},
    )


def normalize_stream(records: Iterable[JSONDict]) -> Generator[NormalizedEvent, None, None]:
    for rec in records:
        if isinstance(rec, dict):
            yield normalize_record(rec)


# ---------------------------------------------------------------------------
# Layer 2b: V1 Format Support (Codex pre-October 2025)
#
# Old format (sep-2025) uses flat top-level fields instead of a payload wrapper:
#   { type: "message", role: "user"|"assistant", content: [{type, text}] }
#   { type: "reasoning", summary: [{text}], encrypted_content: ... }
#   { type: "function_call", name, arguments, call_id }
#   { type: "function_call_output", call_id, output }
#   { record_type: "state" }   <- state markers, skip
#   { id, timestamp, instructions, git }  <- session header (no type field)
# ---------------------------------------------------------------------------

_V1_TYPES = {"message", "reasoning", "function_call", "function_call_output"}


def _detect_v1_format(records: List[JSONDict]) -> bool:
    """Returns True if records look like old (pre-Oct-2025) Codex JSONL format."""
    for rec in records[:10]:
        if rec.get("type") in _V1_TYPES:
            return True
    return False


def _extract_v1_text(rec: JSONDict) -> Optional[str]:
    """Extract text content from a v1 message record."""
    content = rec.get("content", [])
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                for key in ("text", "input_text", "output_text"):
                    val = item.get(key)
                    if isinstance(val, str) and val.strip():
                        return val.strip()
    elif isinstance(content, str) and content.strip():
        return content.strip()
    return None


def normalize_v1_stream(records: List[JSONDict]) -> List[NormalizedEvent]:
    """Normalize old-format (v1) Codex JSONL records to NormalizedEvent list.

    Creates synthetic turn structure: each user message triggers a new turn.
    """
    events: List[NormalizedEvent] = []
    turn_count = 0
    turn_id = "v1-turn-0"

    for rec in records:
        t = rec.get("type")
        rt = rec.get("record_type")

        # Skip state markers
        if rt == "state":
            continue

        # Session header: first line has id/timestamp but no type
        if t is None and "id" in rec:
            ts = rec.get("timestamp")
            events.append(NormalizedEvent(
                ts=ts,
                ts_ms=_iso_to_epoch_ms(ts),
                kind="session_meta",
                subkind=None,
                role=None,
                turn_id=None,
                message=None,
                data={
                    "id": rec.get("id", ""),
                    "timestamp": ts,
                    "cwd": "",
                    "originator": "codex_vscode",
                    "cli_version": "",
                    "model_provider": "openai",
                },
            ))
            continue

        # User message → synthetic task_started + user message event
        if t == "message" and rec.get("role") == "user":
            turn_count += 1
            turn_id = f"v1-turn-{turn_count}"
            # Synthetic task_started so build_session() creates a new Turn
            events.append(NormalizedEvent(
                ts=None, ts_ms=None,
                kind="event_msg",
                subkind="task_started",
                role=None,
                turn_id=turn_id,
                message=None,
                data={"turn_id": turn_id},
            ))
            text = _extract_v1_text(rec)
            events.append(NormalizedEvent(
                ts=None, ts_ms=None,
                kind="response_item",
                subkind="message",
                role="user",
                turn_id=turn_id,
                message=text,
                data={"role": "user", "content": rec.get("content", []), "type": "message"},
            ))
            continue

        # Assistant message
        if t == "message" and rec.get("role") == "assistant":
            text = _extract_v1_text(rec)
            events.append(NormalizedEvent(
                ts=None, ts_ms=None,
                kind="response_item",
                subkind="message",
                role="assistant",
                turn_id=turn_id,
                message=text,
                data={"role": "assistant", "content": rec.get("content", []), "type": "message"},
            ))
            continue

        # Reasoning / thinking
        if t == "reasoning":
            summary = rec.get("summary", [])
            if isinstance(summary, list):
                text = " ".join(
                    s.get("text", "") for s in summary
                    if isinstance(s, dict) and s.get("text")
                ).strip() or None
            else:
                text = None
            events.append(NormalizedEvent(
                ts=None, ts_ms=None,
                kind="response_item",
                subkind="reasoning",
                role=None,
                turn_id=turn_id,
                message=text,
                data={"summary": summary, "type": "reasoning"},
            ))
            continue

        # Function call (tool invocation)
        if t == "function_call":
            name = rec.get("name", "tool")
            args = rec.get("arguments", "")
            events.append(NormalizedEvent(
                ts=None, ts_ms=None,
                kind="response_item",
                subkind="custom_tool_call",
                role=None,
                turn_id=turn_id,
                message=name,
                data={"name": name, "input": args, "call_id": rec.get("call_id"), "type": "custom_tool_call"},
            ))
            continue

        # Function call output (tool result)
        if t == "function_call_output":
            output = rec.get("output", "")
            if not isinstance(output, str):
                output = json.dumps(output, ensure_ascii=False)
            events.append(NormalizedEvent(
                ts=None, ts_ms=None,
                kind="response_item",
                subkind="custom_tool_call_output",
                role=None,
                turn_id=turn_id,
                message=output[:500],
                data={"output": output, "call_id": rec.get("call_id"), "type": "custom_tool_call_output"},
            ))
            continue

    return events


# ---------------------------------------------------------------------------
# Layer 3: Session Model
# ---------------------------------------------------------------------------

@dataclass
class Turn:
    turn_id: str
    turn_number: int
    model: Optional[str] = None
    effort: Optional[str] = None
    personality: Optional[str] = None
    start_ts: Optional[str] = None
    end_ts: Optional[str] = None
    user_message: Optional[str] = None
    events: List[NormalizedEvent] = field(default_factory=list)
    token_usage: Optional[JSONDict] = None


@dataclass
class Session:
    session_id: str = ""
    session_ts: Optional[str] = None
    cwd: str = ""
    originator: str = ""
    cli_version: str = ""
    model_provider: str = ""
    turns: List[Turn] = field(default_factory=list)
    total_token_usage: Optional[JSONDict] = None
    preamble_events: List[NormalizedEvent] = field(default_factory=list)


def build_session(events: List[NormalizedEvent]) -> Session:
    session = Session()
    current_turn: Optional[Turn] = None
    turn_number = 0

    # Detect if session has explicit task_started events.
    # Older Codex versions (pre-v0.100) omit task_started/task_complete.
    has_task_started = any(
        ev.kind == "event_msg" and ev.subkind == "task_started"
        for ev in events
    )

    for ev in events:
        # Session metadata
        if ev.kind == "session_meta":
            session.session_id = ev.data.get("id", "")
            session.session_ts = ev.data.get("timestamp") or ev.ts
            session.cwd = ev.data.get("cwd", "")
            session.originator = ev.data.get("originator", "")
            session.cli_version = ev.data.get("cli_version", "")
            session.model_provider = ev.data.get("model_provider", "")
            session.preamble_events.append(ev)
            continue

        # Task started -> new turn
        if ev.kind == "event_msg" and ev.subkind == "task_started":
            turn_number += 1
            current_turn = Turn(
                turn_id=ev.turn_id or ev.data.get("turn_id", ""),
                turn_number=turn_number,
                start_ts=ev.ts,
            )
            current_turn.events.append(ev)
            session.turns.append(current_turn)
            continue

        # Fallback: older Codex omits task_started — use user_message as implicit turn boundary
        if (not has_task_started
                and ev.kind == "event_msg"
                and ev.subkind == "user_message"):
            turn_number += 1
            current_turn = Turn(
                turn_id=ev.turn_id or f"implicit-turn-{turn_number}",
                turn_number=turn_number,
                start_ts=ev.ts,
            )
            session.turns.append(current_turn)
            # Fall through: let this event also be added to the turn below

        # Turn context -> enrich current turn metadata
        if ev.kind == "turn_context":
            if current_turn is None:
                # Turn context before first task_started -> preamble
                session.preamble_events.append(ev)
                continue
            current_turn.model = ev.data.get("model")
            current_turn.effort = ev.data.get("effort")
            current_turn.personality = ev.data.get("personality")
            current_turn.events.append(ev)
            continue

        # Before first turn -> preamble
        if current_turn is None:
            session.preamble_events.append(ev)
            continue

        # Accumulate events into current turn
        current_turn.events.append(ev)

        # Track user message
        if ev.subkind == "user_message" and ev.message:
            current_turn.user_message = ev.message

        # Track token usage (keep last with info)
        if ev.subkind == "token_count":
            info = ev.data.get("info")
            if isinstance(info, dict) and info:
                current_turn.token_usage = info
                session.total_token_usage = info

        # Track end timestamp
        if ev.subkind == "task_complete":
            current_turn.end_ts = ev.ts

        # Update end_ts to last event ts
        if ev.ts and current_turn.end_ts is None:
            current_turn.end_ts = ev.ts

    return session


# ---------------------------------------------------------------------------
# Layer 4: ANSI Colors
# ---------------------------------------------------------------------------

class Color:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    GRAY = "\033[90m"

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def style(self, text: str, *codes: str) -> str:
        if not self.enabled or not codes:
            return text
        return "".join(codes) + text + self.RESET


# ---------------------------------------------------------------------------
# Layer 5: Formatting Helpers
# ---------------------------------------------------------------------------

def format_number(n: Any) -> str:
    if n is None:
        return "?"
    try:
        return f"{int(n):,}"
    except (ValueError, TypeError):
        return str(n)


def format_duration_sec(start_ms: Optional[int], end_ms: Optional[int]) -> str:
    if start_ms is None or end_ms is None:
        return "?"
    diff = (end_ms - start_ms) / 1000.0
    if diff < 0:
        return "?"
    if diff < 60:
        return f"{diff:.0f}s"
    minutes = int(diff // 60)
    seconds = int(diff % 60)
    return f"{minutes}m{seconds}s"


def _indent(text: str, prefix: str = "  ") -> str:
    return textwrap.indent(text, prefix)


# ---------------------------------------------------------------------------
# Layer 6: Filtering
# ---------------------------------------------------------------------------

@dataclass
class FilterSpec:
    turns: Optional[Set[int]] = None
    roles: Optional[Set[str]] = None
    kinds: Optional[Set[str]] = None
    subkinds: Optional[Set[str]] = None

    def matches_event(self, ev: NormalizedEvent) -> bool:
        if self.roles and ev.role not in self.roles:
            return False
        if self.kinds and ev.kind not in self.kinds:
            return False
        if self.subkinds and ev.subkind not in self.subkinds:
            return False
        return True

    @property
    def has_event_filters(self) -> bool:
        return bool(self.roles or self.kinds or self.subkinds)


def parse_filter_spec(args: argparse.Namespace) -> FilterSpec:
    spec = FilterSpec()
    if args.turn:
        spec.turns = set()
        for part in args.turn.split(","):
            part = part.strip()
            if part.isdigit():
                spec.turns.add(int(part))
    if args.role:
        spec.roles = {r.strip() for r in args.role.split(",")}
    if args.kind:
        spec.kinds = {k.strip() for k in args.kind.split(",")}
    if args.subkind:
        spec.subkinds = {s.strip() for s in args.subkind.split(",")}
    return spec


# ---------------------------------------------------------------------------
# Layer 7: Pretty Renderer
# ---------------------------------------------------------------------------

# Events to skip in pretty mode (internal plumbing)
_SKIP_SUBKINDS_DEFAULT = {"task_started"}
_SKIP_KINDS_DEFAULT = {"turn_context"}
# event_msg subkinds that duplicate response_item content
_EVENT_MSG_DUPLICATES = {"user_message", "agent_message", "agent_reasoning", "task_complete"}
_DEVELOPER_ROLES = {"developer"}


class PrettyRenderer:
    def __init__(
        self,
        color: Color,
        width: int = 100,
        verbose: bool = False,
        show_tokens: bool = False,
        show_patches: bool = False,
    ):
        self.c = color
        self.width = width
        self.verbose = verbose
        self.show_tokens = show_tokens
        self.show_patches = show_patches

    def render_session(
        self,
        session: Session,
        out: TextIO,
        filters: Optional[FilterSpec] = None,
        summary_only: bool = False,
    ) -> None:
        self.render_header(session, out)

        if not summary_only:
            if self.verbose and session.preamble_events:
                out.write(self.c.style(
                    "\n--- Preamble (developer/system) " + "-" * (self.width - 33) + "\n",
                    Color.DIM, Color.MAGENTA,
                ))
                for ev in session.preamble_events:
                    if ev.kind == "session_meta":
                        continue
                    self._render_event(ev, out)

            for turn in session.turns:
                if filters and filters.turns and turn.turn_number not in filters.turns:
                    continue
                self.render_turn(turn, out, filters)

        out.write("\n")
        self.render_summary(session, out)

    def render_header(self, session: Session, out: TextIO) -> None:
        line = "=" * self.width
        out.write(self.c.style(line, Color.BOLD, Color.CYAN) + "\n")
        title = " CODEX SESSION"
        out.write(self.c.style(title, Color.BOLD, Color.CYAN) + "\n")
        out.write(self.c.style(line, Color.BOLD, Color.CYAN) + "\n")

        def kv(key: str, val: str) -> str:
            label = self.c.style(f"{key:<10}:", Color.GRAY)
            return f"{label} {val}\n"

        out.write(kv("Session", session.session_id or "?"))
        if session.session_ts:
            out.write(kv("Started", _format_ts_display(session.session_ts)))
        out.write(kv("CWD", session.cwd or "?"))
        source = session.originator
        if session.cli_version:
            source += f" (v{session.cli_version})"
        out.write(kv("Source", source))
        out.write(kv("Provider", session.model_provider or "?"))
        out.write(self.c.style(line, Color.BOLD, Color.CYAN) + "\n")

    def render_turn(self, turn: Turn, out: TextIO, filters: Optional[FilterSpec] = None) -> None:
        # Turn header
        header_line = f"--- Turn {turn.turn_number} "
        header_line += "-" * (self.width - len(header_line))
        out.write("\n" + self.c.style(header_line, Color.BOLD, Color.WHITE) + "\n")

        # Metadata line
        meta_parts = []
        if turn.model:
            meta_parts.append(f"Model: {turn.model}")
        if turn.effort:
            meta_parts.append(f"Effort: {turn.effort}")

        start_time = _iso_short_time(turn.start_ts)
        end_time = _iso_short_time(turn.end_ts)
        duration = format_duration_sec(
            _iso_to_epoch_ms(turn.start_ts),
            _iso_to_epoch_ms(turn.end_ts),
        )
        meta_parts.append(f"{start_time} - {end_time} ({duration})")
        out.write(self.c.style(" | ".join(meta_parts), Color.GRAY) + "\n")

        # Events
        for ev in turn.events:
            # Skip internal events
            if ev.subkind in _SKIP_SUBKINDS_DEFAULT:
                continue
            if ev.kind in _SKIP_KINDS_DEFAULT and not self.verbose:
                continue

            # Skip event_msg entries that duplicate response_item content
            if ev.kind == "event_msg" and ev.subkind in _EVENT_MSG_DUPLICATES:
                continue

            # Skip developer messages unless verbose
            if ev.role in _DEVELOPER_ROLES and not self.verbose:
                continue

            # Skip token_count unless show_tokens
            if ev.subkind == "token_count" and not self.show_tokens:
                continue

            # Apply event-level filters
            if filters and filters.has_event_filters:
                if not filters.matches_event(ev):
                    continue

            self._render_event(ev, out)

        # Turn-ending token summary
        if turn.token_usage:
            self._render_token_summary(turn.token_usage, out)

    def _render_event(self, ev: NormalizedEvent, out: TextIO) -> None:
        if ev.kind == "response_item":
            self._render_response_item(ev, out)
        elif ev.kind == "event_msg":
            self._render_event_msg(ev, out)
        elif ev.kind == "turn_context" and self.verbose:
            model = ev.data.get("model", "?")
            effort = ev.data.get("effort", "?")
            out.write(self.c.style(
                f"  [CONTEXT] model={model} effort={effort}\n",
                Color.DIM, Color.MAGENTA,
            ))

    def _render_response_item(self, ev: NormalizedEvent, out: TextIO) -> None:
        if ev.subkind == "message":
            self._render_message(ev, out)
        elif ev.subkind == "reasoning":
            if ev.message:
                label = self.c.style("  [REASONING] ", Color.GRAY)
                text = self.c.style(ev.message, Color.DIM)
                out.write(f"\n{label}{text}\n")
        elif ev.subkind == "custom_tool_call":
            self._render_tool_call(ev, out)
        elif ev.subkind == "custom_tool_call_output":
            self._render_tool_output(ev, out)

    def _render_message(self, ev: NormalizedEvent, out: TextIO) -> None:
        if not ev.message:
            return

        phase = ev.data.get("phase", "")
        role = (ev.role or "?").upper()

        if ev.role == "user":
            label = self.c.style(f"  [{role}] ", Color.BOLD, Color.GREEN)
            text = self.c.style(ev.message, Color.GREEN)
        elif ev.role == "assistant":
            if phase == "commentary":
                label = self.c.style(f"  [{role} commentary] ", Color.DIM, Color.WHITE)
                text = self.c.style(ev.message, Color.DIM)
            else:
                label = self.c.style(f"  [{role}] ", Color.BOLD, Color.WHITE)
                text = ev.message
        elif ev.role == "developer":
            # Truncate long developer messages
            display = ev.message
            if len(display) > 200 and not self.verbose:
                display = display[:200] + "..."
            label = self.c.style(f"  [{role}] ", Color.MAGENTA)
            text = self.c.style(display, Color.DIM, Color.MAGENTA)
        else:
            label = self.c.style(f"  [{role}] ", Color.WHITE)
            text = ev.message

        out.write(f"\n{label}{text}\n")

    def _render_tool_call(self, ev: NormalizedEvent, out: TextIO) -> None:
        tool_name = ev.message or ev.data.get("name", "tool")
        label = self.c.style(f"  [TOOL] {tool_name}", Color.BOLD, Color.YELLOW)
        out.write(f"\n{label}\n")

        tool_input = ev.data.get("input", "")
        if isinstance(tool_input, str) and tool_input.strip():
            lines = tool_input.strip().split("\n")
            max_lines = len(lines) if self.show_patches else 8

            for line in lines[:max_lines]:
                if line.startswith("+"):
                    out.write(self.c.style(f"    {line}", Color.GREEN) + "\n")
                elif line.startswith("-"):
                    out.write(self.c.style(f"    {line}", Color.RED) + "\n")
                elif line.startswith("***"):
                    out.write(self.c.style(f"    {line}", Color.CYAN) + "\n")
                else:
                    out.write(self.c.style(f"    {line}", Color.DIM, Color.YELLOW) + "\n")

            if len(lines) > max_lines:
                out.write(self.c.style(
                    f"    ...(truncated, {len(lines)} lines total)\n",
                    Color.DIM,
                ))

    def _render_tool_output(self, ev: NormalizedEvent, out: TextIO) -> None:
        display = ev.message or ""
        if isinstance(display, str) and len(display) > 200 and not self.verbose:
            display = display[:200] + "..."
        label = self.c.style("  [TOOL RESULT] ", Color.DIM, Color.YELLOW)
        text = self.c.style(display, Color.DIM, Color.YELLOW)
        out.write(f"{label}{text}\n")

    def _render_event_msg(self, ev: NormalizedEvent, out: TextIO) -> None:
        if ev.subkind == "user_message" and ev.message:
            label = self.c.style("  [USER] ", Color.BOLD, Color.GREEN)
            text = self.c.style(ev.message.strip(), Color.GREEN)
            out.write(f"\n{label}{text}\n")

        elif ev.subkind == "agent_message" and ev.message:
            label = self.c.style("  [ASSISTANT] ", Color.BOLD, Color.WHITE)
            out.write(f"\n{label}{ev.message.strip()}\n")

        elif ev.subkind == "agent_reasoning" and ev.message:
            label = self.c.style("  [REASONING] ", Color.GRAY)
            text = self.c.style(ev.message, Color.DIM)
            out.write(f"\n{label}{text}\n")

        elif ev.subkind == "task_complete" and ev.message:
            # Already shown via agent_message, skip to avoid duplication
            pass

        elif ev.subkind == "token_count" and self.show_tokens:
            self._render_token_inline(ev, out)

    def _render_token_inline(self, ev: NormalizedEvent, out: TextIO) -> None:
        info = ev.data.get("info")
        if not isinstance(info, dict) or not info:
            return
        last = info.get("last_token_usage", {})
        if not last:
            return
        parts = []
        parts.append(f"in={format_number(last.get('input_tokens'))}")
        cached = last.get("cached_input_tokens")
        if cached:
            parts.append(f"(cached={format_number(cached)})")
        parts.append(f"out={format_number(last.get('output_tokens'))}")
        reasoning = last.get("reasoning_output_tokens")
        if reasoning:
            parts.append(f"reasoning={format_number(reasoning)}")
        parts.append(f"total={format_number(last.get('total_tokens'))}")
        line = self.c.style(f"  Tokens (last): {' '.join(parts)}", Color.DIM, Color.GRAY)
        out.write(f"{line}\n")

    def _render_token_summary(self, token_info: JSONDict, out: TextIO) -> None:
        total = token_info.get("total_token_usage", {})
        if not total:
            return
        parts = []
        parts.append(f"in={format_number(total.get('input_tokens'))}")
        cached = total.get("cached_input_tokens")
        if cached:
            parts.append(f"(cached={format_number(cached)})")
        parts.append(f"out={format_number(total.get('output_tokens'))}")
        reasoning = total.get("reasoning_output_tokens")
        if reasoning:
            parts.append(f"reasoning={format_number(reasoning)}")
        parts.append(f"total={format_number(total.get('total_tokens'))}")
        line = self.c.style(f"\n  Tokens: {' '.join(parts)}", Color.DIM, Color.GRAY)
        out.write(f"{line}\n")

    def render_summary(self, session: Session, out: TextIO) -> None:
        line = "=" * self.width
        out.write(self.c.style(line, Color.BOLD, Color.CYAN) + "\n")
        out.write(self.c.style(" SESSION SUMMARY", Color.BOLD, Color.CYAN) + "\n")
        out.write(self.c.style(line, Color.BOLD, Color.CYAN) + "\n")

        def kv(key: str, val: str) -> str:
            label = self.c.style(f"{key:<14}:", Color.GRAY)
            return f"{label} {val}\n"

        # Duration
        if session.turns:
            first_ts = session.turns[0].start_ts
            last_ts = session.turns[-1].end_ts
            duration = format_duration_sec(
                _iso_to_epoch_ms(first_ts),
                _iso_to_epoch_ms(last_ts),
            )
            t1 = _iso_short_time(first_ts)
            t2 = _iso_short_time(last_ts)
            out.write(kv("Duration", f"{duration} ({t1} - {t2})"))
        out.write(kv("Turns", str(len(session.turns))))

        # Total tokens
        if session.total_token_usage:
            total = session.total_token_usage.get("total_token_usage", {})
            if total:
                parts = []
                parts.append(f"in={format_number(total.get('input_tokens'))}")
                cached = total.get("cached_input_tokens")
                if cached:
                    parts.append(f"(cached={format_number(cached)})")
                parts.append(f"out={format_number(total.get('output_tokens'))}")
                reasoning = total.get("reasoning_output_tokens")
                if reasoning:
                    parts.append(f"reasoning={format_number(reasoning)}")
                parts.append(f"total={format_number(total.get('total_tokens'))}")
                out.write(kv("Total tokens", " ".join(parts)))

        # Tool calls
        tool_calls: List[str] = []
        for turn in session.turns:
            for ev in turn.events:
                if ev.subkind == "custom_tool_call":
                    name = ev.data.get("name", "tool")
                    tool_calls.append(name)
        if tool_calls:
            from collections import Counter
            counts = Counter(tool_calls)
            desc = ", ".join(f"{name} x{cnt}" if cnt > 1 else name for name, cnt in counts.items())
            out.write(kv("Tool calls", f"{len(tool_calls)} ({desc})"))
        else:
            out.write(kv("Tool calls", "0"))

        out.write(self.c.style(line, Color.BOLD, Color.CYAN) + "\n")


# ---------------------------------------------------------------------------
# Layer 8: File Output Writers (reuse from codex_log_parser.py)
# ---------------------------------------------------------------------------

def write_jsonl(events: Iterable[NormalizedEvent], path: Union[str, Path]) -> None:
    from pathlib import Path as P
    path = P(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(asdict(ev), ensure_ascii=False) + "\n")


def write_json(events: List[NormalizedEvent], path: Union[str, Path]) -> None:
    from pathlib import Path as P
    path = P(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump([asdict(e) for e in events], f, ensure_ascii=False, indent=2)


def write_csv(events: Iterable[NormalizedEvent], path: Union[str, Path]) -> None:
    from pathlib import Path as P
    path = P(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["ts", "ts_ms", "kind", "subkind", "role", "turn_id", "message"]

    def clean(v: Any) -> Any:
        if v is None:
            return None
        if isinstance(v, str):
            v = v.replace("\r\n", "\n").replace("\r", "\n")
            return v.replace("\n", "\\n")
        return v

    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        for ev in events:
            row = {k: clean(getattr(ev, k)) for k in fields}
            w.writerow(row)


def split_outputs(events: List[NormalizedEvent], out_dir: Union[str, Path]) -> None:
    from pathlib import Path as P
    out_dir = P(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    write_jsonl(events, out_dir / "events.jsonl")
    write_csv(events, out_dir / "events.csv")

    messages = [
        e for e in events
        if e.subkind in ("agent_message", "user_message")
        or (e.kind == "response_item" and e.subkind == "message")
    ]
    tool_outputs = [
        e for e in events if (e.kind == "response_item" and e.subkind == "custom_tool_call_output")
    ]
    tasks = [e for e in events if e.subkind in ("task_started", "task_complete")]
    turn_ctx = [e for e in events if e.kind == "turn_context"]

    write_jsonl(messages, out_dir / "messages.jsonl")
    write_jsonl(tool_outputs, out_dir / "tool_outputs.jsonl")
    write_jsonl(tasks, out_dir / "tasks.jsonl")
    write_jsonl(turn_ctx, out_dir / "turn_context.jsonl")


# ---------------------------------------------------------------------------
# Layer 9: Visualizer JSON Export
# ---------------------------------------------------------------------------

_VIZ_TYPE_MAP: Dict[tuple, Optional[str]] = {
    ("event_msg", "task_started"): "command",
    ("event_msg", "task_complete"): "backup",
    ("event_msg", "token_count"): "search",
    ("event_msg", "user_message"): "command",
    ("event_msg", "agent_message"): "analyze",
    ("event_msg", "agent_reasoning"): "note",
    ("response_item", "message"): None,  # depends on role
    ("response_item", "reasoning"): "note",
    ("response_item", "custom_tool_call"): "edit",
    ("response_item", "custom_tool_call_output"): "read",
    ("turn_context", None): "backup",
    ("session_meta", None): "backup",
}


def _build_viz_label(ev: NormalizedEvent, turn: Turn) -> str:
    # Collapse all whitespace (including newlines) to single spaces for a clean single-line label
    msg = re.sub(r'\s+', ' ', (ev.message or "").strip())
    if ev.subkind == "task_started":
        return f"Turn {turn.turn_number} started"
    if ev.subkind == "task_complete":
        return f"Turn {turn.turn_number} complete"
    if ev.role == "user" and msg:
        return f"User: {msg[:70]}"
    if ev.role == "assistant" and msg:
        return f"Agent: {msg[:70]}"
    if ev.role == "developer" and msg:
        return f"System: {msg[:70]}"
    if ev.subkind == "reasoning" and msg:
        return f"Reasoning: {msg[:70]}"
    if ev.subkind == "custom_tool_call":
        name = ev.data.get("name", "tool")
        tool_input = ev.data.get("input", "")
        if isinstance(tool_input, str) and tool_input.strip():
            try:
                parsed = json.loads(tool_input)
                if isinstance(parsed, dict):
                    cmd = parsed.get("command", [])
                    if isinstance(cmd, list) and cmd:
                        cmd_str = " ".join(str(c) for c in cmd)
                        return f"{name}: {cmd_str[:60]}"
                    for key in ("patch", "content", "input"):
                        v = parsed.get(key, "")
                        if v and isinstance(v, str):
                            first = v.strip().split("\n")[0]
                            return f"{name}: {first[:60]}"
            except (json.JSONDecodeError, TypeError):
                pass
            first = tool_input.strip().split("\n")[0]
            return f"{name}: {first[:60]}"
        return f"Tool: {name}"
    if ev.subkind == "custom_tool_call_output" and msg:
        return f"Result: {msg[:70]}"
    if ev.subkind == "token_count":
        return "Token count update"
    if ev.kind == "turn_context":
        model = ev.data.get("model", "?")
        return f"Context: model={model}"
    if ev.kind == "session_meta":
        return "Session init"
    if msg:
        return msg[:80]
    return f"{ev.kind}/{ev.subkind or '?'}"


def _build_session_description(session: Session) -> str:
    parts = []
    for t in session.turns:
        if t.user_message:
            parts.append(t.user_message.strip()[:60])
    if parts:
        return f"{len(session.turns)} turns: {' | '.join(parts)}"
    return f"{len(session.turns)} turns"


def _map_event_to_viz(
    ev: NormalizedEvent, idx: int, turn: Turn, verbose: bool,
) -> Optional[JSONDict]:
    # Skip event_msg duplicates (same rules as PrettyRenderer)
    if ev.kind == "event_msg" and ev.subkind in _EVENT_MSG_DUPLICATES:
        return None
    # Skip developer unless verbose
    if ev.role == "developer" and not verbose:
        return None
    # Skip internal plumbing
    if ev.kind == "turn_context":
        return None
    if ev.subkind == "token_count":
        return None
    if ev.subkind == "task_started":
        return None

    viz_type = _VIZ_TYPE_MAP.get((ev.kind, ev.subkind))
    if viz_type is None and ev.kind == "response_item" and ev.subkind == "message":
        viz_type = "command" if ev.role == "user" else "analyze"
    if viz_type is None:
        viz_type = "note"

    label = _build_viz_label(ev, turn)
    if ev.subkind == "custom_tool_call":
        detail = str(ev.data.get("input", ev.message or ""))[:500]
    else:
        detail = (ev.message or "")[:500]

    thinking: Optional[str] = None
    if ev.subkind == "reasoning" and ev.message:
        thinking = ev.message[:200]

    return {
        "event_index": idx,
        "event_type": viz_type,
        "label": label[:80],
        "detail": detail,
        "source": ev.role or ev.kind,
        "thinking": thinking,
        "timestamp": ev.ts or "",
    }


def export_viz_json(
    session: Session,
    out_dir: Union[str, Any],
    verbose: bool = False,
) -> str:
    """Export Session to visualizer-compatible JSON. Returns output file path."""
    from pathlib import Path as P
    out_dir_p = P(out_dir)
    out_dir_p.mkdir(parents=True, exist_ok=True)

    # Build meta
    meta: JSONDict = {
        "label": f"Codex session {_format_ts_display(session.session_ts)}",
        "generated_at": (
            session.turns[-1].end_ts if session.turns else session.session_ts
        ),
        "agent": {
            "type": "codex",
            "model": session.turns[0].model if session.turns else "unknown",
            "version": session.cli_version,
            "provider": session.model_provider,
        },
        "source": session.originator,
        "description": _build_session_description(session),
    }

    # Build events
    viz_events: List[JSONDict] = []
    idx = 0
    for turn in session.turns:
        for ev in turn.events:
            viz_ev = _map_event_to_viz(ev, idx, turn, verbose)
            if viz_ev is not None:
                viz_events.append(viz_ev)
                idx += 1

    # Generate filename: session_YYYYMMDD_HHMMSS_description.json
    ts_part = "unknown"
    if session.session_ts:
        try:
            raw = session.session_ts
            if raw.endswith("Z"):
                raw = raw[:-1] + "+00:00"
            dt = datetime.fromisoformat(raw)
            ts_part = dt.strftime("%Y%m%d_%H%M%S")
        except Exception:
            pass

    desc_part = ""
    if session.turns and session.turns[0].user_message:
        desc_part = session.turns[0].user_message[:40]
        desc_part = re.sub(r"[^a-z0-9]+", "_", desc_part.lower()).strip("_")

    filename = f"session_{ts_part}_{desc_part}.json" if desc_part else f"session_{ts_part}.json"
    out_path = out_dir_p / filename

    data: JSONDict = {"meta": meta, "events": viz_events}
    out_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return str(out_path)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_ts_display(ts: Optional[str]) -> str:
    if not ts:
        return "?"
    try:
        if ts.endswith("Z"):
            dt = datetime.fromisoformat(ts[:-1]).replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(ts)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except Exception:
        return ts


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(
        description="Codex agent log parser and prettifier.",
        epilog=(
            "Examples:\n"
            "  %(prog)s session.jsonl                      # pretty terminal output\n"
            "  %(prog)s session.jsonl --summary             # session statistics only\n"
            "  %(prog)s session.jsonl --turn 2              # show only turn 2\n"
            "  %(prog)s session.jsonl --jsonl out.jsonl     # normalized JSONL output\n"
            "  %(prog)s session.jsonl --out-dir ./parsed/   # split outputs\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("input", help="Path to JSONL log file, or '-' for stdin")

    fmt = p.add_argument_group("output format")
    fmt.add_argument("--jsonl", metavar="PATH", help="Write normalized events to JSONL file")
    fmt.add_argument("--json", metavar="PATH", help="Write normalized events to JSON array file")
    fmt.add_argument("--csv", metavar="PATH", help="Write normalized events to CSV file")
    fmt.add_argument("--out-dir", metavar="DIR", help="Write split outputs to directory")
    fmt.add_argument("--viz-json", metavar="DIR", help="Export session as visualizer JSON to directory")
    fmt.add_argument("--summary", action="store_true", help="Show session statistics only")

    flt = p.add_argument_group("filtering")
    flt.add_argument("--turn", metavar="N[,N...]", help="Show only specific turns (1-based, comma-separated)")
    flt.add_argument("--role", metavar="ROLE[,...]", help="Filter by role (user, assistant, developer)")
    flt.add_argument("--kind", metavar="KIND[,...]", help="Filter by event kind")
    flt.add_argument("--subkind", metavar="SUB[,...]", help="Filter by event subkind")

    disp = p.add_argument_group("display")
    disp.add_argument("--no-color", action="store_true", help="Disable ANSI colors")
    disp.add_argument("--width", type=int, default=0, help="Terminal width (default: auto-detect)")
    disp.add_argument("--verbose", "-v", action="store_true", help="Show developer messages and system prompts")
    disp.add_argument("--show-tokens", action="store_true", help="Show all token count events inline")
    disp.add_argument("--show-patches", action="store_true", help="Show full tool call patch content")

    args = p.parse_args(argv)

    # Detect terminal width
    width = args.width
    if width <= 0:
        try:
            width = shutil.get_terminal_size(fallback=(100, 24)).columns
        except Exception:
            width = 100

    # Detect color support
    use_color = not args.no_color
    if use_color and not sys.stdout.isatty():
        use_color = False
    if os.environ.get("NO_COLOR"):
        use_color = False

    # Open input
    if args.input == "-":
        stream: TextIO = sys.stdin
    else:
        stream = open(args.input, "r", encoding="utf-8", errors="replace")

    try:
        raw_records = list(iter_json_objects(stream))
    finally:
        if stream is not sys.stdin:
            stream.close()

    if _detect_v1_format(raw_records):
        events = normalize_v1_stream(raw_records)
    else:
        events = list(normalize_stream(raw_records))

    # File outputs (backward-compatible)
    has_file_output = bool(args.jsonl or args.json or args.csv or args.out_dir)
    if args.jsonl:
        write_jsonl(events, args.jsonl)
    if args.json:
        write_json(events, args.json)
    if args.csv:
        write_csv(events, args.csv)
    if args.out_dir:
        split_outputs(events, args.out_dir)

    # Visualizer JSON export
    session = build_session(events)
    if args.viz_json:
        out_path = export_viz_json(session, args.viz_json, verbose=args.verbose)
        sys.stderr.write(f"Exported: {out_path}\n")
        has_file_output = True

    # If only file outputs requested and no pretty/summary, exit
    if has_file_output and not args.summary:
        return 0

    # Pretty output (default) or summary
    color = Color(enabled=use_color)
    renderer = PrettyRenderer(
        color=color,
        width=width,
        verbose=args.verbose,
        show_tokens=args.show_tokens,
        show_patches=args.show_patches,
    )
    filters = parse_filter_spec(args)
    renderer.render_session(session, sys.stdout, filters=filters, summary_only=args.summary)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
