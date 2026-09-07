#!/usr/bin/env bash
# Run every model and condition of the main sweep in sequence.
# Usage: scripts/run_all.sh [extra args passed to run_models.py, e.g. --limit 5]
set -euo pipefail

cd "$(dirname "$0")/.."
PY=.venv/bin/python

$PY scripts/run_models.py --model blip       --condition caption      "$@"
$PY scripts/run_models.py --model qwen2vl-2b --condition naive        "$@"
$PY scripts/run_models.py --model qwen2vl-2b --condition wcag         "$@"
$PY scripts/run_models.py --model qwen2vl-2b --condition wcag_context "$@"
