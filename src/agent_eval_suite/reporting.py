from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _load_json(path: str | Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    source = Path(path)
    with source.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"report payload at {source} must be a JSON object")
    return payload


def _fmt_percent(value: Any) -> str:
    try:
        return f"{float(value) * 100:.2f}%"
    except Exception:
        return "n/a"


def _render_overview(compare_report: dict[str, Any]) -> list[str]:
    overview = compare_report.get("overview", {})
    metrics = compare_report.get("metrics", {})
    pass_rate = metrics.get("pass_rate", {})
    hard_fail = metrics.get("hard_fail_rate", {})
    return [
        "## Overview",
        "",
        f"- Baseline run: `{compare_report.get('baseline_run_id')}`",
        f"- Candidate run: `{compare_report.get('candidate_run_id')}`",
        f"- Dataset: `{compare_report.get('dataset_id')}`",
        f"- Risk level: `{overview.get('risk_level', 'n/a')}`",
        f"- Pass rate: {_fmt_percent(pass_rate.get('baseline'))} -> {_fmt_percent(pass_rate.get('candidate'))} (delta {pass_rate.get('delta', 0):+.4f})",
        f"- Hard-fail rate: {_fmt_percent(hard_fail.get('baseline'))} -> {_fmt_percent(hard_fail.get('candidate'))} (delta {hard_fail.get('delta', 0):+.4f})",
        f"- Regressed cases: {overview.get('regressed_cases', 0)}",
        f"- Improved cases: {overview.get('improved_cases', 0)}",
        f"- New hard-fail cases: {overview.get('new_hard_fail_cases', 0)}",
        f"- Resolved hard-fail cases: {overview.get('resolved_hard_fail_cases', 0)}",
        "",
    ]


def _render_top_regressions(compare_report: dict[str, Any]) -> list[str]:
    rows = compare_report.get("top_regressed_judges", [])
    lines = ["## Top Regressed Judges", ""]
    if not isinstance(rows, list) or not rows:
        lines.append("- No judge regressions detected.")
        lines.append("")
        return lines
    for row in rows[:10]:
        lines.append(
            "- `{judge}`: {baseline:.4f} -> {candidate:.4f} (delta {delta:+.4f})".format(
                judge=row.get("judge_id", "unknown"),
                baseline=float(row.get("baseline", 0.0)),
                candidate=float(row.get("candidate", 0.0)),
                delta=float(row.get("delta", 0.0)),
            )
        )
    lines.append("")
    return lines


def _render_failure_clusters(compare_report: dict[str, Any]) -> list[str]:
    rows = compare_report.get("failure_clusters", {}).get("delta_ranked", [])
    lines = ["## Failure Clusters", ""]
    if not isinstance(rows, list) or not rows:
        lines.append("- No failure cluster deltas available.")
        lines.append("")
        return lines
    for row in rows[:15]:
        lines.append(
            "- `{cluster}`: baseline {b}, candidate {c}, delta {d:+d}".format(
                cluster=row.get("cluster", "unknown"),
                b=int(row.get("baseline_count", 0)),
                c=int(row.get("candidate_count", 0)),
                d=int(row.get("delta", 0)),
            )
        )
    lines.append("")
    return lines


def _render_case_lists(compare_report: dict[str, Any]) -> list[str]:
    new_hard_fail = compare_report.get("new_hard_fail_case_ids", [])
    resolved_hard_fail = compare_report.get("resolved_hard_fail_case_ids", [])
    lines = ["## Hard-Fail Case Changes", ""]
    if isinstance(new_hard_fail, list) and new_hard_fail:
        lines.append("- New hard-fail cases:")
        for case_id in new_hard_fail:
            lines.append(f"  - `{case_id}`")
    else:
        lines.append("- New hard-fail cases: none")
    if isinstance(resolved_hard_fail, list) and resolved_hard_fail:
        lines.append("- Resolved hard-fail cases:")
        for case_id in resolved_hard_fail:
            lines.append(f"  - `{case_id}`")
    else:
        lines.append("- Resolved hard-fail cases: none")
    lines.append("")
    return lines


def _render_gate(gate_report: dict[str, Any] | None) -> list[str]:
    lines = ["## Gate Decision", ""]
    if gate_report is None:
        lines.append("- Gate report not provided.")
        lines.append("")
        return lines

    lines.append(f"- Passed: `{bool(gate_report.get('passed'))}`")
    failures = gate_report.get("failures", [])
    if isinstance(failures, list) and failures:
        lines.append("- Failures:")
        for failure in failures:
            lines.append(f"  - {failure}")
    else:
        lines.append("- Failures: none")
    lines.append("")
    return lines


def _render_replay(replay_report: dict[str, Any] | None) -> list[str]:
    lines = ["## Replay & Environment", ""]
    if replay_report is None:
        lines.append("- Replay report not provided.")
        lines.append("")
        return lines
    lines.append(f"- Replay passed: `{bool(replay_report.get('replay_passed'))}`")
    lines.append(f"- Summary match: `{bool(replay_report.get('summary_match'))}`")
    case_mismatches = replay_report.get("case_mismatches", [])
    env_mismatches = replay_report.get("env_mismatches", [])
    lines.append(
        f"- Case mismatches: {len(case_mismatches) if isinstance(case_mismatches, list) else 0}"
    )
    lines.append(
        f"- Environment mismatches: {len(env_mismatches) if isinstance(env_mismatches, list) else 0}"
    )
    if isinstance(env_mismatches, list) and env_mismatches:
        lines.append("- Environment mismatch details:")
        for row in env_mismatches[:10]:
            lines.append(
                "  - `{key}` pinned=`{p}` current=`{c}`".format(
                    key=row.get("key"),
                    p=row.get("pinned"),
                    c=row.get("current"),
                )
            )
    lines.append("")
    return lines


def generate_markdown_report(
    compare_path: str | Path,
    *,
    out_path: str | Path,
    gate_path: str | Path | None = None,
    replay_path: str | Path | None = None,
    title: str = "Agent Eval Report",
) -> Path:
    compare_report = _load_json(compare_path)
    if compare_report is None:
        raise ValueError("compare report is required")
    gate_report = _load_json(gate_path)
    replay_report = _load_json(replay_path)

    lines: list[str] = [
        f"# {title}",
        "",
        f"_Generated: {datetime.now(UTC).isoformat()}_",
        "",
    ]
    lines.extend(_render_overview(compare_report))
    lines.extend(_render_top_regressions(compare_report))
    lines.extend(_render_failure_clusters(compare_report))
    lines.extend(_render_case_lists(compare_report))
    lines.extend(_render_gate(gate_report))
    lines.extend(_render_replay(replay_report))

    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return target
