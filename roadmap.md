# Agent Eval Suite Roadmap

Date: February 28, 2026

This roadmap focuses on the OSS core in this repository and keeps paid/private items out of scope.

## Guiding Principles

1. Keep the trace schema opinionated and stable.
2. Prefer deterministic judges for release-critical paths.
3. Make every gate decision evidence-backed and locally reproducible.
4. Treat replay compatibility as a first-class contract.

## Phase 0: Foundation (Weeks 1-2)

Goal: lock contracts and runnable skeleton.

- Finalize `trace` and `replay` schema v0.
- Define judge plugin interface and judge result contract.
- Define local evidence pack folder layout and manifest format.
- Add basic CLI skeleton for `run`, `compare`, and `gate`.

Exit criteria:

- Schema v0 documented.
- Example traces replay successfully.
- Plugin interface used by at least one deterministic judge.

## Phase 1: Deterministic MVP (Weeks 3-6)

Goal: deliver a useful offline evaluator.

- Implement offline eval runner for datasets and trace inputs.
- Implement baseline-vs-candidate compare.
- Implement CI gate exit codes.
- Ship deterministic judges:
  - `ToolContractJudge`
  - `PolicyJudge`
  - `RegexJudge`
  - `JSONSchemaJudge`
- Emit JSON summary and full evidence pack artifacts.

Exit criteria:

- Candidate runs can be compared to a pinned baseline.
- CI can block on configured regression thresholds.
- Evidence packs are complete enough for manual audit/review.

## Phase 2: Lean Integration Plugin (Weeks 7-8)

Goal: add optional formal correctness scoring without coupling OSS core to any vendor/prover API.

- Add `LeanJudge` adapter contract around an external checker command.
- Keep core runner usable when `LeanJudge` is not installed.
- Add compatibility tests for plugin discovery and failure isolation.

Exit criteria:

- `LeanJudge` can be enabled/disabled via config.
- Core runner behavior remains stable without the plugin.

## Phase 3: Hardening and Contract Stability (Weeks 9-12)

Goal: make the OSS core reliable for wider adoption.

- Add schema versioning and migration policy.
- Add replay determinism checks and golden trace fixtures.
- Add backward-compatibility tests for evidence pack manifests.
- Add failure taxonomy reports and top-regression summaries.

Exit criteria:

- Contract changes require explicit version bump and migration notes.
- Deterministic replay tests pass on golden fixtures.

## Phase 4: Integration Surface (Weeks 13-16)

Goal: improve portability and ecosystem fit while staying local-first.

- Add import adapters for common trace/eval formats (where feasible).
- Add docs/examples for CI integration patterns.
- Add templates for judge policy configs and threshold gates.

Exit criteria:

- External traces can be normalized to schema v0+.
- Teams can onboard with documented CI examples and sample policies.

## Out of Scope for This OSS Repo

1. Private benchmark packs and holdouts.
2. Customer-specific policy packs.
3. Hosted storage/dashboard features and enterprise access controls (RBAC/SSO).

These remain paid/private by design.
