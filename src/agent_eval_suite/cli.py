from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_eval_suite.artifacts import write_evidence_pack, write_json
from agent_eval_suite.adapter_conformance import run_adapter_conformance
from agent_eval_suite.benchmarks import ARCHETYPES, write_benchmark_suite
from agent_eval_suite.compare import compare_runs, write_compare_report
from agent_eval_suite.contracts import run_contract_checks
from agent_eval_suite.environment import capture_environment_metadata
from agent_eval_suite.gate import GateThresholds, evaluate_gate, write_gate_decision
from agent_eval_suite.framework_importers import FRAMEWORKS, import_framework_to_suite
from agent_eval_suite.importers import PROVIDERS, import_to_suite
from agent_eval_suite.loop_runner import ProposeExecuteRepairRunner
from agent_eval_suite.otel_export import export_run_to_otel
from agent_eval_suite.plugins import DEFAULT_JUDGES, instantiate_judge
from agent_eval_suite.provenance import (
    apply_manifest_hashes,
    verify_attestation,
    write_attestation,
)
from agent_eval_suite.registry import (
    DEFAULT_REGISTRY_PATH,
    add_waiver,
    get_baseline,
    get_active_waivers_for_baseline,
    list_baselines,
    list_datasets,
    list_audit_log,
    list_approvals,
    list_waivers,
    promote_baseline,
    register_dataset,
    resolve_baseline_reference,
    set_baseline,
)
from agent_eval_suite.replay_engine import replay_execute_run, replay_run
from agent_eval_suite.reporting import generate_markdown_report
from agent_eval_suite.runner import EvalRunner
from agent_eval_suite.scaffold import scaffold_init
from agent_eval_suite.schema_governance import (
    LATEST_SCHEMA_VERSION,
    migrate_suite_file,
    validate_suite_file,
)
from agent_eval_suite.stability import StabilityOptions, run_stability_check
from agent_eval_suite.schema import EvalSuite, RunConfig, utc_now_iso


def _default_run_id() -> str:
    return f"run-{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"


def _load_json(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    with Path(path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _emit_structured_error(
    code: str, message: str, details: dict[str, Any] | None = None
) -> None:
    payload = {"error": {"code": code, "message": message, "details": details or {}}}
    print(json.dumps(payload), file=sys.stderr)


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
        strict_side_effects=args.strict_side_effects,
    )
    generated_suite = loop_runner.run(suite)
    run_config = _build_run_config(
        args=args,
        suite=generated_suite,
        judge_names=judge_names,
        judge_configs=all_configs,
        execution_mode="propose_execute_repair",
    )
    run_config.execution_config = {
        "propose_command": args.propose_command,
        "repair_command": args.repair_command,
        "max_repairs": args.max_repairs,
        "command_timeout_seconds": args.command_timeout_seconds,
        "strict_side_effects": args.strict_side_effects,
    }
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
    baseline_path, baseline_entry = resolve_baseline_reference(
        args.baseline, path=args.registry_path
    )
    report = compare_runs(
        baseline_path,
        args.candidate,
        enforce_compatibility=not args.allow_incompatible,
    )
    report["baseline_reference"] = {
        "input": args.baseline,
        "resolved_path": baseline_path,
        "registry_entry": baseline_entry,
    }
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


def cmd_registry_dataset_add(args: argparse.Namespace) -> int:
    tags = args.tag or []
    entry = register_dataset(
        suite_path=args.suite,
        dataset_id=args.dataset_id,
        description=args.description,
        tags=tags,
        path=args.registry_path,
    )
    print(json.dumps({"dataset_registered": entry, "registry_path": args.registry_path}))
    return 0


def cmd_registry_dataset_list(args: argparse.Namespace) -> int:
    rows = list_datasets(path=args.registry_path)
    print(json.dumps({"datasets": rows, "count": len(rows), "registry_path": args.registry_path}))
    return 0


def cmd_registry_baseline_set(args: argparse.Namespace) -> int:
    entry = set_baseline(
        name=args.name,
        run_path=args.run,
        dataset_id=args.dataset_id,
        notes=args.notes,
        path=args.registry_path,
    )
    print(json.dumps({"baseline_set": entry, "registry_path": args.registry_path}))
    return 0


def cmd_registry_baseline_list(args: argparse.Namespace) -> int:
    rows = list_baselines(path=args.registry_path)
    print(json.dumps({"baselines": rows, "count": len(rows), "registry_path": args.registry_path}))
    return 0


def cmd_registry_baseline_promote(args: argparse.Namespace) -> int:
    payload = promote_baseline(
        name=args.name,
        run_path=args.run,
        approved_by=args.approved_by,
        rationale=args.rationale,
        dataset_id=args.dataset_id,
        notes=args.notes,
        path=args.registry_path,
    )
    print(json.dumps({"promotion": payload, "registry_path": args.registry_path}))
    return 0


def cmd_registry_baseline_show(args: argparse.Namespace) -> int:
    entry = get_baseline(args.name, path=args.registry_path)
    if entry is None:
        print(
            json.dumps(
                {
                    "error": f"baseline '{args.name}' not found",
                    "registry_path": args.registry_path,
                }
            )
        )
        return 1
    print(json.dumps({"baseline": entry, "registry_path": args.registry_path}))
    return 0


def cmd_registry_approval_list(args: argparse.Namespace) -> int:
    rows = list_approvals(name=args.name, path=args.registry_path)
    print(
        json.dumps(
            {
                "approvals": rows,
                "count": len(rows),
                "registry_path": args.registry_path,
            }
        )
    )
    return 0


def cmd_registry_waiver_add(args: argparse.Namespace) -> int:
    entry = add_waiver(
        baseline_name=args.baseline_name,
        reason=args.reason,
        approved_by=args.approved_by,
        case_id=args.case_id,
        judge_id=args.judge_id,
        regression_key=args.regression_key,
        expires_at=args.expires_at,
        path=args.registry_path,
    )
    print(json.dumps({"waiver": entry, "registry_path": args.registry_path}))
    return 0


def cmd_registry_waiver_list(args: argparse.Namespace) -> int:
    rows = list_waivers(
        baseline_name=args.baseline_name,
        active_only=args.active_only,
        path=args.registry_path,
    )
    print(
        json.dumps(
            {"waivers": rows, "count": len(rows), "registry_path": args.registry_path}
        )
    )
    return 0


def cmd_registry_audit_log(args: argparse.Namespace) -> int:
    rows = list_audit_log(path=args.registry_path, limit=args.limit)
    print(json.dumps({"audit_log": rows, "count": len(rows), "registry_path": args.registry_path}))
    return 0


def cmd_gate(args: argparse.Namespace) -> int:
    with Path(args.compare).open("r", encoding="utf-8") as handle:
        compare_report = json.load(handle)

    waived_case_ids: set[str] = set()
    waiver_refs: list[dict[str, Any]] = []
    if args.apply_waivers:
        if not args.baseline_name:
            raise ValueError("--baseline-name is required when --apply-waivers is set")
        waiver_refs = get_active_waivers_for_baseline(
            args.baseline_name, path=args.registry_path
        )
        for waiver in waiver_refs:
            case_id = waiver.get("case_id")
            if isinstance(case_id, str) and case_id:
                waived_case_ids.add(case_id)

    thresholds = GateThresholds(
        min_pass_rate=args.min_pass_rate,
        max_hard_fail_rate=args.max_hard_fail_rate,
        max_pass_rate_drop=args.max_pass_rate_drop,
        max_hard_fail_increase=args.max_hard_fail_increase,
        max_regressed_cases=args.max_regressed_cases,
        max_new_hard_fail_cases=args.max_new_hard_fail_cases,
    )
    decision = evaluate_gate(
        compare_report, thresholds, waived_case_ids=waived_case_ids
    )
    decision["waiver_refs"] = waiver_refs

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
        strict=args.strict,
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
    if args.diagnostics_out:
        write_json(args.diagnostics_out, suite["metadata"].get("import_diagnostics", []))
    print(
        json.dumps(
            {
                "out": str(args.out),
                "dataset_id": args.dataset_id,
                "cases": len(suite["cases"]),
                "provider_case_counts": suite["metadata"]["provider_case_counts"],
                "diagnostics_count": len(
                    suite["metadata"].get("import_diagnostics", [])
                ),
            }
        )
    )
    return 0


def cmd_import_framework(args: argparse.Namespace) -> int:
    suite = import_framework_to_suite(
        input_path=args.input,
        framework=args.framework,
        dataset_id=args.dataset_id,
        case_prefix=args.case_prefix,
        strict=args.strict,
    )
    if not suite["cases"]:
        print(
            json.dumps(
                {
                    "input": str(args.input),
                    "framework": args.framework,
                    "error": "no trace cases were imported",
                }
            )
        )
        return 1

    write_json(args.out, suite)
    if args.diagnostics_out:
        write_json(args.diagnostics_out, suite["metadata"].get("import_diagnostics", []))
    print(
        json.dumps(
            {
                "out": str(args.out),
                "dataset_id": args.dataset_id,
                "cases": len(suite["cases"]),
                "framework_case_counts": suite["metadata"]["framework_case_counts"],
                "diagnostics_count": len(
                    suite["metadata"].get("import_diagnostics", [])
                ),
            }
        )
    )
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    report = replay_run(args.run, args.out)
    print(json.dumps(report))
    return 0 if report["replay_passed"] else 1


def cmd_replay_exec(args: argparse.Namespace) -> int:
    report = replay_execute_run(args.run, args.out)
    print(json.dumps(report))
    return 0 if report["execution_replay_passed"] else 1


def cmd_export_otel(args: argparse.Namespace) -> int:
    out = export_run_to_otel(args.run, args.out)
    print(json.dumps({"out": str(out)}))
    return 0


def cmd_attest(args: argparse.Namespace) -> int:
    manifest_path = apply_manifest_hashes(args.run)
    out = write_attestation(
        args.run,
        out_path=args.out,
        secret=args.secret,
        signer=args.signer,
    )
    print(json.dumps({"manifest": str(manifest_path), "attestation": str(out)}))
    return 0


def cmd_verify_attestation(args: argparse.Namespace) -> int:
    report = verify_attestation(
        args.run,
        attestation_path=args.attestation,
        secret=args.secret,
    )
    if args.out:
        write_json(args.out, report)
    print(json.dumps(report))
    return 0 if report["passed"] else 1


def cmd_report_markdown(args: argparse.Namespace) -> int:
    out = generate_markdown_report(
        compare_path=args.compare,
        gate_path=args.gate,
        replay_path=args.replay,
        out_path=args.out,
        title=args.title,
    )
    print(json.dumps({"out": str(out)}))
    return 0


def cmd_schema_validate(args: argparse.Namespace) -> int:
    report = validate_suite_file(
        args.input,
        strict=args.strict,
        require_version=args.require_version,
    )
    print(json.dumps(report))
    return 0 if report["passed"] else 1


def cmd_schema_migrate(args: argparse.Namespace) -> int:
    report = migrate_suite_file(
        args.input,
        args.output,
        target_version=args.target_version,
    )
    print(json.dumps(report))
    return 0 if report["validation"]["passed"] else 1


def cmd_adapter_conformance(args: argparse.Namespace) -> int:
    report = run_adapter_conformance(
        fixtures_dir=args.fixtures_dir,
        min_fixtures_per_provider=args.min_fixtures_per_provider,
        strict_import=args.strict_import,
    )
    if args.out:
        write_json(args.out, report)
    print(json.dumps(report))
    return 0 if report["passed"] else 1


def cmd_contracts_check(args: argparse.Namespace) -> int:
    report = run_contract_checks(
        schema_fixtures_dir=args.schema_fixtures_dir,
        adapter_fixtures_dir=args.adapter_fixtures_dir,
        min_fixtures_per_provider=args.min_fixtures_per_provider,
    )
    if args.out:
        write_json(args.out, report)
    print(json.dumps(report))
    return 0 if report["passed"] else 1


def cmd_stability_check(args: argparse.Namespace) -> int:
    judge_names = args.judge or list(DEFAULT_JUDGES)
    judge_configs = _load_json(args.judge_config)
    options = StabilityOptions(
        runs=args.runs,
        execution_mode=args.execution_mode,
        propose_command=args.propose_command,
        repair_command=args.repair_command,
        max_repairs=args.max_repairs,
        command_timeout_seconds=args.command_timeout_seconds,
        strict_side_effects=args.strict_side_effects,
        quarantine_min_pass_rate=args.quarantine_min_pass_rate,
    )
    report = run_stability_check(
        args.suite,
        judge_names=judge_names,
        judge_configs=judge_configs if isinstance(judge_configs, dict) else {},
        options=options,
    )
    if args.out:
        write_json(args.out, report)
    print(json.dumps(report))
    return 0 if not report["flaky_case_ids"] else 1


def cmd_benchmark_generate(args: argparse.Namespace) -> int:
    out = write_benchmark_suite(
        archetype=args.archetype,
        cases=args.cases,
        out_path=args.out,
        seed=args.seed,
        dataset_id=args.dataset_id,
    )
    print(json.dumps({"out": str(out), "archetype": args.archetype, "cases": args.cases}))
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
    run_loop_parser.add_argument(
        "--strict-side-effects",
        action="store_true",
        help="Fail loop attempts when tool calls do not have deterministic side-effect responses",
    )
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
        "--registry-path",
        default=DEFAULT_REGISTRY_PATH,
        help="Registry path used to resolve baseline names (default: .agent_eval/registry.json)",
    )
    compare_parser.add_argument(
        "--allow-incompatible",
        action="store_true",
        help="Allow compare even if dataset/case compatibility checks fail",
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
    gate_parser.add_argument("--max-regressed-cases", type=int, default=None)
    gate_parser.add_argument("--max-new-hard-fail-cases", type=int, default=None)
    gate_parser.add_argument(
        "--apply-waivers",
        action="store_true",
        help="Apply active baseline waivers from registry during gate evaluation",
    )
    gate_parser.add_argument(
        "--baseline-name",
        default=None,
        help="Baseline name used to resolve active waivers (required with --apply-waivers)",
    )
    gate_parser.add_argument(
        "--registry-path",
        default=DEFAULT_REGISTRY_PATH,
        help="Registry path for baseline waivers (default: .agent_eval/registry.json)",
    )
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
        "--strict",
        action="store_true",
        help="Fail import on unknown top-level fields or empty parsed traces",
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
    import_parser.add_argument(
        "--diagnostics-out",
        default=None,
        help="Optional path to write import diagnostics JSON",
    )
    import_parser.set_defaults(func=cmd_import_trace)

    framework_import_parser = subparsers.add_parser(
        "import-framework",
        help="Import framework-native trace exports into Agent Eval Suite schema",
    )
    framework_import_parser.add_argument(
        "--framework",
        default="auto",
        choices=list(FRAMEWORKS),
        help="Framework trace format (default: auto detect)",
    )
    framework_import_parser.add_argument("--input", required=True, help="Input JSON or JSONL path")
    framework_import_parser.add_argument(
        "--out", required=True, help="Output suite JSON path in internal schema"
    )
    framework_import_parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail import on empty parsed traces",
    )
    framework_import_parser.add_argument(
        "--dataset-id",
        default="framework-imported-suite",
        help="Dataset identifier written to output suite",
    )
    framework_import_parser.add_argument(
        "--case-prefix",
        default="case",
        help="Case id prefix for imported cases",
    )
    framework_import_parser.add_argument(
        "--diagnostics-out",
        default=None,
        help="Optional path to write import diagnostics JSON",
    )
    framework_import_parser.set_defaults(func=cmd_import_framework)

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

    replay_exec_parser = subparsers.add_parser(
        "replay-exec",
        help="Re-run propose/execute/repair commands and compare trajectory + verdict parity",
    )
    replay_exec_parser.add_argument(
        "--run", required=True, help="Path to run-loop evidence pack directory"
    )
    replay_exec_parser.add_argument(
        "--out",
        default=None,
        help="Optional output path for replay-exec report JSON",
    )
    replay_exec_parser.set_defaults(func=cmd_replay_exec)

    otel_parser = subparsers.add_parser(
        "export-otel",
        help="Export run events to OpenTelemetry-style GenAI JSONL",
    )
    otel_parser.add_argument(
        "--run", required=True, help="Path to evidence pack directory"
    )
    otel_parser.add_argument("--out", required=True, help="Output JSONL path")
    otel_parser.set_defaults(func=cmd_export_otel)

    attest_parser = subparsers.add_parser(
        "attest", help="Generate provenance attestation for an evidence pack"
    )
    attest_parser.add_argument("--run", required=True, help="Path to evidence pack directory")
    attest_parser.add_argument(
        "--out", default=None, help="Optional output path for attestation JSON"
    )
    attest_parser.add_argument(
        "--secret",
        default=None,
        help="Optional signing secret (HMAC-SHA256). Omit for unsigned attestation.",
    )
    attest_parser.add_argument("--signer", default="local")
    attest_parser.set_defaults(func=cmd_attest)

    verify_attest_parser = subparsers.add_parser(
        "verify-attestation", help="Verify evidence pack attestation and hashes"
    )
    verify_attest_parser.add_argument(
        "--run", required=True, help="Path to evidence pack directory"
    )
    verify_attest_parser.add_argument(
        "--attestation",
        default=None,
        help="Optional attestation file path (defaults to run/provenance_attestation.json)",
    )
    verify_attest_parser.add_argument(
        "--secret",
        default=None,
        help="Optional signing secret for signature verification",
    )
    verify_attest_parser.add_argument(
        "--out", default=None, help="Optional JSON output path for verify report"
    )
    verify_attest_parser.set_defaults(func=cmd_verify_attestation)

    report_parser = subparsers.add_parser(
        "report", help="Generate human-readable reports from eval artifacts"
    )
    report_subparsers = report_parser.add_subparsers(
        dest="report_command", required=True
    )
    report_md_parser = report_subparsers.add_parser(
        "markdown", help="Generate markdown report from compare/gate/replay outputs"
    )
    report_md_parser.add_argument("--compare", required=True, help="Compare report JSON path")
    report_md_parser.add_argument("--gate", default=None, help="Optional gate report JSON path")
    report_md_parser.add_argument(
        "--replay", default=None, help="Optional replay report JSON path"
    )
    report_md_parser.add_argument("--out", required=True, help="Output markdown file path")
    report_md_parser.add_argument(
        "--title", default="Agent Eval Report", help="Markdown report title"
    )
    report_md_parser.set_defaults(func=cmd_report_markdown)

    schema_parser = subparsers.add_parser("schema", help="Schema governance commands")
    schema_subparsers = schema_parser.add_subparsers(
        dest="schema_command", required=True
    )

    schema_validate_parser = schema_subparsers.add_parser(
        "validate", help="Validate suite JSON against schema contract"
    )
    schema_validate_parser.add_argument("--input", required=True, help="Suite JSON file")
    schema_validate_parser.add_argument(
        "--strict", action="store_true", help="Fail on unknown fields"
    )
    schema_validate_parser.add_argument(
        "--require-version",
        default=None,
        help="Require metadata.schema_version to match this value",
    )
    schema_validate_parser.set_defaults(func=cmd_schema_validate)

    schema_migrate_parser = schema_subparsers.add_parser(
        "migrate", help="Migrate suite JSON to latest schema contract"
    )
    schema_migrate_parser.add_argument("--input", required=True, help="Input suite JSON file")
    schema_migrate_parser.add_argument("--output", required=True, help="Output suite JSON file")
    schema_migrate_parser.add_argument(
        "--target-version",
        default=LATEST_SCHEMA_VERSION,
        help=f"Target schema version (default: {LATEST_SCHEMA_VERSION})",
    )
    schema_migrate_parser.set_defaults(func=cmd_schema_migrate)

    adapter_conformance_parser = subparsers.add_parser(
        "adapter-conformance",
        help="Run strict adapter conformance checks on fixture corpus",
    )
    adapter_conformance_parser.add_argument(
        "--fixtures-dir",
        default="tests/fixtures/adapters",
        help="Directory with provider fixture JSON files",
    )
    adapter_conformance_parser.add_argument(
        "--min-fixtures-per-provider",
        type=int,
        default=2,
        help="Minimum fixtures required for each provider",
    )
    adapter_conformance_parser.add_argument(
        "--strict-import",
        action="store_true",
        default=True,
        help="Use strict importer mode during conformance checks",
    )
    adapter_conformance_parser.add_argument(
        "--no-strict-import",
        dest="strict_import",
        action="store_false",
        help="Disable strict importer mode during conformance checks",
    )
    adapter_conformance_parser.add_argument(
        "--out", default=None, help="Optional JSON output path for conformance report"
    )
    adapter_conformance_parser.set_defaults(func=cmd_adapter_conformance)

    contracts_check_parser = subparsers.add_parser(
        "contracts-check",
        help="Run schema back-compat and adapter conformance checks for CI",
    )
    contracts_check_parser.add_argument(
        "--schema-fixtures-dir",
        default="tests/fixtures/schema_backcompat",
        help="Schema fixture directory for migration/validation checks",
    )
    contracts_check_parser.add_argument(
        "--adapter-fixtures-dir",
        default="tests/fixtures/adapters",
        help="Adapter fixture directory",
    )
    contracts_check_parser.add_argument(
        "--min-fixtures-per-provider",
        type=int,
        default=2,
        help="Minimum fixtures required for each provider",
    )
    contracts_check_parser.add_argument(
        "--out", default=None, help="Optional JSON output path for contracts report"
    )
    contracts_check_parser.set_defaults(func=cmd_contracts_check)

    stability_parser = subparsers.add_parser(
        "stability-check",
        help="Run repeated evaluations to detect flaky behavior and recommend quarantine lanes",
    )
    stability_parser.add_argument("--suite", required=True, help="Path to eval suite JSON")
    stability_parser.add_argument(
        "--runs", type=int, default=5, help="Number of repeated runs (>=2)"
    )
    stability_parser.add_argument(
        "--execution-mode",
        choices=["trace_score", "propose_execute_repair"],
        default="trace_score",
        help="Execution mode for each stability run",
    )
    stability_parser.add_argument(
        "--propose-command",
        default=None,
        help="Required when --execution-mode propose_execute_repair",
    )
    stability_parser.add_argument(
        "--repair-command",
        default=None,
        help="Optional repair command for propose_execute_repair mode",
    )
    stability_parser.add_argument("--max-repairs", type=int, default=2)
    stability_parser.add_argument("--command-timeout-seconds", type=int, default=30)
    stability_parser.add_argument(
        "--strict-side-effects",
        action="store_true",
        help="Fail propose/repair attempts when side-effect responses are missing",
    )
    stability_parser.add_argument(
        "--quarantine-min-pass-rate",
        type=float,
        default=0.98,
        help="Recommend quarantine when flaky case pass_rate is below this threshold",
    )
    stability_parser.add_argument(
        "--out", default=None, help="Optional JSON output path for stability report"
    )
    _add_judge_args(stability_parser)
    stability_parser.set_defaults(func=cmd_stability_check)

    benchmark_parser = subparsers.add_parser(
        "benchmark-generate",
        help="Generate synthetic public benchmark suite by agent archetype",
    )
    benchmark_parser.add_argument(
        "--archetype",
        required=True,
        choices=list(ARCHETYPES),
        help="Benchmark archetype",
    )
    benchmark_parser.add_argument(
        "--cases", type=int, default=20, help="Number of benchmark cases"
    )
    benchmark_parser.add_argument(
        "--seed", type=int, default=0, help="Deterministic benchmark generator seed"
    )
    benchmark_parser.add_argument(
        "--dataset-id", default=None, help="Optional dataset id override"
    )
    benchmark_parser.add_argument("--out", required=True, help="Output suite JSON path")
    benchmark_parser.set_defaults(func=cmd_benchmark_generate)

    registry_parser = subparsers.add_parser(
        "registry", help="Manage local dataset and baseline registry"
    )
    registry_subparsers = registry_parser.add_subparsers(
        dest="registry_command", required=True
    )

    dataset_add_parser = registry_subparsers.add_parser(
        "dataset-add", help="Register a dataset suite in the local registry"
    )
    dataset_add_parser.add_argument("--suite", required=True, help="Suite JSON file path")
    dataset_add_parser.add_argument("--dataset-id", default=None)
    dataset_add_parser.add_argument("--description", default=None)
    dataset_add_parser.add_argument("--tag", action="append", default=[])
    dataset_add_parser.add_argument(
        "--registry-path",
        default=DEFAULT_REGISTRY_PATH,
        help="Registry path (default: .agent_eval/registry.json)",
    )
    dataset_add_parser.set_defaults(func=cmd_registry_dataset_add)

    dataset_list_parser = registry_subparsers.add_parser(
        "dataset-list", help="List registered datasets"
    )
    dataset_list_parser.add_argument(
        "--registry-path",
        default=DEFAULT_REGISTRY_PATH,
        help="Registry path (default: .agent_eval/registry.json)",
    )
    dataset_list_parser.set_defaults(func=cmd_registry_dataset_list)

    baseline_set_parser = registry_subparsers.add_parser(
        "baseline-set", help="Set or update a named baseline reference"
    )
    baseline_set_parser.add_argument("--name", required=True)
    baseline_set_parser.add_argument("--run", required=True, help="Evidence pack run directory")
    baseline_set_parser.add_argument("--dataset-id", default=None)
    baseline_set_parser.add_argument("--notes", default=None)
    baseline_set_parser.add_argument(
        "--registry-path",
        default=DEFAULT_REGISTRY_PATH,
        help="Registry path (default: .agent_eval/registry.json)",
    )
    baseline_set_parser.set_defaults(func=cmd_registry_baseline_set)

    baseline_list_parser = registry_subparsers.add_parser(
        "baseline-list", help="List named baselines"
    )
    baseline_list_parser.add_argument(
        "--registry-path",
        default=DEFAULT_REGISTRY_PATH,
        help="Registry path (default: .agent_eval/registry.json)",
    )
    baseline_list_parser.set_defaults(func=cmd_registry_baseline_list)

    baseline_promote_parser = registry_subparsers.add_parser(
        "baseline-promote", help="Set baseline and record approval metadata"
    )
    baseline_promote_parser.add_argument("--name", required=True)
    baseline_promote_parser.add_argument("--run", required=True, help="Evidence pack run directory")
    baseline_promote_parser.add_argument("--approved-by", required=True)
    baseline_promote_parser.add_argument("--rationale", required=True)
    baseline_promote_parser.add_argument("--dataset-id", default=None)
    baseline_promote_parser.add_argument("--notes", default=None)
    baseline_promote_parser.add_argument(
        "--registry-path",
        default=DEFAULT_REGISTRY_PATH,
        help="Registry path (default: .agent_eval/registry.json)",
    )
    baseline_promote_parser.set_defaults(func=cmd_registry_baseline_promote)

    baseline_show_parser = registry_subparsers.add_parser(
        "baseline-show", help="Show one named baseline"
    )
    baseline_show_parser.add_argument("--name", required=True)
    baseline_show_parser.add_argument(
        "--registry-path",
        default=DEFAULT_REGISTRY_PATH,
        help="Registry path (default: .agent_eval/registry.json)",
    )
    baseline_show_parser.set_defaults(func=cmd_registry_baseline_show)

    approval_list_parser = registry_subparsers.add_parser(
        "approval-list", help="List baseline promotion approvals"
    )
    approval_list_parser.add_argument("--name", default=None)
    approval_list_parser.add_argument(
        "--registry-path",
        default=DEFAULT_REGISTRY_PATH,
        help="Registry path (default: .agent_eval/registry.json)",
    )
    approval_list_parser.set_defaults(func=cmd_registry_approval_list)

    waiver_add_parser = registry_subparsers.add_parser(
        "waiver-add", help="Add a baseline waiver for a known regression scope"
    )
    waiver_add_parser.add_argument("--baseline-name", required=True)
    waiver_add_parser.add_argument("--approved-by", required=True)
    waiver_add_parser.add_argument("--reason", required=True)
    waiver_add_parser.add_argument("--case-id", default=None)
    waiver_add_parser.add_argument("--judge-id", default=None)
    waiver_add_parser.add_argument("--regression-key", default=None)
    waiver_add_parser.add_argument(
        "--expires-at",
        default=None,
        help="Optional ISO-8601 expiry timestamp for this waiver",
    )
    waiver_add_parser.add_argument(
        "--registry-path",
        default=DEFAULT_REGISTRY_PATH,
        help="Registry path (default: .agent_eval/registry.json)",
    )
    waiver_add_parser.set_defaults(func=cmd_registry_waiver_add)

    waiver_list_parser = registry_subparsers.add_parser(
        "waiver-list", help="List waivers"
    )
    waiver_list_parser.add_argument("--baseline-name", default=None)
    waiver_list_parser.add_argument("--active-only", action="store_true")
    waiver_list_parser.add_argument(
        "--registry-path",
        default=DEFAULT_REGISTRY_PATH,
        help="Registry path (default: .agent_eval/registry.json)",
    )
    waiver_list_parser.set_defaults(func=cmd_registry_waiver_list)

    audit_log_parser = registry_subparsers.add_parser(
        "audit-log", help="Show registry audit events"
    )
    audit_log_parser.add_argument("--limit", type=int, default=100)
    audit_log_parser.add_argument(
        "--registry-path",
        default=DEFAULT_REGISTRY_PATH,
        help="Registry path (default: .agent_eval/registry.json)",
    )
    audit_log_parser.set_defaults(func=cmd_registry_audit_log)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse already printed usage/help; preserve behavior.
        code = exc.code if isinstance(exc.code, int) else 1
        return code

    try:
        return args.func(args)
    except FileNotFoundError as exc:
        _emit_structured_error(
            code="file_not_found",
            message=str(exc),
            details={"exception_type": exc.__class__.__name__},
        )
        return 1
    except json.JSONDecodeError as exc:
        _emit_structured_error(
            code="invalid_json",
            message=str(exc),
            details={
                "line": exc.lineno,
                "column": exc.colno,
                "position": exc.pos,
                "exception_type": exc.__class__.__name__,
            },
        )
        return 1
    except ValueError as exc:
        _emit_structured_error(
            code="validation_error",
            message=str(exc),
            details={"exception_type": exc.__class__.__name__},
        )
        return 1
    except Exception as exc:  # pragma: no cover - defensive top-level handler
        _emit_structured_error(
            code="internal_error",
            message=str(exc),
            details={"exception_type": exc.__class__.__name__},
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
