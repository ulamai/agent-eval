from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_eval_suite.schema import CaseResult, EvalSuite, RunConfig, RunSummary, utc_now_iso


def write_json(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def write_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")


def write_evidence_pack(
    output_dir: str | Path,
    suite: EvalSuite,
    run_config: RunConfig,
    summary: RunSummary,
    case_results: list[CaseResult],
) -> Path:
    base = Path(output_dir)
    run_dir = base / "run"
    judges_dir = base / "judges"
    cases_dir = base / "cases"
    compare_dir = base / "compare"

    run_dir.mkdir(parents=True, exist_ok=True)
    judges_dir.mkdir(parents=True, exist_ok=True)
    cases_dir.mkdir(parents=True, exist_ok=True)
    compare_dir.mkdir(parents=True, exist_ok=True)

    events_rows: list[dict[str, Any]] = []
    for case in suite.cases:
        for event in case.trace:
            events_rows.append(
                {
                    "run_id": run_config.run_id,
                    "dataset_id": suite.dataset_id,
                    "case_id": case.case_id,
                    **event.to_dict(),
                }
            )

    write_json(run_dir / "config.json", run_config.to_dict())
    write_json(run_dir / "summary.json", summary.to_dict())
    write_jsonl(run_dir / "events.jsonl", events_rows)

    by_judge: dict[str, list[dict[str, Any]]] = {}
    case_by_id = {case.case_id: case for case in suite.cases}
    for case_result in case_results:
        for judge_result in case_result.judge_results:
            by_judge.setdefault(judge_result.judge_id, []).append(judge_result.to_dict())

        case_dir = cases_dir / case_result.case_id
        case_dir.mkdir(parents=True, exist_ok=True)
        write_json(case_dir / "trajectory.json", case_by_id[case_result.case_id].to_dict())
        write_json(case_dir / "verdicts.json", case_result.to_dict())
        (case_dir / "artifacts").mkdir(exist_ok=True)

    for judge_id, results in by_judge.items():
        write_json(judges_dir / f"{judge_id}.json", results)

    report = {
        "run_config": run_config.to_dict(),
        "summary": summary.to_dict(),
        "cases": [case_result.to_dict() for case_result in case_results],
    }
    write_json(base / "report.json", report)

    manifest = {
        "version": run_config.schema_version,
        "generated_at": utc_now_iso(),
        "run_id": run_config.run_id,
        "dataset_id": suite.dataset_id,
        "files": {
            "report": "report.json",
            "run_config": "run/config.json",
            "run_summary": "run/summary.json",
            "events": "run/events.jsonl",
            "judges_dir": "judges/",
            "cases_dir": "cases/",
            "compare_dir": "compare/",
        },
    }
    write_json(base / "manifest.json", manifest)
    return base
