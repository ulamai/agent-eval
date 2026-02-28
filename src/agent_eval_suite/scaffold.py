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
    "cost_budget": {
        "max_total_tokens": 5000,
        "max_cost_usd": 0.25,
    },
    "latency_slo": {
        "max_p95_latency_ms": 1500,
        "max_total_latency_ms": 4000,
    },
    "retry_storm": {
        "max_retries_per_call": 2,
        "max_total_retries": 6,
    },
    "loop_guard": {
        "max_steps": 40,
        "max_attempts": 3,
    },
    "tool_abuse": {
        "max_tool_calls_total": 20,
        "forbidden_tool_patterns": ["delete", "drop", "admin"],
    },
    "prompt_injection": {},
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
    "max_regressed_cases": 0,
    "max_new_hard_fail_cases": 0,
}

GITLAB_CI_TEMPLATE = """stages:
  - eval

agent_eval_gate:
  stage: eval
  image: python:3.11
  script:
    - pip install --upgrade pip
    - pip install -e .
    - bash ci/run-agent-eval.sh
"""

BUILDKITE_TEMPLATE = """steps:
  - label: ":mag: Agent Eval Gate"
    commands:
      - "python3 -m pip install --upgrade pip"
      - "python3 -m pip install -e ."
      - "bash ci/run-agent-eval.sh"
"""

CIRCLECI_TEMPLATE = """version: 2.1
jobs:
  agent_eval_gate:
    docker:
      - image: cimg/python:3.11
    steps:
      - checkout
      - run: python -m pip install --upgrade pip
      - run: python -m pip install -e .
      - run: bash ci/run-agent-eval.sh
workflows:
  agent_eval:
    jobs:
      - agent_eval_gate
"""

JENKINSFILE_TEMPLATE = """pipeline {
  agent any
  stages {
    stage('Agent Eval Gate') {
      steps {
        sh 'python3 -m pip install --upgrade pip'
        sh 'python3 -m pip install -e .'
        sh 'bash ci/run-agent-eval.sh'
      }
    }
  }
}
"""

CI_RUN_SCRIPT = """#!/usr/bin/env bash
set -euo pipefail

agent-eval run \\
  --suite suites/starter_suite.json \\
  --judge-config config/judges.json \\
  --out runs/baseline \\
  --run-id baseline-main

agent-eval run \\
  --suite suites/starter_suite.json \\
  --judge-config config/judges.json \\
  --out runs/candidate \\
  --run-id candidate-pr

agent-eval compare \\
  --baseline runs/baseline \\
  --candidate runs/candidate \\
  --out runs/candidate/compare/baseline_delta.json

agent-eval gate \\
  --compare runs/candidate/compare/baseline_delta.json \\
  --min-pass-rate 0.95 \\
  --max-hard-fail-rate 0.05 \\
  --max-pass-rate-drop 0.02 \\
  --max-hard-fail-increase 0.02 \\
  --max-regressed-cases 0 \\
  --max-new-hard-fail-cases 0
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
        base / "ci" / "gitlab-agent-eval.yml": GITLAB_CI_TEMPLATE,
        base / "ci" / "buildkite-agent-eval.yml": BUILDKITE_TEMPLATE,
        base / "ci" / "circleci-agent-eval.yml": CIRCLECI_TEMPLATE,
        base / "ci" / "Jenkinsfile.agent-eval": JENKINSFILE_TEMPLATE,
        base / "ci" / "run-agent-eval.sh": CI_RUN_SCRIPT,
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
            if path.suffix == ".sh":
                path.chmod(0o755)
        else:
            _write_json(path, payload)
        created.append(str(path))

    return created, skipped
