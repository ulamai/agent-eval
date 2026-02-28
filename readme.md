# Agent Eval Suite

Agent Eval Suite is an opinionated open-source evaluation layer for agent runs, built for teams that need release-quality evidence instead of one-off spot checks. It focuses on deterministic scoring, trajectory-aware analysis, and CI-friendly pass/fail outcomes so model, prompt, and toolchain changes can be evaluated with the same rigor as software changes.

The project generalizes the `bench + replay` pattern into a reusable product surface: ingest traces from common agent stacks, score them with deterministic judges, compare against baselines, and gate releases automatically. It also ships a local-first evidence pack format that preserves run config, case verdicts, and replay artifacts so every decision is auditable and reproducible.

## Product Wedge

Ship agents with evidence, not guesswork:

- Stable trace schema and replay contract.
- Deterministic-first judges for hard correctness and policy conformance.
- Baseline-vs-candidate comparison with CI gate exit codes.
- Local artifact outputs that make regressions explainable.

## Open-Source Scope

1. Trace schema + replay contract for agent runs.
2. Offline eval runner + baseline compare + CI gate exit codes.
3. Judge plugin system.
4. Deterministic judges:
   - `ToolContractJudge`
   - `PolicyJudge`
   - `RegexJudge` / `JSONSchemaJudge`
5. Optional `LeanJudge` plugin via external adapter command contract.
6. Local artifact outputs:
   - machine-readable JSON report
   - evidence pack folder structure

## Core Concepts

- `trace`: ordered events from an agent run, including tool calls and outcomes.
- `replay`: deterministic re-execution of a trace under a pinned config.
- `judge`: scoring component that emits `pass/fail`, score, and evidence.
- `baseline`: reference run used for regression comparison.
- `gate`: policy that converts eval deltas into CI pass/fail behavior.

## Trace Schema v1.0 (Opinionated)

Minimum required entities:

1. `run`
   - `run_id`, `dataset_id`, `agent_version`, `model`, `started_at`, `seed`
2. `event`
   - `idx`, `ts`, `actor`, `type`, `input`, `output`, `tool`, `error`, `latency_ms`
3. `judge_result`
   - `judge_id`, `case_id`, `score`, `passed`, `reason`, `evidence_refs`
4. `aggregate_result`
   - `pass_rate`, `hard_fail_rate`, `regression_delta`, `gate_status`

Contract priorities:

- Backward compatibility for schema revisions.
- Deterministic replay when config and artifacts are pinned.
- Explicit failure taxonomy (timeouts, contract violations, policy failures, parse/type errors where applicable).

## Evidence Pack Output

Each run writes a local evidence pack:

```text
evidence_pack/
  manifest.json
  run/
    config.json
    summary.json
    events.jsonl
  judges/
    tool_contract.json
    policy.json
    regex.json
    json_schema.json
    lean.json          # optional
  compare/
    baseline_delta.json
    gate_decision.json
  cases/
    <case_id>/
      trajectory.json
      verdicts.json
      artifacts/
```

## Repository Direction

This repository is the open foundation:

- stable contracts
- deterministic eval primitives
- local-first evidence portability

Enterprise packaging is intentionally out-of-repo.

## Lean Adapter Contract (Optional)

`LeanJudge` is independent from any specific prover API. Configure a command in judge config:

```json
{
  "lean": {
    "command": ["my-lean-checker", "--json-stdin"]
  }
}
```

Contract:

- Input on stdin: JSON `lean_payload` from each case metadata.
- Output on stdout: JSON object with at least `passed` (bool), optional `reason`, `evidence`.

## Quickstart

```bash
python -m pip install -e .
agent-eval init --out .
agent-eval run --suite examples/suite_good.json --out runs/baseline --run-id baseline-1
agent-eval run --suite examples/suite_bad.json --out runs/candidate --run-id candidate-1
agent-eval compare --baseline runs/baseline --candidate runs/candidate --out runs/candidate/compare/baseline_delta.json
agent-eval gate --compare runs/candidate/compare/baseline_delta.json --min-pass-rate 0.95 --max-hard-fail-increase 0.00
```

CI usage: `agent-eval gate` returns exit code `0` on pass and `1` on gate failure.

`agent-eval compare` includes aggregate deltas and per-case regression details (`case_regressions`) when run artifacts are available.
It also emits richer report sections: `overview`, `top_regressed_judges`, and ranked `failure_clusters`.

## Dataset + Baseline Registry

Use the local registry to track datasets and named baselines:

```bash
agent-eval registry dataset-add --suite suites/starter_suite.json --dataset-id starter-suite
agent-eval registry baseline-set --name main --run runs/baseline
agent-eval compare --baseline main --candidate runs/candidate
```

Registry default path: `.agent_eval/registry.json` (override with `--registry-path`).
By default, `compare` enforces baseline/candidate compatibility (dataset and case checks). Use `--allow-incompatible` to bypass.

## Propose/Execute/Repair Loop

`run-loop` executes iterative agent attempts with deterministic scoring on each iteration.

```bash
agent-eval run-loop \
  --suite suites/starter_suite.json \
  --out runs/loop \
  --propose-command "python my_agent_adapter.py" \
  --max-repairs 2
```

Adapter command contract:

- Reads JSON payload from stdin (`mode`, `case_id`, `input`, `expected_output`, `attempt`, `previous_attempts`, contracts/policy).
- Writes JSON to stdout:
  - `assistant_output`
  - `tool_calls` as `[{ "tool": "...", "arguments": {...} }]`

Tool execution is deterministic from per-case `metadata.tool_responses`.

## Replay + Environment Pinning

Every run records pinned environment metadata in `run/config.json`.

Replay verifies:

- summary parity against saved artifacts
- per-case verdict parity
- pinned environment compatibility

```bash
agent-eval replay --run runs/candidate --out runs/candidate/compare/replay_report.json
```

`agent-eval replay` returns exit code `0` on full replay match and `1` otherwise.

For propose/execute/repair runs, execution replay re-runs adapter commands and checks
trajectory/verdict parity:

```bash
agent-eval replay-exec --run runs/loop --out runs/loop/compare/replay_exec_report.json
```

`agent-eval replay-exec` returns exit code `0` only when execution replay fully matches.

## Trace Import Adapters

Use `import-trace` to normalize external exports into this repo's trace schema:

```bash
agent-eval import-trace --provider auto --input exports/provider_dump.json --out suites/imported.json --dataset-id imported-suite
```

Supported providers:

- `auto` (detect format per record)
- `openai`
- `anthropic`
- `vertex`
- `foundry`

Imported events are enriched with OTel-style trace/span identifiers and GenAI attributes.
Use `--strict` to fail on unknown top-level provider fields or empty parsed traces.

Adapter conformance tests are included under `tests/fixtures/adapters/` and `tests/test_adapter_conformance.py`.

Run strict conformance checks:

```bash
agent-eval adapter-conformance --fixtures-dir tests/fixtures/adapters --min-fixtures-per-provider 2
```

## OpenTelemetry Export

Export any run to OpenTelemetry-style GenAI JSONL:

```bash
agent-eval export-otel --run runs/candidate --out runs/candidate/otel_events.jsonl
```

## Structured Errors

Runtime failures return machine-readable JSON on stderr:

```json
{"error":{"code":"validation_error","message":"...","details":{...}}}
```

## Schema Governance + Contracts

Validate suites:

```bash
agent-eval schema validate --input suites/starter_suite.json --strict --require-version 1.0.0
```

Migrate legacy suites:

```bash
agent-eval schema migrate --input legacy_suite.json --output suites/migrated_suite.json
```

Run combined schema back-compat + adapter checks:

```bash
agent-eval contracts-check \
  --schema-fixtures-dir tests/fixtures/schema_backcompat \
  --adapter-fixtures-dir tests/fixtures/adapters \
  --min-fixtures-per-provider 2
```

## Markdown Reports

Generate a human-readable report from compare/gate/replay artifacts:

```bash
agent-eval report markdown \
  --compare runs/candidate/compare/baseline_delta.json \
  --gate runs/candidate/compare/gate_decision.json \
  --replay runs/candidate/compare/replay_report.json \
  --out runs/candidate/compare/report.md \
  --title "Release Eval Report"
```

## Local Release + Packaging

No hosted CI integration is required for packaging:

```bash
./scripts/check_contracts.sh
./scripts/release_local.sh
docker build -t agent-eval-suite:0.1.1 .
```
