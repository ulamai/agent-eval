from __future__ import annotations

from typing import Any

from agent_eval_suite.judges.base import BaseJudge
from agent_eval_suite.schema import EvalCase, JudgeResult


class ToolContractJudge(BaseJudge):
    judge_id = "tool_contract"

    def evaluate(self, case: EvalCase) -> JudgeResult:
        calls_checked = 0
        violations: list[dict[str, Any]] = []

        for event in case.trace:
            if event.type != "tool_call" or not event.tool:
                continue
            contract = case.tool_contracts.get(event.tool)
            if not contract:
                continue

            calls_checked += 1
            args = event.input if isinstance(event.input, dict) else {}
            missing = [key for key in contract.required_args if key not in args]
            forbidden = [key for key in contract.forbidden_args if key in args]

            if missing or forbidden:
                violations.append(
                    {
                        "event_idx": event.idx,
                        "tool": event.tool,
                        "missing_required_args": missing,
                        "forbidden_args_present": forbidden,
                    }
                )

        if calls_checked == 0 and not case.tool_contracts:
            return JudgeResult(
                judge_id=self.judge_id,
                case_id=case.case_id,
                score=1.0,
                passed=True,
                reason="no tool contracts configured",
                hard_fail=True,
                skipped=True,
            )

        if calls_checked == 0 and case.tool_contracts:
            return JudgeResult(
                judge_id=self.judge_id,
                case_id=case.case_id,
                score=0.0,
                passed=False,
                reason="tool contracts configured but no matching tool calls were found",
                hard_fail=True,
                evidence_refs={"contracts": sorted(case.tool_contracts.keys())},
            )

        score = max(0.0, 1.0 - (len(violations) / float(calls_checked)))
        passed = not violations
        reason = "all tool contract checks passed" if passed else "tool contract violations"

        return JudgeResult(
            judge_id=self.judge_id,
            case_id=case.case_id,
            score=score,
            passed=passed,
            reason=reason,
            hard_fail=True,
            evidence_refs={"violations": violations, "calls_checked": calls_checked},
        )
