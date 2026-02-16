#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"

if [ -f "$ENV_FILE" ]; then
    set -a
    # shellcheck disable=SC1090
    . "$ENV_FILE"
    set +a
fi

SESSIONS_DIR="${CODEX_SESSIONS_DIR:-$HOME/.codex/sessions}"
VENV_DIR="${CODEX_VENV_DIR:-$SCRIPT_DIR/.venv}"
PRETTIFY="$SCRIPT_DIR/codex_prettify.py"
VIZ_DIR="$SCRIPT_DIR/agentic-llm-session-visualizer-main"
VIZ_DATA="$VIZ_DIR/visualization/data/sessions_json"
REQUIREMENTS="$SCRIPT_DIR/requirements.txt"
RAW_JSONL_DIR="$SCRIPT_DIR/json_downloader/raw_jsonl"
DJANGO_HOST="${DJANGO_HOST:-127.0.0.1}"
DJANGO_PORT="${DJANGO_PORT:-8000}"

cleanup_appledouble() {
    local target="${1:-}"
    [ -n "$target" ] || return 0
    [ -d "$target" ] || return 0
    # On some external filesystems macOS creates AppleDouble sidecar files (._*),
    # which pip may interpret as broken distributions (e.g. "-pip").
    find "$target" -type f -name '._*' -delete 2>/dev/null || true
}

if [ ! -d "$SESSIONS_DIR" ]; then
    echo "Sessions directory not found: $SESSIONS_DIR"
    echo "Set CODEX_SESSIONS_DIR in your environment or in $ENV_FILE."
    exit 1
fi

# Ensure venv exists
if [ ! -d "$VENV_DIR" ]; then
    echo "Creating venv..."
    python3 -m venv "$VENV_DIR"
fi

cleanup_appledouble "$VENV_DIR"

if [ -x "$VENV_DIR/bin/python3" ]; then
    PYTHON="$VENV_DIR/bin/python3"
elif [ -x "$VENV_DIR/bin/python" ]; then
    PYTHON="$VENV_DIR/bin/python"
elif [ -x "$VENV_DIR/Scripts/python.exe" ]; then
    PYTHON="$VENV_DIR/Scripts/python.exe"
else
    echo "Python executable not found in venv: $VENV_DIR"
    exit 1
fi

# Install deps if Django missing
if ! "$PYTHON" -c "import django" 2>/dev/null; then
    if [ -f "$REQUIREMENTS" ]; then
        echo "Installing dependencies..."
        "$PYTHON" -m pip install -q -r "$REQUIREMENTS"
        cleanup_appledouble "$VENV_DIR"
    fi
fi

# Parse flags
SERVE=false
DOWNLOAD_ONLY=false
IMPORT_ALL=false
SPECIFIC_FILE=""
ARGS=()
for arg in "$@"; do
    if [ "$arg" = "--serve" ]; then
        SERVE=true
    elif [ "$arg" = "--download-only" ]; then
        DOWNLOAD_ONLY=true
    elif [ "$arg" = "--all" ]; then
        IMPORT_ALL=true
    elif [[ "$arg" == --file=* ]]; then
        SPECIFIC_FILE="${arg#--file=}"
    else
        ARGS+=("$arg")
    fi
done

mkdir -p "$VIZ_DATA"
mkdir -p "$RAW_JSONL_DIR"

if [ "$IMPORT_ALL" = true ]; then
    # Import ALL .jsonl files (rekurencyjnie - obsługuje strukturę YYYY/MM/DD/)
    echo "Importing all sessions from $SESSIONS_DIR..."
    IMPORTED=0
    while IFS= read -r -d '' JSONL; do
        [ -f "$JSONL" ] || continue
        BASENAME=$(basename "$JSONL")
        DEST="$RAW_JSONL_DIR/$BASENAME"
        if [ ! -f "$DEST" ] || [ "$JSONL" -nt "$DEST" ]; then
            cp "$JSONL" "$DEST"
        fi
        "$PYTHON" "$PRETTIFY" "$DEST" --viz-json "$VIZ_DATA" 2>&1
        IMPORTED=$((IMPORTED + 1))
    done < <(find "$SESSIONS_DIR" -name '*.jsonl' -type f -print0)
    echo "Imported $IMPORTED sessions."

elif [ -n "$SPECIFIC_FILE" ]; then
    # Import a specific file (SPECIFIC_FILE może być relatywną ścieżką: YYYY/MM/DD/file.jsonl)
    SOURCE="$SESSIONS_DIR/$SPECIFIC_FILE"
    if [ ! -f "$SOURCE" ]; then
        echo "File not found: $SOURCE"
        exit 1
    fi
    BASENAME=$(basename "$SPECIFIC_FILE")
    DEST="$RAW_JSONL_DIR/$BASENAME"
    cp "$SOURCE" "$DEST"
    "$PYTHON" "$PRETTIFY" "$DEST" --viz-json "$VIZ_DATA"

else
    # Default: import newest only
    NEWEST=$(find "$SESSIONS_DIR" -name '*.jsonl' -type f -print0 \
        | xargs -0 ls -t 2>/dev/null \
        | head -1)

    if [ -z "$NEWEST" ]; then
        echo "No .jsonl files found in $SESSIONS_DIR"
        exit 1
    fi

    BASENAME=$(basename "$NEWEST")
    DEST="$RAW_JSONL_DIR/$BASENAME"

    if [ ! -f "$DEST" ] || [ "$NEWEST" -nt "$DEST" ]; then
        cp "$NEWEST" "$DEST"
        echo "Copied: $BASENAME"
    else
        echo "Already up to date: $BASENAME"
    fi

    if [ "$DOWNLOAD_ONLY" = true ]; then
        "$PYTHON" "$PRETTIFY" "$DEST" --viz-json "$VIZ_DATA"
    else
        "$PYTHON" "$PRETTIFY" "$DEST" --viz-json "$VIZ_DATA" "${ARGS[@]+"${ARGS[@]}"}"
    fi
fi

# Optionally start Django server
if [ "$SERVE" = true ]; then
    echo ""
    echo "Starting visualizer at http://$DJANGO_HOST:$DJANGO_PORT/"
    cd "$VIZ_DIR"
    exec "$PYTHON" manage.py runserver "$DJANGO_HOST:$DJANGO_PORT"
fi
