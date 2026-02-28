from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class GateThresholds:
    min_pass_rate: float | None = None
    max_hard_fail_rate: float | None = None
    max_pass_rate_drop: float | None = None
    max_hard_fail_increase: float | None = None
    max_regressed_cases: int | None = None
    max_new_hard_fail_cases: int | None = None


def _load_report(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def evaluate_gate(
    compare_report: dict[str, Any],
    thresholds: GateThresholds,
    waived_case_ids: set[str] | None = None,
) -> dict[str, Any]:
    waived = waived_case_ids or set()
    failures: list[str] = []
    metrics = compare_report.get("metrics", {})
    pass_rate = float(metrics.get("pass_rate", {}).get("candidate", 0.0))
    pass_rate_delta = float(metrics.get("pass_rate", {}).get("delta", 0.0))
    hard_fail_rate = float(metrics.get("hard_fail_rate", {}).get("candidate", 0.0))
    hard_fail_delta = float(metrics.get("hard_fail_rate", {}).get("delta", 0.0))

    if thresholds.min_pass_rate is not None and pass_rate < thresholds.min_pass_rate:
        failures.append(
            f"candidate pass_rate {pass_rate:.4f} is below min_pass_rate {thresholds.min_pass_rate:.4f}"
        )

    if (
        thresholds.max_hard_fail_rate is not None
        and hard_fail_rate > thresholds.max_hard_fail_rate
    ):
        failures.append(
            f"candidate hard_fail_rate {hard_fail_rate:.4f} is above max_hard_fail_rate {thresholds.max_hard_fail_rate:.4f}"
        )

    if (
        thresholds.max_pass_rate_drop is not None
        and -pass_rate_delta > thresholds.max_pass_rate_drop
    ):
        failures.append(
            f"pass_rate dropped by {-pass_rate_delta:.4f}, above max_pass_rate_drop {thresholds.max_pass_rate_drop:.4f}"
        )

    if (
        thresholds.max_hard_fail_increase is not None
        and hard_fail_delta > thresholds.max_hard_fail_increase
    ):
        failures.append(
            f"hard_fail_rate increased by {hard_fail_delta:.4f}, above max_hard_fail_increase {thresholds.max_hard_fail_increase:.4f}"
        )

    case_regressions = compare_report.get("case_regressions", [])
    regressed_cases = [
        row.get("case_id")
        for row in case_regressions
        if isinstance(row, dict)
        and bool(row.get("regressed"))
        and isinstance(row.get("case_id"), str)
        and row.get("case_id") not in waived
    ]
    new_hard_fail_cases = [
        case_id
        for case_id in compare_report.get("new_hard_fail_case_ids", [])
        if isinstance(case_id, str) and case_id not in waived
    ]

    if (
        thresholds.max_regressed_cases is not None
        and len(regressed_cases) > thresholds.max_regressed_cases
    ):
        failures.append(
            f"regressed_cases {len(regressed_cases)} exceeds max_regressed_cases {thresholds.max_regressed_cases}"
        )
    if (
        thresholds.max_new_hard_fail_cases is not None
        and len(new_hard_fail_cases) > thresholds.max_new_hard_fail_cases
    ):
        failures.append(
            "new_hard_fail_cases {0} exceeds max_new_hard_fail_cases {1}".format(
                len(new_hard_fail_cases), thresholds.max_new_hard_fail_cases
            )
        )

    passed = not failures
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "passed": passed,
        "failures": failures,
        "waived_case_ids": sorted(waived),
        "regressed_cases_considered": len(regressed_cases),
        "new_hard_fail_cases_considered": len(new_hard_fail_cases),
        "thresholds": asdict(thresholds),
        "baseline_run_id": compare_report.get("baseline_run_id"),
        "candidate_run_id": compare_report.get("candidate_run_id"),
    }


def gate_from_path(path: str | Path, thresholds: GateThresholds) -> dict[str, Any]:
    return evaluate_gate(_load_report(path), thresholds)


def write_gate_decision(decision: dict[str, Any], out_path: str | Path) -> Path:
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(decision, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return target
