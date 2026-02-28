from __future__ import annotations

import json
from collections import Counter
from typing import Any

from agent_eval_suite.judges.base import BaseJudge
from agent_eval_suite.schema import EvalCase, JudgeResult


def _fingerprint(tool: str | None, args: Any) -> str:
    normalized = args
    if isinstance(args, (dict, list)):
        normalized = json.dumps(args, sort_keys=True)
    return f"{tool or 'unknown'}::{normalized}"


class RetryStormJudge(BaseJudge):
    judge_id = "retry_storm"

    def evaluate(self, case: EvalCase) -> JudgeResult:
        max_retries_per_call = int(self.config.get("max_retries_per_call", 2))
        max_total_retries = int(self.config.get("max_total_retries", 6))

        call_counts: Counter[str] = Counter()
        errors = 0
        for event in case.trace:
            if event.type == "tool_call":
                call_counts[_fingerprint(event.tool, event.input)] += 1
            if event.error:
                errors += 1

        repeated: list[dict[str, Any]] = []
        total_retries = 0
        for key, count in call_counts.items():
            retries = max(0, count - 1)
            if retries:
                total_retries += retries
            if retries > max_retries_per_call:
                repeated.append({"call": key, "retries": retries})

        violations: list[str] = []
        if repeated:
            violations.append("retries exceeded for one or more tool calls")
        if total_retries > max_total_retries:
            violations.append(
                f"total retries {total_retries} exceeds max_total_retries {max_total_retries}"
            )

        if not call_counts:
            return JudgeResult(
                judge_id=self.judge_id,
                case_id=case.case_id,
                score=1.0,
                passed=True,
                reason="no tool calls to evaluate retries",
                hard_fail=False,
                skipped=True,
            )

        checks = 2
        score = max(0.0, 1.0 - (len(violations) / float(checks)))
        return JudgeResult(
            judge_id=self.judge_id,
            case_id=case.case_id,
            score=score,
            passed=not violations,
            reason="retry behavior acceptable" if not violations else "retry storm risk",
            hard_fail=False,
            evidence_refs={
                "errors_seen": errors,
                "distinct_calls": len(call_counts),
                "total_retries": total_retries,
                "high_retry_calls": repeated,
                "violations": violations,
            },
        )
