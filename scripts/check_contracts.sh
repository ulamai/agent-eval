#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHONPATH=src python3 -m unittest discover -s tests -p 'test_*.py'
PYTHONPATH=src python3 -m agent_eval_suite adapter-conformance \
  --fixtures-dir tests/fixtures/adapters \
  --min-fixtures-per-provider 2
PYTHONPATH=src python3 -m agent_eval_suite contracts-check \
  --schema-fixtures-dir tests/fixtures/schema_backcompat \
  --adapter-fixtures-dir tests/fixtures/adapters \
  --min-fixtures-per-provider 2
