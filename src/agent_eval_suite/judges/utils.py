from __future__ import annotations

from typing import Any

from agent_eval_suite.schema import EvalCase


def extract_final_output(case: EvalCase) -> Any:
    for event in reversed(case.trace):
        if event.output is not None and event.actor in {"assistant", "agent"}:
            return event.output
    for event in reversed(case.trace):
        if event.output is not None:
            return event.output
    return case.expected_output
