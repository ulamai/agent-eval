from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_eval_suite.environment import (
    capture_environment_metadata,
    compare_environment_pins,
)
from agent_eval_suite.plugins import instantiate_judge
from agent_eval_suite.runner import EvalRunner
from agent_eval_suite.schema import EvalCase, EvalSuite, RunConfig, RunSummary


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_run_config(run_dir: Path) -> RunConfig:
    config_payload = _load_json(run_dir / "run" / "config.json")
    return RunConfig.from_dict(config_payload)


def _load_suite_from_evidence(run_dir: Path) -> EvalSuite:
    case_paths = sorted((run_dir / "cases").glob("*/trajectory.json"))
    cases = []
    for path in case_paths:
        payload = _load_json(path)
        cases.append(EvalCase.from_dict(payload))
    dataset_id = _load_json(run_dir / "run" / "summary.json").get("dataset_id", "dataset-unknown")
    return EvalSuite(dataset_id=str(dataset_id), cases=cases)


def _load_saved_case_results(run_dir: Path) -> dict[str, dict[str, Any]]:
    results: dict[str, dict[str, Any]] = {}
    for verdict_path in sorted((run_dir / "cases").glob("*/verdicts.json")):
        payload = _load_json(verdict_path)
        case_id = payload.get("case_id")
        if isinstance(case_id, str):
            results[case_id] = payload
    return results


def replay_run(run_path: str | Path, out_path: str | Path | None = None) -> dict[str, Any]:
    run_dir = Path(run_path)
    run_config = _load_run_config(run_dir)
    suite = _load_suite_from_evidence(run_dir)
    saved_summary = RunSummary.from_dict(_load_json(run_dir / "run" / "summary.json"))
    saved_cases = _load_saved_case_results(run_dir)

    judges = []
    for name in run_config.judges:
        config = (
            run_config.judge_configs.get(name, {})
            if isinstance(run_config.judge_configs, dict)
            else {}
        )
        judges.append(instantiate_judge(name, config=config))

    runner = EvalRunner(judges)
    replayed_cases, replayed_summary = runner.run(suite, run_config)

    case_mismatches: list[dict[str, Any]] = []
    for case_result in replayed_cases:
        saved = saved_cases.get(case_result.case_id, {})
        if not saved:
            case_mismatches.append(
                {"case_id": case_result.case_id, "error": "missing saved case verdict"}
            )
            continue
        if bool(saved.get("passed")) != case_result.passed or bool(
            saved.get("hard_failed")
        ) != case_result.hard_failed:
            case_mismatches.append(
                {
                    "case_id": case_result.case_id,
                    "saved_passed": saved.get("passed"),
                    "replayed_passed": case_result.passed,
                    "saved_hard_failed": saved.get("hard_failed"),
                    "replayed_hard_failed": case_result.hard_failed,
                }
            )

    summary_match = replayed_summary.to_dict() == saved_summary.to_dict()
    current_env = capture_environment_metadata()
    pinned_env = dict(run_config.pinned_env)
    pinned_env["container_image"] = run_config.container_image
    pinned_env["prompt_hash"] = run_config.prompt_hash
    pinned_env["policy_hash"] = run_config.policy_hash
    pinned_env["git_commit"] = run_config.git_commit or pinned_env.get("git_commit")
    pinned_env["dependency_lock_hash"] = run_config.dependency_lock_hash or pinned_env.get(
        "dependency_lock_hash"
    )
    env_mismatches = compare_environment_pins(pinned_env, current_env)
    replay_passed = summary_match and not case_mismatches and not env_mismatches

    report = {
        "run_id": run_config.run_id,
        "dataset_id": run_config.dataset_id,
        "replay_passed": replay_passed,
        "summary_match": summary_match,
        "saved_summary": saved_summary.to_dict(),
        "replayed_summary": replayed_summary.to_dict(),
        "case_mismatches": case_mismatches,
        "env_mismatches": env_mismatches,
    }

    target = Path(out_path) if out_path is not None else run_dir / "compare" / "replay_report.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    report["out"] = str(target)
    return report
