"""Log Manager - scanning and importing JSONL sessions into visualization JSON."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple

from .config import get_codex_sessions_dir

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PRETTIFY_SCRIPT = PROJECT_ROOT / "codex_prettify.py"
SESSIONS_JSON_DIR = Path(__file__).resolve().parent / "data" / "sessions_json"


def _get_python() -> str:
    """Get the Python executable to use for codex_prettify.py."""
    explicit_python = os.getenv("CODEX_PYTHON", "").strip()
    if explicit_python:
        return explicit_python

    venv_dir = Path(os.getenv("CODEX_VENV_DIR", str(PROJECT_ROOT / ".venv"))).expanduser()
    candidates = (
        venv_dir / "bin" / "python3",
        venv_dir / "bin" / "python",
        venv_dir / "Scripts" / "python.exe",
    )
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return "python3"


def scan_codex_sessions() -> List[Dict[str, Any]]:
    """Scan CODEX_SESSIONS_DIR and return available JSONL logs.

    Supports both flat (*.jsonl directly in the directory) and nested
    structures (YYYY/MM/DD/*.jsonl).

    Returns:
        List of dicts: filename, rel_path, path, modified, modified_date, size,
        size_kb, month_key.
    """
    sessions_dir = get_codex_sessions_dir()
    if not sessions_dir.exists():
        return []

    sessions = []
    # Recursive scan supports YYYY/MM/DD/*.jsonl structures.
    for path in sorted(
        sessions_dir.rglob("*.jsonl"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    ):
        if path.name.startswith("._"):
            continue
        stat = path.stat()
        mod_dt = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
        rel_path = str(path.relative_to(sessions_dir))
        sessions.append({
            "filename": path.name,
            "rel_path": rel_path,
            "path": str(path),
            "modified": stat.st_mtime,
            "modified_date": mod_dt.strftime("%Y-%m-%d %H:%M"),
            "size": stat.st_size,
            "size_kb": round(stat.st_size / 1024, 1),
            "month_key": mod_dt.strftime("%Y-%m"),
        })

    return sessions


def get_already_imported() -> Set[str]:
    """Return rel_path values that were already imported."""
    SESSIONS_JSON_DIR.mkdir(parents=True, exist_ok=True)
    mapping_file = SESSIONS_JSON_DIR / ".import_mapping.json"
    if mapping_file.exists():
        try:
            data = json.loads(mapping_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return set(data.keys())
        except (json.JSONDecodeError, OSError):
            pass
    return set()


def _update_import_mapping(rel_path: str, json_filename: str) -> None:
    """Add an import mapping entry (key = rel_path)."""
    SESSIONS_JSON_DIR.mkdir(parents=True, exist_ok=True)
    mapping_file = SESSIONS_JSON_DIR / ".import_mapping.json"
    mapping: Dict[str, str] = {}
    if mapping_file.exists():
        try:
            mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            mapping = {}
    mapping[rel_path] = json_filename
    mapping_file.write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def group_by_month(
    sessions: List[Dict[str, Any]],
) -> "OrderedDict[str, List[Dict[str, Any]]]":
    """Group sessions by month key ('YYYY-MM')."""
    grouped: OrderedDict[str, List[Dict[str, Any]]] = OrderedDict()
    for s in sessions:
        key = s["month_key"]
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(s)
    return grouped


def import_session(rel_path: str) -> Tuple[bool, str]:
    """Import a single JSONL file into sessions_json/.

    Args:
        rel_path: Path relative to CODEX_SESSIONS_DIR.

    Returns:
        (success, message)
    """
    sessions_dir = get_codex_sessions_dir()
    source = sessions_dir / rel_path
    if not sessions_dir.exists():
        return False, f"Sessions directory not found: {sessions_dir}"
    if not source.exists():
        return False, f"File not found: {rel_path}"

    if not PRETTIFY_SCRIPT.exists():
        return False, f"Prettify script not found: {PRETTIFY_SCRIPT}"

    SESSIONS_JSON_DIR.mkdir(parents=True, exist_ok=True)

    python = _get_python()
    try:
        result = subprocess.run(
            [python, str(PRETTIFY_SCRIPT), str(source), "--viz-json", str(SESSIONS_JSON_DIR)],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return False, f"Timeout converting {rel_path}"
    except OSError as exc:
        return False, f"Error running prettify: {exc}"

    if result.returncode != 0:
        error_msg = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "Unknown error"
        return False, f"Conversion failed for {Path(rel_path).name}: {error_msg}"

    # Extract output filename from stderr (format: "Exported: /path/to/file.json")
    json_filename = ""
    for line in result.stderr.splitlines():
        if line.startswith("Exported: "):
            json_filename = Path(line.split("Exported: ", 1)[1].strip()).name
            break

    _update_import_mapping(rel_path, json_filename)
    return True, f"Imported: {Path(rel_path).name} → {json_filename}"


def import_sessions(rel_paths: List[str]) -> Tuple[int, List[str]]:
    """Import selected JSONL files.

    Args:
        rel_paths: Lista ścieżek względnych od CODEX_SESSIONS_DIR

    Returns:
        (count_success, messages)
    """
    success_count = 0
    messages = []

    for rel_path in rel_paths:
        ok, msg = import_session(rel_path)
        if ok:
            success_count += 1
        messages.append(msg)

    return success_count, messages


def import_all_sessions() -> Tuple[int, List[str]]:
    """Import all available sessions from CODEX_SESSIONS_DIR."""
    sessions = scan_codex_sessions()
    already_imported = get_already_imported()

    to_import = [s["rel_path"] for s in sessions if s["rel_path"] not in already_imported]

    if not to_import:
        return 0, ["All sessions already imported."]

    return import_sessions(to_import)


def delete_imported_session(json_filename: str) -> Tuple[bool, str]:
    """Delete an imported JSON file from sessions_json/.

    This removes only sessions_json output and never touches source JSONL files.

    Args:
        json_filename: JSON filename, e.g. "session_20260212_233538_xxx.json".

    Returns:
        (success, message)
    """
    target = SESSIONS_JSON_DIR / json_filename

    # Safety check: ensure path stays inside sessions_json/.
    try:
        target.resolve().relative_to(SESSIONS_JSON_DIR.resolve())
    except ValueError:
        return False, f"Security error: path traversal detected for {json_filename}"

    if not target.exists():
        return False, f"File not found: {json_filename}"

    try:
        target.unlink()
    except OSError as exc:
        return False, f"Failed to delete {json_filename}: {exc}"

    # Remove mapping entry (if present).
    mapping_file = SESSIONS_JSON_DIR / ".import_mapping.json"
    if mapping_file.exists():
        try:
            mapping: Dict[str, str] = json.loads(mapping_file.read_text(encoding="utf-8"))
            # Usuń klucze, które wskazują na ten plik
            mapping = {k: v for k, v in mapping.items() if v != json_filename}
            mapping_file.write_text(
                json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except (json.JSONDecodeError, OSError):
            pass

    return True, f"Deleted: {json_filename}"
