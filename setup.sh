#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -m pip --version >/dev/null 2>&1; then
  .venv/bin/python -m ensurepip --upgrade
fi
.venv/bin/python -m pip install -r requirements.txt
if ! .venv/bin/python -c 'from app import Study; Study()' 2>/dev/null; then
  printf 'Preparing the study and six model pipelines. This can take several minutes.\n'
  .venv/bin/python study.py
fi
printf 'Ready. Start the application with ./run.sh\n'

