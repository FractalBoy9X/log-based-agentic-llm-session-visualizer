#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# Forward all arguments to run_prettify.sh with --download-only
"$PROJECT_DIR/run_prettify.sh" --download-only "$@"
