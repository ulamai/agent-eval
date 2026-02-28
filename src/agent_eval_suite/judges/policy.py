from __future__ import annotations

from agent_eval_suite.judges.base import BaseJudge
from agent_eval_suite.schema import EvalCase, JudgeResult


class PolicyJudge(BaseJudge):
    judge_id = "policy"

    def evaluate(self, case: EvalCase) -> JudgeResult:
        if not case.policy.forbidden_tools and not case.policy.required_tools:
            return JudgeResult(
                judge_id=self.judge_id,
                case_id=case.case_id,
                score=1.0,
                passed=True,
                reason="no policy constraints configured",
                hard_fail=True,
                skipped=True,
            )

        tool_calls = [event.tool for event in case.trace if event.type == "tool_call"]
        used_tools = {tool for tool in tool_calls if tool}

        forbidden_violations = sorted(
            tool for tool in case.policy.forbidden_tools if tool in used_tools
        )
        missing_required = sorted(
            tool for tool in case.policy.required_tools if tool not in used_tools
        )
        violations_count = len(forbidden_violations) + len(missing_required)
        total_rules = max(
            1, len(case.policy.forbidden_tools) + len(case.policy.required_tools)
        )
        score = max(0.0, 1.0 - (violations_count / float(total_rules)))
        passed = violations_count == 0

        reason = "policy checks passed"
        if forbidden_violations or missing_required:
            reason = "policy violations detected"

        return JudgeResult(
            judge_id=self.judge_id,
            case_id=case.case_id,
            score=score,
            passed=passed,
            reason=reason,
            hard_fail=True,
            evidence_refs={
                "forbidden_tools_used": forbidden_violations,
                "missing_required_tools": missing_required,
                "used_tools": sorted(used_tools),
            },
        )
