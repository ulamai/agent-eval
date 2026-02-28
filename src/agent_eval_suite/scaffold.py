from __future__ import annotations

import json
from pathlib import Path
from typing import Any


STARTER_SUITE = {
    "dataset_id": "starter-suite",
    "metadata": {"source": "agent-eval init"},
    "cases": [
        {
            "case_id": "starter-1",
            "input": "What is the weather in San Francisco?",
            "expected_output": {"answer": "72F", "status": "ok"},
            "tool_contracts": {
                "search_weather": {
                    "required_args": ["city"],
                    "forbidden_args": ["api_key"],
                }
            },
            "policy": {
                "required_tools": ["search_weather"],
                "forbidden_tools": ["delete_database"],
            },
            "regex_patterns": ["72F", "ok"],
            "json_schema": {
                "type": "object",
                "required": ["answer", "status"],
                "properties": {
                    "answer": {"type": "string"},
                    "status": {"type": "string", "enum": ["ok"]},
                },
            },
            "trace": [
                {
                    "idx": 0,
                    "ts": "2026-02-28T10:00:00+00:00",
                    "actor": "user",
                    "type": "message",
                    "input": "weather in sf",
                },
                {
                    "idx": 1,
                    "ts": "2026-02-28T10:00:01+00:00",
                    "actor": "agent",
                    "type": "tool_call",
                    "tool": "search_weather",
                    "input": {"city": "San Francisco"},
                },
                {
                    "idx": 2,
                    "ts": "2026-02-28T10:00:02+00:00",
                    "actor": "tool",
                    "type": "tool_result",
                    "tool": "search_weather",
                    "output": {"temp_f": 72},
                },
                {
                    "idx": 3,
                    "ts": "2026-02-28T10:00:03+00:00",
                    "actor": "assistant",
                    "type": "message",
                    "output": "{\"answer\":\"72F\",\"status\":\"ok\"}",
                },
            ],
        }
    ],
}

JUDGE_CONFIG = {
    "tool_contract": {},
    "policy": {},
    "trajectory_step": {},
    "regex": {},
    "json_schema": {},
    "repair_path": {},
    "lean": {
        "command": ["lean-checker", "--json-stdin"],
        "timeout_seconds": 30,
    },
}

GATE_CONFIG = {
    "min_pass_rate": 0.95,
    "max_hard_fail_rate": 0.05,
    "max_pass_rate_drop": 0.02,
    "max_hard_fail_increase": 0.02,
}

GITHUB_ACTIONS_TEMPLATE = """name: Agent Eval Gate

on:
  pull_request:
  workflow_dispatch:

jobs:
  eval-gate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install
        run: |
          python -m pip install --upgrade pip
          python -m pip install -e .
      - name: Run baseline eval
        run: |
          agent-eval run \\
            --suite suites/starter_suite.json \\
            --judge-config config/judges.json \\
            --out runs/baseline \\
            --run-id baseline-main
      - name: Run candidate eval
        run: |
          agent-eval run \\
            --suite suites/starter_suite.json \\
            --judge-config config/judges.json \\
            --out runs/candidate \\
            --run-id candidate-pr
      - name: Compare baseline vs candidate
        run: |
          agent-eval compare \\
            --baseline runs/baseline \\
            --candidate runs/candidate \\
            --out runs/candidate/compare/baseline_delta.json
      - name: Gate decision
        run: |
          agent-eval gate \\
            --compare runs/candidate/compare/baseline_delta.json \\
            --min-pass-rate 0.95 \\
            --max-hard-fail-rate 0.05 \\
            --max-pass-rate-drop 0.02 \\
            --max-hard-fail-increase 0.02
"""


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def scaffold_init(out_dir: str | Path, force: bool = False) -> tuple[list[str], list[str]]:
    base = Path(out_dir)
    files: dict[Path, Any] = {
        base / "suites" / "starter_suite.json": STARTER_SUITE,
        base / "config" / "judges.json": JUDGE_CONFIG,
        base / "config" / "gate.json": GATE_CONFIG,
        base / "ci" / "github-actions-agent-eval.yml": GITHUB_ACTIONS_TEMPLATE,
    }
    created: list[str] = []
    skipped: list[str] = []

    for path, payload in files.items():
        if path.exists() and not force:
            skipped.append(str(path))
            continue

        if isinstance(payload, str):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(payload, encoding="utf-8")
        else:
            _write_json(path, payload)
        created.append(str(path))

    return created, skipped
