#!/usr/bin/env python3
"""
jsonl_deminify.py

Deminifikator plikow JSONL z logow agentowych (Codex, itp.).

Wczytuje plik .jsonl (1 JSON na linie) i wypisuje kazdy rekord
w formacie czytelnym dla czlowieka: z wcieciami, separatorami
miedzy rekordami i opcjonalnym kolorowaniem.

Dane NIE sa modyfikowane -- to dokladnie ten sam JSON, tylko
pretty-printed (indent=2).

Uzycie:
  python3 jsonl_deminify.py session.jsonl
  python3 jsonl_deminify.py session.jsonl -o pretty_output.json
  python3 jsonl_deminify.py session.jsonl --no-color
  python3 jsonl_deminify.py session.jsonl --compact-keys
  cat session.jsonl | python3 jsonl_deminify.py -
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, TextIO

# ---------------------------------------------------------------------------
# ANSI colors (auto-disabled on non-TTY or NO_COLOR)
# ---------------------------------------------------------------------------

_RESET = "\033[0m"
_BOLD = "\033[1m"
_DIM = "\033[2m"

_KEY_COLOR = "\033[36m"       # cyan  - JSON keys
_STR_COLOR = "\033[32m"       # green - string values
_NUM_COLOR = "\033[33m"       # yellow - numbers
_BOOL_COLOR = "\033[35m"      # magenta - true/false/null
_BRACE_COLOR = "\033[90m"     # gray - braces/brackets
_SEP_COLOR = "\033[90m"       # gray - record separator line
_RECNUM_COLOR = "\033[1;34m"  # bold blue - record number
_TYPE_COLOR = "\033[1;33m"    # bold yellow - type/subtype tag
_TS_COLOR = "\033[37m"        # white - timestamp


def _color_enabled(force: Optional[bool] = None) -> bool:
    if force is not None:
        return force
    if os.environ.get("NO_COLOR"):
        return False
    return sys.stdout.isatty()


# ---------------------------------------------------------------------------
# Colorized JSON renderer
# ---------------------------------------------------------------------------

def _colorize_json(obj: Any, indent: int = 2, _depth: int = 0) -> str:
    """Render a JSON value with ANSI color codes, indented."""
    pad = " " * (indent * _depth)
    pad_inner = " " * (indent * (_depth + 1))

    if obj is None:
        return f"{_BOOL_COLOR}null{_RESET}"
    if isinstance(obj, bool):
        return f"{_BOOL_COLOR}{json.dumps(obj)}{_RESET}"
    if isinstance(obj, (int, float)):
        return f"{_NUM_COLOR}{json.dumps(obj)}{_RESET}"
    if isinstance(obj, str):
        return f"{_STR_COLOR}{json.dumps(obj, ensure_ascii=False)}{_RESET}"

    if isinstance(obj, list):
        if not obj:
            return f"{_BRACE_COLOR}[]{_RESET}"
        lines = [f"{_BRACE_COLOR}[{_RESET}"]
        for i, item in enumerate(obj):
            comma = "," if i < len(obj) - 1 else ""
            val = _colorize_json(item, indent, _depth + 1)
            lines.append(f"{pad_inner}{val}{comma}")
        lines.append(f"{pad}{_BRACE_COLOR}]{_RESET}")
        return "\n".join(lines)

    if isinstance(obj, dict):
        if not obj:
            return f"{_BRACE_COLOR}{{}}{_RESET}"
        lines = [f"{_BRACE_COLOR}{{{_RESET}"]
        items = list(obj.items())
        for i, (k, v) in enumerate(items):
            comma = "," if i < len(items) - 1 else ""
            key_str = f"{_KEY_COLOR}{json.dumps(k, ensure_ascii=False)}{_RESET}"
            val_str = _colorize_json(v, indent, _depth + 1)
            lines.append(f"{pad_inner}{key_str}: {val_str}{comma}")
        lines.append(f"{pad}{_BRACE_COLOR}}}{_RESET}")
        return "\n".join(lines)

    return str(obj)


# ---------------------------------------------------------------------------
# Record header (label above each JSON record)
# ---------------------------------------------------------------------------

def _record_header(idx: int, obj: Dict[str, Any], use_color: bool, term_width: int) -> str:
    """Build a separator + label line for a record."""
    rec_type = obj.get("type", "?")
    timestamp = obj.get("timestamp", "")

    # Subtype extraction
    payload = obj.get("payload", {})
    subtype = ""
    if isinstance(payload, dict):
        subtype = payload.get("type", "")
        # Extra context for some subtypes
        if subtype == "message":
            role = payload.get("role", "")
            if role:
                subtype = f"message/{role}"
        elif subtype == "function_call":
            name = payload.get("name", "")
            if name:
                subtype = f"function_call:{name}"
        elif subtype == "custom_tool_call":
            name = payload.get("name", "")
            if name:
                subtype = f"custom_tool_call:{name}"

    # Phase info (commentary vs final_answer)
    phase = ""
    if isinstance(payload, dict):
        p = payload.get("phase", "")
        if p:
            phase = f" [{p}]"

    if use_color:
        sep_line = f"{_SEP_COLOR}{'=' * term_width}{_RESET}"
        label = (
            f"{_RECNUM_COLOR}[Record {idx}]{_RESET}  "
            f"{_TYPE_COLOR}{rec_type}{_RESET}"
        )
        if subtype:
            label += f" {_DIM}>{_RESET} {_TYPE_COLOR}{subtype}{_RESET}"
        if phase:
            label += f" {_DIM}{phase}{_RESET}"
        if timestamp:
            label += f"  {_TS_COLOR}{timestamp}{_RESET}"
    else:
        sep_line = "=" * term_width
        label = f"[Record {idx}]  {rec_type}"
        if subtype:
            label += f" > {subtype}"
        if phase:
            label += phase
        if timestamp:
            label += f"  {timestamp}"

    return f"{sep_line}\n{label}\n"


# ---------------------------------------------------------------------------
# Compact-keys mode: shorten known long fields
# ---------------------------------------------------------------------------

_COMPACT_KEYS = {
    "encrypted_content": "<encrypted {len} chars>",
    "base_instructions": "<base_instructions {len} chars>",
}


def _compact_deep(obj: Any) -> Any:
    """Replace known bulky fields with placeholders (preserves structure)."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in _COMPACT_KEYS and isinstance(v, (str, dict)):
                if isinstance(v, str):
                    out[k] = _COMPACT_KEYS[k].format(len=len(v))
                elif isinstance(v, dict):
                    # e.g. base_instructions: {"text": "...long..."}
                    txt = v.get("text", "")
                    if isinstance(txt, str) and len(txt) > 200:
                        out[k] = {"text": f"<{len(txt)} chars>"}
                    else:
                        out[k] = _compact_deep(v)
                else:
                    out[k] = v
            else:
                out[k] = _compact_deep(v)
        return out
    if isinstance(obj, list):
        return [_compact_deep(item) for item in obj]
    return obj


# ---------------------------------------------------------------------------
# Streaming JSONL reader
# ---------------------------------------------------------------------------

def iter_records(stream: TextIO):
    """Yield (line_number, parsed_dict) for each JSON line."""
    for lineno, raw in enumerate(stream, start=1):
        raw = raw.strip()
        if not raw:
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError as e:
            print(f"[WARN] Line {lineno}: invalid JSON ({e})", file=sys.stderr)
            continue
        if isinstance(obj, dict):
            yield lineno, obj


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deminifikator JSONL - wypisuje kazdy rekord w czytelnej formie."
    )
    parser.add_argument(
        "input",
        help="Plik .jsonl do deminifikacji (lub '-' dla stdin)",
    )
    parser.add_argument(
        "-o", "--output",
        help="Zapisz wynik do pliku zamiast stdout.",
        default=None,
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="Wymus brak kolorow ANSI.",
    )
    parser.add_argument(
        "--color",
        action="store_true",
        help="Wymus kolorowanie nawet jezeli stdout nie jest TTY.",
    )
    parser.add_argument(
        "--compact-keys",
        action="store_true",
        help="Skroc znane dlugasne pola (encrypted_content, base_instructions).",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="Wielkosc wciecia (domyslnie 2).",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=0,
        help="Szerokosc separatora (0 = auto z terminala, domyslnie 100).",
    )
    parser.add_argument(
        "--records",
        help="Zakres rekordow do wyswietlenia, np. '1-10' lub '5' lub '3,7,12'.",
        default=None,
    )

    args = parser.parse_args()

    # Resolve color mode
    if args.no_color:
        use_color = False
    elif args.color:
        use_color = True
    else:
        use_color = _color_enabled()

    # If writing to file, disable color by default
    out_file: Optional[TextIO] = None
    if args.output:
        out_file = open(args.output, "w", encoding="utf-8")
        if not args.color:
            use_color = False

    out = out_file or sys.stdout

    # Terminal width
    term_width = args.width
    if term_width <= 0:
        try:
            term_width = os.get_terminal_size().columns
        except OSError:
            term_width = 100

    # Parse --records filter
    record_filter: Optional[set] = None
    if args.records:
        record_filter = set()
        for part in args.records.split(","):
            part = part.strip()
            if "-" in part:
                lo, hi = part.split("-", 1)
                for n in range(int(lo), int(hi) + 1):
                    record_filter.add(n)
            else:
                record_filter.add(int(part))

    # Open input
    if args.input == "-":
        stream = sys.stdin
    else:
        stream = open(args.input, "r", encoding="utf-8")

    rec_idx = 0
    try:
        for _lineno, obj in iter_records(stream):
            rec_idx += 1

            if record_filter and rec_idx not in record_filter:
                continue

            # Compact mode
            display_obj = _compact_deep(obj) if args.compact_keys else obj

            # Header
            header = _record_header(rec_idx, obj, use_color, term_width)
            out.write(header)

            # Pretty JSON body
            if use_color:
                body = _colorize_json(display_obj, indent=args.indent)
            else:
                body = json.dumps(display_obj, indent=args.indent, ensure_ascii=False)

            out.write(body)
            out.write("\n\n")

    finally:
        if stream is not sys.stdin:
            stream.close()

    # Summary
    total_label = f"Total: {rec_idx} records"
    if record_filter:
        shown = len(record_filter & set(range(1, rec_idx + 1)))
        total_label += f" ({shown} shown)"

    if use_color:
        out.write(f"{_SEP_COLOR}{'=' * term_width}{_RESET}\n")
        out.write(f"{_DIM}{total_label}{_RESET}\n")
    else:
        out.write(f"{'=' * term_width}\n")
        out.write(f"{total_label}\n")

    if out_file:
        out_file.close()
        print(f"Saved to: {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
