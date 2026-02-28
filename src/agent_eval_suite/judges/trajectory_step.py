from __future__ import annotations

from agent_eval_suite.judges.base import BaseJudge
from agent_eval_suite.schema import EvalCase, JudgeResult, TraceEvent


def _attempt_key(event: TraceEvent) -> int:
    if isinstance(event.attempt, int):
        return event.attempt
    return 0


class TrajectoryStepJudge(BaseJudge):
    judge_id = "trajectory_step"

    def evaluate(self, case: EvalCase) -> JudgeResult:
        if not case.trace:
            return JudgeResult(
                judge_id=self.judge_id,
                case_id=case.case_id,
                score=0.0,
                passed=False,
                reason="empty trace",
                hard_fail=True,
                evidence_refs={"violations": ["trace is empty"]},
            )

        violations: list[dict[str, object]] = []
        pending_calls: dict[int, str | None] = {}
        checks = 0

        for event in case.trace:
            attempt = _attempt_key(event)
            if event.type == "tool_call":
                pending_calls[attempt] = event.tool
                checks += 1
                continue

            if event.type == "tool_result":
                checks += 1
                if attempt not in pending_calls:
                    violations.append(
                        {
                            "event_idx": event.idx,
                            "attempt": attempt,
                            "error": "tool_result without prior tool_call",
                            "tool": event.tool,
                        }
                    )
                    continue
                expected_tool = pending_calls.pop(attempt)
                if expected_tool is not None and event.tool not in (None, expected_tool):
                    violations.append(
                        {
                            "event_idx": event.idx,
                            "attempt": attempt,
                            "error": "tool_result tool mismatch",
                            "expected_tool": expected_tool,
                            "actual_tool": event.tool,
                        }
                    )

        for attempt, tool_name in sorted(pending_calls.items()):
            violations.append(
                {
                    "attempt": attempt,
                    "error": "unresolved tool_call without tool_result",
                    "tool": tool_name,
                }
            )

        denominator = max(1, checks)
        score = max(0.0, 1.0 - (len(violations) / float(denominator)))
        passed = not violations
        return JudgeResult(
            judge_id=self.judge_id,
            case_id=case.case_id,
            score=score,
            passed=passed,
            reason="trajectory checks passed" if passed else "trajectory step violations",
            hard_fail=True,
            evidence_refs={"violations": violations, "checks": checks},
        )
