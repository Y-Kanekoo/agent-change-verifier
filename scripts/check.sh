#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
export UV_CACHE_DIR="$PWD/.uv-cache"
export UV_PYTHON_INSTALL_DIR="$PWD/.uv-python"
export TMPDIR="$PWD/.tmp"
mkdir -p "$TMPDIR"
uv run ruff check .
uv run ruff format --check .
uv run mypy --strict src
uv run pytest
