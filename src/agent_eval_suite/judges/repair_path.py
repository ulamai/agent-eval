from __future__ import annotations

from agent_eval_suite.judges.base import BaseJudge
from agent_eval_suite.schema import EvalCase, JudgeResult


class RepairPathJudge(BaseJudge):
    judge_id = "repair_path"

    def evaluate(self, case: EvalCase) -> JudgeResult:
        attempts = case.metadata.get("attempt_history")
        if not isinstance(attempts, list) or not attempts:
            return JudgeResult(
                judge_id=self.judge_id,
                case_id=case.case_id,
                score=1.0,
                passed=True,
                reason="no repair attempts available",
                hard_fail=False,
                skipped=True,
            )

        seen_attempts: list[int] = []
        violations: list[str] = []
        for row in attempts:
            if not isinstance(row, dict):
                violations.append("attempt record must be an object")
                continue
            attempt = row.get("attempt")
            if not isinstance(attempt, int):
                violations.append("attempt id must be integer")
                continue
            seen_attempts.append(attempt)

        if seen_attempts != sorted(seen_attempts):
            violations.append("attempt ids are not monotonic")
        if len(set(seen_attempts)) != len(seen_attempts):
            violations.append("duplicate attempt ids detected")

        attempts_used = len(seen_attempts)
        efficiency = 1.0 / float(max(1, attempts_used))
        passed = not violations
        score = efficiency if passed else 0.0

        return JudgeResult(
            judge_id=self.judge_id,
            case_id=case.case_id,
            score=score,
            passed=passed,
            reason="repair path checks passed" if passed else "repair path violations",
            hard_fail=False,
            evidence_refs={
                "attempts_used": attempts_used,
                "attempt_ids": seen_attempts,
                "violations": violations,
            },
        )
