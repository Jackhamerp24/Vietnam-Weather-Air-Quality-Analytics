#!/bin/sh
# Phase 11 operator wrapper TEMPLATE. It delegates to a Python launcher that
# parses an external mode-600 file containing only literal DATABASE_URL and
# OPENAQ_API_KEY assignments. It rejects shell syntax and unknown/duplicate
# keys, then execs with an explicit environment allowlist. This file is not
# installed or executed by the repository.
set -eu

CHECKOUT="${VN_AIR_CHECKOUT:?set VN_AIR_CHECKOUT to the repository checkout}"
PYTHON="${VN_AIR_PYTHON:-$CHECKOUT/.venv/bin/python}"
OUTPUT_ROOT="${VN_AIR_OUTPUT_ROOT:-$CHECKOUT/.local/automation/cycles}"
ENV_FILE="${VN_AIR_ENV_FILE:?set VN_AIR_ENV_FILE}"

if [ "$(cd "$CHECKOUT" 2>/dev/null && pwd -P)" != "$CHECKOUT" ]; then
    echo "automation wrapper: checkout path must resolve exactly" >&2
    exit 3
fi
exec "$PYTHON" -I -B "$CHECKOUT/scripts/run_automation.py" \
    --env-file "$ENV_FILE" --output-root "$OUTPUT_ROOT"
