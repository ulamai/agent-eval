#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

python3 -m pip install --upgrade pip build twine
rm -rf build dist ./*.egg-info
python3 -m build
python3 -m twine check dist/*

echo "Built release artifacts in dist/:"
ls -1 dist/
