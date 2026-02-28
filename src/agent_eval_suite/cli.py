from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_eval_suite.artifacts import write_evidence_pack, write_json
from agent_eval_suite.compare import compare_runs, write_compare_report
from agent_eval_suite.environment import capture_environment_metadata
from agent_eval_suite.gate import GateThresholds, evaluate_gate, write_gate_decision
from agent_eval_suite.importers import PROVIDERS, import_to_suite
from agent_eval_suite.loop_runner import ProposeExecuteRepairRunner
from agent_eval_suite.otel_export import export_run_to_otel
from agent_eval_suite.plugins import DEFAULT_JUDGES, instantiate_judge
from agent_eval_suite.replay_engine import replay_run
from agent_eval_suite.runner import EvalRunner
from agent_eval_suite.scaffold import scaffold_init
from agent_eval_suite.schema import EvalSuite, RunConfig, utc_now_iso


def _default_run_id() -> str:
    return f"run-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"


def _load_json(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _build_run_config(
    args: argparse.Namespace,
    suite: EvalSuite,
    judge_names: list[str],
    judge_configs: dict[str, Any],
    execution_mode: str,
) -> RunConfig:
    captured_env = capture_environment_metadata()
    return RunConfig(
        run_id=args.run_id or _default_run_id(),
        dataset_id=suite.dataset_id,
        agent_version=args.agent_version,
        model=args.model,
        started_at=utc_now_iso(),
        seed=args.seed,
        judges=judge_names,
        judge_configs=judge_configs if isinstance(judge_configs, dict) else {},
        execution_mode=execution_mode,
        pinned_env=captured_env,
        prompt_hash=args.prompt_hash,
        policy_hash=args.policy_hash,
        container_image=args.container_image,
        git_commit=args.git_commit or captured_env.get("git_commit"),
        dependency_lock_hash=args.dependency_lock_hash
        or captured_env.get("dependency_lock_hash"),
    )


def cmd_run(args: argparse.Namespace) -> int:
    suite = EvalSuite.from_path(args.suite)
    judge_names = args.judge or list(DEFAULT_JUDGES)
    all_configs = _load_json(args.judge_config)

    judges = []
    for name in judge_names:
        config = all_configs.get(name, {}) if isinstance(all_configs, dict) else {}
        judges.append(instantiate_judge(name, config=config))

    run_config = _build_run_config(
        args=args,
        suite=suite,
        judge_names=judge_names,
        judge_configs=all_configs,
        execution_mode="trace_score",
    )
    runner = EvalRunner(judges=judges)
    case_results, summary = runner.run(suite, run_config)
    write_evidence_pack(args.out, suite, run_config, summary, case_results)

    if args.summary_json:
        write_json(args.summary_json, summary.to_dict())

    print(json.dumps({"run_id": run_config.run_id, "summary": summary.to_dict()}))
    return 0


def cmd_run_loop(args: argparse.Namespace) -> int:
    suite = EvalSuite.from_path(args.suite)
    judge_names = args.judge or list(DEFAULT_JUDGES)
    all_configs = _load_json(args.judge_config)

    judges = []
    for name in judge_names:
        config = all_configs.get(name, {}) if isinstance(all_configs, dict) else {}
        judges.append(instantiate_judge(name, config=config))

    eval_runner = EvalRunner(judges=judges)
    loop_runner = ProposeExecuteRepairRunner(
        eval_runner=eval_runner,
        propose_command=args.propose_command,
        repair_command=args.repair_command,
        max_repairs=args.max_repairs,
        timeout_seconds=args.command_timeout_seconds,
    )
    generated_suite = loop_runner.run(suite)
    run_config = _build_run_config(
        args=args,
        suite=generated_suite,
        judge_names=judge_names,
        judge_configs=all_configs,
        execution_mode="propose_execute_repair",
    )
    case_results, summary = eval_runner.run(generated_suite, run_config)
    write_evidence_pack(args.out, generated_suite, run_config, summary, case_results)

    if args.summary_json:
        write_json(args.summary_json, summary.to_dict())

    print(
        json.dumps(
            {
                "run_id": run_config.run_id,
                "summary": summary.to_dict(),
                "execution_mode": run_config.execution_mode,
            }
        )
    )
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    report = compare_runs(args.baseline, args.candidate)
    if args.out:
        out_path = Path(args.out)
    else:
        candidate = Path(args.candidate)
        out_path = (
            candidate / "compare" / "baseline_delta.json"
            if candidate.is_dir()
            else Path("compare") / "baseline_delta.json"
        )
    write_compare_report(report, out_path)
    print(json.dumps({"compare_report": str(out_path), "regressions": report["regressions"]}))
    return 0


def cmd_gate(args: argparse.Namespace) -> int:
    with Path(args.compare).open("r", encoding="utf-8") as handle:
        compare_report = json.load(handle)

    thresholds = GateThresholds(
        min_pass_rate=args.min_pass_rate,
        max_hard_fail_rate=args.max_hard_fail_rate,
        max_pass_rate_drop=args.max_pass_rate_drop,
        max_hard_fail_increase=args.max_hard_fail_increase,
    )
    decision = evaluate_gate(compare_report, thresholds)

    if args.out:
        out_path = Path(args.out)
    else:
        out_path = Path(args.compare).parent / "gate_decision.json"
    write_gate_decision(decision, out_path)

    print(json.dumps({"gate_decision": str(out_path), "passed": decision["passed"]}))
    return 0 if decision["passed"] else 1


def cmd_init(args: argparse.Namespace) -> int:
    created, skipped = scaffold_init(args.out, force=args.force)
    if skipped and not args.force:
        print(
            json.dumps(
                {
                    "out": str(args.out),
                    "created": created,
                    "skipped_existing": skipped,
                    "hint": "re-run with --force to overwrite existing files",
                }
            )
        )
        return 1

    print(json.dumps({"out": str(args.out), "created": created, "skipped_existing": skipped}))
    return 0


def cmd_import_trace(args: argparse.Namespace) -> int:
    suite = import_to_suite(
        input_path=args.input,
        provider=args.provider,
        dataset_id=args.dataset_id,
        case_prefix=args.case_prefix,
    )
    if not suite["cases"]:
        print(
            json.dumps(
                {
                    "input": str(args.input),
                    "provider": args.provider,
                    "error": "no trace cases were imported",
                }
            )
        )
        return 1

    write_json(args.out, suite)
    print(
        json.dumps(
            {
                "out": str(args.out),
                "dataset_id": args.dataset_id,
                "cases": len(suite["cases"]),
                "provider_case_counts": suite["metadata"]["provider_case_counts"],
            }
        )
    )
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    report = replay_run(args.run, args.out)
    print(json.dumps(report))
    return 0 if report["replay_passed"] else 1


def cmd_export_otel(args: argparse.Namespace) -> int:
    out = export_run_to_otel(args.run, args.out)
    print(json.dumps({"out": str(out)}))
    return 0


def _add_run_identity_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-id", default=None, help="Override run id")
    parser.add_argument("--agent-version", default="unknown")
    parser.add_argument("--model", default="unknown")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--prompt-hash", default=None)
    parser.add_argument("--policy-hash", default=None)
    parser.add_argument("--container-image", default=None)
    parser.add_argument("--git-commit", default=None)
    parser.add_argument("--dependency-lock-hash", default=None)


def _add_judge_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--judge",
        action="append",
        default=[],
        help="Judge name or module:Class. Can be repeated.",
    )
    parser.add_argument(
        "--judge-config",
        default=None,
        help="JSON file mapping judge names to config objects",
    )
    parser.add_argument(
        "--summary-json", default=None, help="Optional path to write summary JSON"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="agent-eval")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run offline evaluation from suite")
    run_parser.add_argument("--suite", required=True, help="Path to eval suite JSON")
    run_parser.add_argument("--out", required=True, help="Output evidence pack directory")
    _add_run_identity_args(run_parser)
    _add_judge_args(run_parser)
    run_parser.set_defaults(func=cmd_run)

    run_loop_parser = subparsers.add_parser(
        "run-loop",
        help="Run propose/execute/repair loop, then score with deterministic judges",
    )
    run_loop_parser.add_argument("--suite", required=True, help="Path to eval suite JSON")
    run_loop_parser.add_argument(
        "--out", required=True, help="Output evidence pack directory"
    )
    run_loop_parser.add_argument(
        "--propose-command",
        required=True,
        help="Shell command (quoted) for propose step; reads JSON on stdin, writes JSON on stdout",
    )
    run_loop_parser.add_argument(
        "--repair-command",
        default=None,
        help="Optional shell command for repair step; falls back to propose-command if omitted",
    )
    run_loop_parser.add_argument("--max-repairs", type=int, default=2)
    run_loop_parser.add_argument("--command-timeout-seconds", type=int, default=30)
    _add_run_identity_args(run_loop_parser)
    _add_judge_args(run_loop_parser)
    run_loop_parser.set_defaults(func=cmd_run_loop)

    compare_parser = subparsers.add_parser(
        "compare", help="Compare candidate run summary against baseline"
    )
    compare_parser.add_argument("--baseline", required=True, help="Baseline run directory")
    compare_parser.add_argument(
        "--candidate", required=True, help="Candidate run directory"
    )
    compare_parser.add_argument(
        "--out", default=None, help="Output path for compare report JSON"
    )
    compare_parser.set_defaults(func=cmd_compare)

    gate_parser = subparsers.add_parser(
        "gate", help="Apply CI gate thresholds to compare report"
    )
    gate_parser.add_argument("--compare", required=True, help="Compare report JSON path")
    gate_parser.add_argument("--min-pass-rate", type=float, default=None)
    gate_parser.add_argument("--max-hard-fail-rate", type=float, default=None)
    gate_parser.add_argument("--max-pass-rate-drop", type=float, default=None)
    gate_parser.add_argument("--max-hard-fail-increase", type=float, default=None)
    gate_parser.add_argument(
        "--out", default=None, help="Output path for gate decision JSON"
    )
    gate_parser.set_defaults(func=cmd_gate)

    init_parser = subparsers.add_parser(
        "init", help="Scaffold starter suite, judge config, and CI template"
    )
    init_parser.add_argument(
        "--out",
        default=".",
        help="Output directory for generated starter files (default: current directory)",
    )
    init_parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing scaffold files if they already exist",
    )
    init_parser.set_defaults(func=cmd_init)

    import_parser = subparsers.add_parser(
        "import-trace",
        help="Import provider trace export(s) into Agent Eval Suite schema",
    )
    import_parser.add_argument(
        "--provider",
        default="auto",
        choices=list(PROVIDERS),
        help="Trace provider format (default: auto detect)",
    )
    import_parser.add_argument("--input", required=True, help="Input JSON or JSONL path")
    import_parser.add_argument(
        "--out", required=True, help="Output suite JSON path in internal schema"
    )
    import_parser.add_argument(
        "--dataset-id",
        default="imported-suite",
        help="Dataset identifier written to output suite",
    )
    import_parser.add_argument(
        "--case-prefix",
        default="case",
        help="Case id prefix for imported cases",
    )
    import_parser.set_defaults(func=cmd_import_trace)

    replay_parser = subparsers.add_parser(
        "replay",
        help="Re-execute judge scoring from an evidence pack and verify pinned environment",
    )
    replay_parser.add_argument(
        "--run", required=True, help="Path to evidence pack directory to replay"
    )
    replay_parser.add_argument(
        "--out",
        default=None,
        help="Optional output path for replay report JSON",
    )
    replay_parser.set_defaults(func=cmd_replay)

    otel_parser = subparsers.add_parser(
        "export-otel",
        help="Export run events to OpenTelemetry-style GenAI JSONL",
    )
    otel_parser.add_argument(
        "--run", required=True, help="Path to evidence pack directory"
    )
    otel_parser.add_argument("--out", required=True, help="Output JSONL path")
    otel_parser.set_defaults(func=cmd_export_otel)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
