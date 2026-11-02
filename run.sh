#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -x .venv/bin/python ]]; then
  printf 'Run ./setup.sh first.\n' >&2
  exit 1
fi
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
printf 'Building Energy Lab: http://127.0.0.1:%s\nStop with Ctrl+C.\n' "${PORT:-8765}"
exec .venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port "${PORT:-8765}" --workers 1

