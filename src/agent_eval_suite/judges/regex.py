from __future__ import annotations

import re

from agent_eval_suite.judges.base import BaseJudge
from agent_eval_suite.judges.utils import extract_final_output
from agent_eval_suite.schema import EvalCase, JudgeResult


class RegexJudge(BaseJudge):
    judge_id = "regex"

    def evaluate(self, case: EvalCase) -> JudgeResult:
        if not case.regex_patterns:
            return JudgeResult(
                judge_id=self.judge_id,
                case_id=case.case_id,
                score=1.0,
                passed=True,
                reason="no regex patterns configured",
                hard_fail=True,
                skipped=True,
            )

        output = extract_final_output(case)
        if output is None:
            return JudgeResult(
                judge_id=self.judge_id,
                case_id=case.case_id,
                score=0.0,
                passed=False,
                reason="final output missing for regex evaluation",
                hard_fail=True,
                evidence_refs={"patterns": case.regex_patterns},
            )

        text = output if isinstance(output, str) else str(output)
        missing_patterns = [
            pattern for pattern in case.regex_patterns if re.search(pattern, text) is None
        ]
        matched = len(case.regex_patterns) - len(missing_patterns)
        score = matched / float(len(case.regex_patterns))
        passed = not missing_patterns

        return JudgeResult(
            judge_id=self.judge_id,
            case_id=case.case_id,
            score=score,
            passed=passed,
            reason="regex checks passed" if passed else "regex pattern mismatch",
            hard_fail=True,
            evidence_refs={
                "patterns": case.regex_patterns,
                "missing_patterns": missing_patterns,
            },
        )
