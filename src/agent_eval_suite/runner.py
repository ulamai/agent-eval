from __future__ import annotations

from collections import defaultdict

from agent_eval_suite.judges.base import BaseJudge
from agent_eval_suite.replay import validate_trace
from agent_eval_suite.schema import (
    CaseResult,
    EvalCase,
    EvalSuite,
    JudgeResult,
    RunConfig,
    RunSummary,
)


class EvalRunner:
    def __init__(self, judges: list[BaseJudge]):
        self.judges = judges

    def evaluate_case(self, case: EvalCase) -> CaseResult:
        replay_issues = validate_trace(case.trace)
        replay_result = JudgeResult(
            judge_id="replay_contract",
            case_id=case.case_id,
            score=1.0 if not replay_issues else 0.0,
            passed=not replay_issues,
            reason="replay checks passed"
            if not replay_issues
            else "replay contract violations",
            hard_fail=True,
            evidence_refs={"issues": replay_issues},
        )

        results = [replay_result]
        for judge in self.judges:
            results.append(judge.evaluate(case))

        passed = all(result.passed for result in results if not result.skipped)
        hard_failed = any((not result.passed) and result.hard_fail for result in results)
        return CaseResult(
            case_id=case.case_id,
            passed=passed,
            hard_failed=hard_failed,
            judge_results=results,
            replay_issues=replay_issues,
        )

    def run(self, suite: EvalSuite, run_config: RunConfig) -> tuple[list[CaseResult], RunSummary]:
        case_results: list[CaseResult] = []
        judge_total = defaultdict(int)
        judge_passed = defaultdict(int)

        for case in suite.cases:
            case_result = self.evaluate_case(case)
            case_results.append(case_result)

            for result in case_result.judge_results:
                if result.skipped:
                    continue
                judge_total[result.judge_id] += 1
                if result.passed:
                    judge_passed[result.judge_id] += 1

        total_cases = len(case_results)
        passed_cases = sum(1 for result in case_results if result.passed)
        hard_fail_cases = sum(1 for result in case_results if result.hard_failed)
        failed_cases = total_cases - passed_cases
        pass_rate = passed_cases / total_cases if total_cases else 0.0
        hard_fail_rate = hard_fail_cases / total_cases if total_cases else 0.0
        judge_pass_rates = {
            judge_id: judge_passed[judge_id] / total
            for judge_id, total in judge_total.items()
            if total
        }

        summary = RunSummary(
            run_id=run_config.run_id,
            dataset_id=suite.dataset_id,
            total_cases=total_cases,
            passed_cases=passed_cases,
            failed_cases=failed_cases,
            hard_fail_cases=hard_fail_cases,
            pass_rate=pass_rate,
            hard_fail_rate=hard_fail_rate,
            judge_pass_rates=judge_pass_rates,
            schema_version=run_config.schema_version,
        )
        return case_results, summary
