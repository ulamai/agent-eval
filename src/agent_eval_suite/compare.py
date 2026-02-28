from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _normalize_summary(raw: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(raw)
    if "total_cases" not in normalized and "total" in normalized:
        normalized["total_cases"] = normalized.get("total", 0)
    if "passed_cases" not in normalized and "passed" in normalized:
        normalized["passed_cases"] = normalized.get("passed", 0)
    if "failed_cases" not in normalized and "failed" in normalized:
        normalized["failed_cases"] = normalized.get("failed", 0)
    if "hard_fail_cases" not in normalized:
        if "hard_fail_count" in normalized:
            normalized["hard_fail_cases"] = normalized.get("hard_fail_count", 0)
        elif "hard_failed" in normalized:
            normalized["hard_fail_cases"] = normalized.get("hard_failed", 0)
    if "judge_pass_rates" not in normalized and "judge_rates" in normalized:
        normalized["judge_pass_rates"] = normalized.get("judge_rates", {})
    return normalized


def load_summary(path: str | Path) -> dict[str, Any]:
    raw = Path(path)
    if raw.is_file():
        return _normalize_summary(_load_json(raw))
    summary_path = raw / "run" / "summary.json"
    if summary_path.exists():
        return _normalize_summary(_load_json(summary_path))
    raise FileNotFoundError(f"could not find summary.json in {raw}")


def _metric_delta(name: str, baseline: float, candidate: float) -> dict[str, Any]:
    return {
        "name": name,
        "baseline": baseline,
        "candidate": candidate,
        "delta": candidate - baseline,
    }


def _index_case_results(path: str | Path) -> dict[str, dict[str, Any]]:
    raw = Path(path)
    payload: dict[str, Any] | None = None
    if raw.is_file():
        payload = _load_json(raw)
    else:
        report_path = raw / "report.json"
        if report_path.exists():
            payload = _load_json(report_path)

    cases: list[dict[str, Any]] = []
    if payload and isinstance(payload.get("cases"), list):
        cases = [case for case in payload["cases"] if isinstance(case, dict)]
    elif raw.is_dir():
        verdict_paths = sorted((raw / "cases").glob("*/verdicts.json"))
        for verdict_path in verdict_paths:
            verdict = _load_json(verdict_path)
            if isinstance(verdict, dict):
                cases.append(verdict)

    indexed: dict[str, dict[str, Any]] = {}
    for case in cases:
        case_id = case.get("case_id")
        if isinstance(case_id, str) and case_id:
            indexed[case_id] = case
    return indexed


def _index_judge_scores(case_result: dict[str, Any]) -> dict[str, float]:
    scores: dict[str, float] = {}
    judge_results = case_result.get("judge_results", [])
    if not isinstance(judge_results, list):
        return scores
    for item in judge_results:
        if not isinstance(item, dict):
            continue
        judge_id = item.get("judge_id")
        score = item.get("score")
        if isinstance(judge_id, str):
            try:
                scores[judge_id] = float(score)
            except (TypeError, ValueError):
                continue
    return scores


def _case_regressions(
    baseline_cases: dict[str, dict[str, Any]], candidate_cases: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case_id in sorted(set(baseline_cases) | set(candidate_cases)):
        base = baseline_cases.get(case_id, {})
        cand = candidate_cases.get(case_id, {})

        base_passed = base.get("passed")
        cand_passed = cand.get("passed")
        base_hard = base.get("hard_failed")
        cand_hard = cand.get("hard_failed")

        base_scores = _index_judge_scores(base)
        cand_scores = _index_judge_scores(cand)
        score_deltas = {
            judge_id: _metric_delta(
                judge_id,
                float(base_scores.get(judge_id, 0.0)),
                float(cand_scores.get(judge_id, 0.0)),
            )
            for judge_id in sorted(set(base_scores) | set(cand_scores))
        }

        pass_changed = base_passed != cand_passed
        hard_fail_changed = base_hard != cand_hard
        regressed = (base_passed is True and cand_passed is False) or (
            base_hard is False and cand_hard is True
        )
        improved = (base_passed is False and cand_passed is True) or (
            base_hard is True and cand_hard is False
        )

        if pass_changed or hard_fail_changed or regressed or improved:
            rows.append(
                {
                    "case_id": case_id,
                    "baseline_passed": base_passed,
                    "candidate_passed": cand_passed,
                    "baseline_hard_failed": base_hard,
                    "candidate_hard_failed": cand_hard,
                    "regressed": regressed,
                    "improved": improved,
                    "judge_score_deltas": score_deltas,
                }
            )
    return rows


def compare_runs(baseline_path: str | Path, candidate_path: str | Path) -> dict[str, Any]:
    baseline = load_summary(baseline_path)
    candidate = load_summary(candidate_path)
    baseline_cases = _index_case_results(baseline_path)
    candidate_cases = _index_case_results(candidate_path)
    case_regressions = _case_regressions(baseline_cases, candidate_cases)

    metrics = {
        "pass_rate": _metric_delta(
            "pass_rate",
            float(baseline.get("pass_rate", 0.0)),
            float(candidate.get("pass_rate", 0.0)),
        ),
        "hard_fail_rate": _metric_delta(
            "hard_fail_rate",
            float(baseline.get("hard_fail_rate", 0.0)),
            float(candidate.get("hard_fail_rate", 0.0)),
        ),
    }

    baseline_judges = baseline.get("judge_pass_rates", {})
    candidate_judges = candidate.get("judge_pass_rates", {})
    judge_metrics: dict[str, dict[str, Any]] = {}
    for judge_id in sorted(set(baseline_judges) | set(candidate_judges)):
        judge_metrics[judge_id] = _metric_delta(
            judge_id,
            float(baseline_judges.get(judge_id, 0.0)),
            float(candidate_judges.get(judge_id, 0.0)),
        )

    regressions: list[str] = []
    if metrics["pass_rate"]["delta"] < 0:
        regressions.append("pass_rate decreased")
    if metrics["hard_fail_rate"]["delta"] > 0:
        regressions.append("hard_fail_rate increased")

    for judge_id, metric in judge_metrics.items():
        if metric["delta"] < 0:
            regressions.append(f"{judge_id} pass rate decreased")

    regressed_cases = [case["case_id"] for case in case_regressions if case["regressed"]]
    for case_id in regressed_cases:
        regressions.append(f"case regressed: {case_id}")

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "baseline_run_id": baseline.get("run_id"),
        "candidate_run_id": candidate.get("run_id"),
        "dataset_id": candidate.get("dataset_id") or baseline.get("dataset_id"),
        "metrics": metrics,
        "judge_metrics": judge_metrics,
        "case_regressions": case_regressions,
        "regressions": regressions,
    }


def write_compare_report(
    report: dict[str, Any], out_path: str | Path, ensure_parent: bool = True
) -> Path:
    target = Path(out_path)
    if ensure_parent:
        target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return target
