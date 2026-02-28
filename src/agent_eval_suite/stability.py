from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from agent_eval_suite.loop_runner import ProposeExecuteRepairRunner
from agent_eval_suite.plugins import DEFAULT_JUDGES, instantiate_judge
from agent_eval_suite.runner import EvalRunner
from agent_eval_suite.schema import EvalSuite, RunConfig, utc_now_iso


@dataclass(slots=True)
class StabilityOptions:
    runs: int = 5
    execution_mode: str = "trace_score"
    propose_command: str | None = None
    repair_command: str | None = None
    max_repairs: int = 2
    command_timeout_seconds: int = 30
    strict_side_effects: bool = False
    quarantine_min_pass_rate: float = 0.98


def _wilson_interval(successes: int, trials: int, z: float = 1.96) -> tuple[float, float]:
    if trials <= 0:
        return 0.0, 0.0
    p = successes / float(trials)
    denom = 1.0 + (z**2 / trials)
    center = (p + (z**2 / (2 * trials))) / denom
    margin = (
        z
        * math.sqrt((p * (1 - p) / trials) + ((z**2) / (4 * (trials**2))))
        / denom
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def _build_run_config(
    suite: EvalSuite,
    judge_names: list[str],
    judge_configs: dict[str, Any],
    execution_mode: str,
    run_index: int,
) -> RunConfig:
    return RunConfig(
        run_id=f"stability-{run_index + 1}",
        dataset_id=suite.dataset_id,
        agent_version="stability-check",
        model="unknown",
        started_at=utc_now_iso(),
        seed=run_index,
        judges=judge_names,
        judge_configs=judge_configs,
        execution_mode=execution_mode,
    )


def run_stability_check(
    suite_path: str,
    *,
    judge_names: list[str] | None = None,
    judge_configs: dict[str, Any] | None = None,
    options: StabilityOptions | None = None,
) -> dict[str, Any]:
    opts = options or StabilityOptions()
    if opts.runs < 2:
        raise ValueError("stability check requires at least 2 runs")

    suite = EvalSuite.from_path(suite_path)
    resolved_judges = judge_names or list(DEFAULT_JUDGES)
    configs = judge_configs or {}
    judges = [instantiate_judge(name, config=configs.get(name, {})) for name in resolved_judges]

    eval_runner = EvalRunner(judges)
    run_rows: list[dict[str, Any]] = []
    case_pass_history: dict[str, list[bool]] = {case.case_id: [] for case in suite.cases}
    case_hard_history: dict[str, list[bool]] = {case.case_id: [] for case in suite.cases}

    for run_index in range(opts.runs):
        run_suite = suite
        execution_mode = "trace_score"
        if opts.execution_mode == "propose_execute_repair":
            if not opts.propose_command:
                raise ValueError(
                    "propose_command is required for execution_mode=propose_execute_repair"
                )
            loop_runner = ProposeExecuteRepairRunner(
                eval_runner=eval_runner,
                propose_command=opts.propose_command,
                repair_command=opts.repair_command,
                max_repairs=opts.max_repairs,
                timeout_seconds=opts.command_timeout_seconds,
                strict_side_effects=opts.strict_side_effects,
            )
            run_suite = loop_runner.run(suite)
            execution_mode = "propose_execute_repair"

        run_config = _build_run_config(
            run_suite,
            judge_names=resolved_judges,
            judge_configs=configs,
            execution_mode=execution_mode,
            run_index=run_index,
        )
        case_results, summary = eval_runner.run(run_suite, run_config)
        run_rows.append(
            {
                "run_index": run_index,
                "run_id": run_config.run_id,
                "pass_rate": summary.pass_rate,
                "hard_fail_rate": summary.hard_fail_rate,
                "passed_cases": summary.passed_cases,
                "failed_cases": summary.failed_cases,
                "hard_fail_cases": summary.hard_fail_cases,
            }
        )

        for result in case_results:
            case_pass_history.setdefault(result.case_id, []).append(bool(result.passed))
            case_hard_history.setdefault(result.case_id, []).append(bool(result.hard_failed))

    case_rows: list[dict[str, Any]] = []
    flaky_case_ids: list[str] = []
    consistently_failing_case_ids: list[str] = []
    quarantine_recommended_case_ids: list[str] = []

    for case_id in sorted(case_pass_history):
        history = case_pass_history[case_id]
        hard_history = case_hard_history.get(case_id, [])
        pass_count = sum(1 for passed in history if passed)
        hard_fail_count = sum(1 for hard in hard_history if hard)
        total = len(history)
        pass_rate = pass_count / float(total) if total else 0.0
        ci_low, ci_high = _wilson_interval(pass_count, total)
        flaky = pass_count not in (0, total)
        consistently_failing = pass_count == 0
        quarantine = flaky and pass_rate < opts.quarantine_min_pass_rate

        if flaky:
            flaky_case_ids.append(case_id)
        if consistently_failing:
            consistently_failing_case_ids.append(case_id)
        if quarantine:
            quarantine_recommended_case_ids.append(case_id)

        case_rows.append(
            {
                "case_id": case_id,
                "runs": total,
                "pass_count": pass_count,
                "hard_fail_count": hard_fail_count,
                "pass_rate": pass_rate,
                "confidence_95": {"low": ci_low, "high": ci_high},
                "flaky": flaky,
                "consistently_failing": consistently_failing,
                "quarantine_recommended": quarantine,
            }
        )

    overall_pass_rates = [row["pass_rate"] for row in run_rows]
    avg_pass_rate = sum(overall_pass_rates) / float(len(overall_pass_rates))
    variance = sum((rate - avg_pass_rate) ** 2 for rate in overall_pass_rates) / float(
        len(overall_pass_rates)
    )

    return {
        "dataset_id": suite.dataset_id,
        "runs": opts.runs,
        "execution_mode": opts.execution_mode,
        "judge_names": resolved_judges,
        "run_results": run_rows,
        "case_stability": case_rows,
        "flaky_case_ids": flaky_case_ids,
        "consistently_failing_case_ids": consistently_failing_case_ids,
        "quarantine_recommended_case_ids": quarantine_recommended_case_ids,
        "summary": {
            "avg_pass_rate": avg_pass_rate,
            "pass_rate_stddev": math.sqrt(max(0.0, variance)),
            "flaky_cases": len(flaky_case_ids),
            "consistently_failing_cases": len(consistently_failing_case_ids),
            "quarantine_recommended_cases": len(quarantine_recommended_case_ids),
        },
    }
