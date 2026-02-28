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


def _failure_clusters(case_results: dict[str, dict[str, Any]]) -> dict[str, int]:
    clusters: dict[str, int] = {}
    for case in case_results.values():
        judge_results = case.get("judge_results", [])
        if not isinstance(judge_results, list):
            continue
        for row in judge_results:
            if not isinstance(row, dict):
                continue
            if row.get("skipped"):
                continue
            if bool(row.get("passed")):
                continue
            judge_id = str(row.get("judge_id", "unknown"))
            reason = str(row.get("reason", "failed"))
            cluster_key = f"{judge_id}:{reason}"
            clusters[cluster_key] = clusters.get(cluster_key, 0) + 1
    return clusters


def _failure_cluster_deltas(
    baseline_clusters: dict[str, int], candidate_clusters: dict[str, int]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for cluster in sorted(set(baseline_clusters) | set(candidate_clusters)):
        base = int(baseline_clusters.get(cluster, 0))
        cand = int(candidate_clusters.get(cluster, 0))
        rows.append(
            {
                "cluster": cluster,
                "baseline_count": base,
                "candidate_count": cand,
                "delta": cand - base,
            }
        )
    rows.sort(key=lambda row: row["delta"], reverse=True)
    return rows


def _risk_level(pass_rate_delta: float, hard_fail_delta: float, regressed_cases: int) -> str:
    if hard_fail_delta > 0.1 or regressed_cases >= 10:
        return "high"
    if pass_rate_delta < -0.03 or hard_fail_delta > 0.02 or regressed_cases > 0:
        return "medium"
    return "low"


def _suggest_fix_hint(cluster: str) -> str:
    judge_id = cluster.split(":", 1)[0]
    hints = {
        "tool_contract": "Align tool arguments to contract requirements and remove forbidden args.",
        "policy": "Update agent planning to satisfy required tools and avoid forbidden tools.",
        "trajectory_step": "Ensure every tool_call has an ordered matching tool_result.",
        "regex": "Adjust output format or regex expectations to restore deterministic matching.",
        "json_schema": "Return schema-valid JSON with required keys and valid enum values.",
        "replay_contract": "Fix trace indexing/span structure and required event fields for replay.",
        "latency_slo": "Reduce slow tool operations, add caching, and tighten timeout strategy.",
        "cost_budget": "Reduce token/tool usage or adjust model/tool strategy for lower cost.",
        "retry_storm": "Add retry caps, backoff limits, and early failure handling.",
        "loop_guard": "Cap attempts/steps and add completion criteria to stop loops.",
        "tool_abuse": "Constrain tool routing and tighten tool allow-lists/pattern guards.",
        "prompt_injection": "Harden prompt/tool sanitization and refuse instruction overrides.",
    }
    return hints.get(judge_id, "Investigate this cluster and add a deterministic guard for recurrence.")


def _build_triage_clusters(cluster_deltas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in cluster_deltas:
        if int(row.get("delta", 0)) <= 0:
            continue
        cluster = str(row.get("cluster", "unknown:failed"))
        if ":" in cluster:
            judge_id, reason = cluster.split(":", 1)
        else:
            judge_id, reason = cluster, "failed"
        rows.append(
            {
                "cluster": cluster,
                "judge_id": judge_id,
                "reason": reason,
                "baseline_count": int(row.get("baseline_count", 0)),
                "candidate_count": int(row.get("candidate_count", 0)),
                "delta": int(row.get("delta", 0)),
                "suggested_fix": _suggest_fix_hint(cluster),
            }
        )
    rows.sort(key=lambda item: item["delta"], reverse=True)
    return rows[:15]


def _release_impact_summary(
    pass_rate_delta: float,
    hard_fail_delta: float,
    regressed_case_count: int,
    new_hard_fail_count: int,
) -> dict[str, Any]:
    score = 0.0
    score += max(0.0, -pass_rate_delta) * 120.0
    score += max(0.0, hard_fail_delta) * 150.0
    score += float(regressed_case_count) * 2.5
    score += float(new_hard_fail_count) * 5.0
    score = min(100.0, round(score, 2))

    if score >= 60:
        level = "critical"
        recommendation = "block"
    elif score >= 30:
        level = "high"
        recommendation = "block_or_explicit_waiver"
    elif score >= 12:
        level = "medium"
        recommendation = "review_before_release"
    else:
        level = "low"
        recommendation = "proceed"

    return {
        "impact_score": score,
        "impact_level": level,
        "recommendation": recommendation,
    }


def _build_compatibility_report(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    baseline_cases: dict[str, dict[str, Any]],
    candidate_cases: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    baseline_dataset_id = baseline.get("dataset_id")
    candidate_dataset_id = candidate.get("dataset_id")
    dataset_match = (
        True
        if not baseline_dataset_id or not candidate_dataset_id
        else baseline_dataset_id == candidate_dataset_id
    )
    checks.append(
        {
            "name": "dataset_id_match",
            "passed": dataset_match,
            "baseline_dataset_id": baseline_dataset_id,
            "candidate_dataset_id": candidate_dataset_id,
        }
    )

    baseline_total_cases = int(baseline.get("total_cases", 0) or 0)
    candidate_total_cases = int(candidate.get("total_cases", 0) or 0)
    totals_match = (
        True
        if (baseline_total_cases == 0 or candidate_total_cases == 0)
        else baseline_total_cases == candidate_total_cases
    )
    checks.append(
        {
            "name": "total_cases_match",
            "passed": totals_match,
            "baseline_total_cases": baseline_total_cases,
            "candidate_total_cases": candidate_total_cases,
        }
    )

    baseline_case_ids = set(baseline_cases.keys())
    candidate_case_ids = set(candidate_cases.keys())
    case_set_match = True
    missing_in_candidate: list[str] = []
    missing_in_baseline: list[str] = []
    if baseline_case_ids and candidate_case_ids:
        missing_in_candidate = sorted(baseline_case_ids - candidate_case_ids)
        missing_in_baseline = sorted(candidate_case_ids - baseline_case_ids)
        case_set_match = not missing_in_candidate and not missing_in_baseline
    checks.append(
        {
            "name": "case_id_set_match",
            "passed": case_set_match,
            "baseline_case_count": len(baseline_case_ids),
            "candidate_case_count": len(candidate_case_ids),
            "missing_in_candidate": missing_in_candidate,
            "missing_in_baseline": missing_in_baseline,
        }
    )

    passed = all(check["passed"] for check in checks)
    failures = [check for check in checks if not check["passed"]]
    return {"passed": passed, "checks": checks, "failures": failures}


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


def compare_runs(
    baseline_path: str | Path,
    candidate_path: str | Path,
    *,
    enforce_compatibility: bool = False,
) -> dict[str, Any]:
    baseline = load_summary(baseline_path)
    candidate = load_summary(candidate_path)
    baseline_cases = _index_case_results(baseline_path)
    candidate_cases = _index_case_results(candidate_path)
    case_regressions = _case_regressions(baseline_cases, candidate_cases)
    baseline_clusters = _failure_clusters(baseline_cases)
    candidate_clusters = _failure_clusters(candidate_cases)
    cluster_deltas = _failure_cluster_deltas(baseline_clusters, candidate_clusters)

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
    improved_cases = [case["case_id"] for case in case_regressions if case["improved"]]
    for case_id in regressed_cases:
        regressions.append(f"case regressed: {case_id}")

    new_hard_fail_cases = [
        case["case_id"]
        for case in case_regressions
        if (case["baseline_hard_failed"] is False and case["candidate_hard_failed"] is True)
    ]
    resolved_hard_fail_cases = [
        case["case_id"]
        for case in case_regressions
        if (case["baseline_hard_failed"] is True and case["candidate_hard_failed"] is False)
    ]
    top_regressed_judges = [
        {
            "judge_id": judge_id,
            "delta": metric["delta"],
            "baseline": metric["baseline"],
            "candidate": metric["candidate"],
        }
        for judge_id, metric in judge_metrics.items()
        if metric["delta"] < 0
    ]
    top_regressed_judges.sort(key=lambda row: row["delta"])

    pass_rate_delta = float(metrics["pass_rate"]["delta"])
    hard_fail_delta = float(metrics["hard_fail_rate"]["delta"])
    risk_level = _risk_level(pass_rate_delta, hard_fail_delta, len(regressed_cases))
    triage_clusters = _build_triage_clusters(cluster_deltas)
    release_impact = _release_impact_summary(
        pass_rate_delta=pass_rate_delta,
        hard_fail_delta=hard_fail_delta,
        regressed_case_count=len(regressed_cases),
        new_hard_fail_count=len(new_hard_fail_cases),
    )
    compatibility = _build_compatibility_report(
        baseline=baseline,
        candidate=candidate,
        baseline_cases=baseline_cases,
        candidate_cases=candidate_cases,
    )
    if enforce_compatibility and not compatibility["passed"]:
        first = compatibility["failures"][0] if compatibility["failures"] else {}
        reason = str(first.get("name", "compatibility check failed"))
        raise ValueError(f"incompatible baseline/candidate runs: {reason}")

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "baseline_run_id": baseline.get("run_id"),
        "candidate_run_id": candidate.get("run_id"),
        "dataset_id": candidate.get("dataset_id") or baseline.get("dataset_id"),
        "compatibility": compatibility,
        "metrics": metrics,
        "judge_metrics": judge_metrics,
        "case_regressions": case_regressions,
        "regressions": regressions,
        "overview": {
            "total_baseline_cases": len(baseline_cases),
            "total_candidate_cases": len(candidate_cases),
            "regressed_cases": len(regressed_cases),
            "improved_cases": len(improved_cases),
            "new_hard_fail_cases": len(new_hard_fail_cases),
            "resolved_hard_fail_cases": len(resolved_hard_fail_cases),
            "risk_level": risk_level,
        },
        "top_regressed_judges": top_regressed_judges[:10],
        "new_hard_fail_case_ids": new_hard_fail_cases,
        "resolved_hard_fail_case_ids": resolved_hard_fail_cases,
        "failure_clusters": {
            "baseline": baseline_clusters,
            "candidate": candidate_clusters,
            "delta_ranked": cluster_deltas[:25],
        },
        "triage": {
            "top_clusters": triage_clusters,
            "suggested_fixes_count": len(triage_clusters),
        },
        "release_impact": release_impact,
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
