from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_eval_suite.importers import import_to_suite
from agent_eval_suite.schema_governance import validate_suite_payload

PROVIDER_NAMES = ("openai", "anthropic", "vertex", "foundry")


def _provider_from_filename(path: Path) -> str | None:
    stem = path.stem.lower()
    for provider in PROVIDER_NAMES:
        if stem.startswith(provider):
            return provider
    return None


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"fixture {path} must be a JSON object")
    return payload


def run_adapter_conformance(
    fixtures_dir: str | Path,
    *,
    min_fixtures_per_provider: int = 1,
    strict_import: bool = True,
) -> dict[str, Any]:
    root = Path(fixtures_dir)
    if not root.exists():
        raise FileNotFoundError(f"fixtures directory not found: {root}")

    fixture_paths = sorted(root.glob("*.json"))
    provider_rows: dict[str, dict[str, Any]] = {
        provider: {
            "provider": provider,
            "fixtures_total": 0,
            "fixtures_passed": 0,
            "fixtures_failed": 0,
            "event_type_coverage": {"message": 0, "tool_call": 0, "tool_result": 0},
            "diagnostics_total": 0,
            "errors": [],
        }
        for provider in PROVIDER_NAMES
    }
    fixture_reports: list[dict[str, Any]] = []

    for fixture in fixture_paths:
        provider = _provider_from_filename(fixture)
        if provider is None:
            continue
        row = provider_rows[provider]
        row["fixtures_total"] += 1

        try:
            suite = import_to_suite(
                input_path=fixture,
                provider=provider,
                dataset_id=f"{provider}-conformance",
                case_prefix=provider,
                strict=strict_import,
            )
            validation = validate_suite_payload(
                suite, strict=True, require_version=None
            )
            if not validation["passed"]:
                raise ValueError(
                    f"schema validation failed: {', '.join(validation['errors'])}"
                )

            trace = suite["cases"][0]["trace"] if suite["cases"] else []
            event_types = {event.get("type") for event in trace if isinstance(event, dict)}
            for key in ("message", "tool_call", "tool_result"):
                if key in event_types:
                    row["event_type_coverage"][key] += 1

            diagnostics = suite.get("metadata", {}).get("import_diagnostics", [])
            if isinstance(diagnostics, list):
                row["diagnostics_total"] += len(diagnostics)
            row["fixtures_passed"] += 1
            fixture_reports.append(
                {
                    "fixture": str(fixture),
                    "provider": provider,
                    "passed": True,
                    "case_count": len(suite.get("cases", [])),
                    "diagnostics_count": len(diagnostics) if isinstance(diagnostics, list) else 0,
                }
            )
        except Exception as exc:
            row["fixtures_failed"] += 1
            row["errors"].append({"fixture": str(fixture), "error": str(exc)})
            fixture_reports.append(
                {
                    "fixture": str(fixture),
                    "provider": provider,
                    "passed": False,
                    "error": str(exc),
                }
            )

    failures: list[dict[str, Any]] = []
    for provider in PROVIDER_NAMES:
        row = provider_rows[provider]
        if row["fixtures_total"] < min_fixtures_per_provider:
            failures.append(
                {
                    "provider": provider,
                    "type": "insufficient_fixtures",
                    "required": min_fixtures_per_provider,
                    "actual": row["fixtures_total"],
                }
            )
        if row["fixtures_failed"] > 0:
            failures.append(
                {
                    "provider": provider,
                    "type": "failing_fixtures",
                    "count": row["fixtures_failed"],
                    "errors": row["errors"],
                }
            )

    passed = len(failures) == 0
    return {
        "passed": passed,
        "fixtures_dir": str(root),
        "providers": provider_rows,
        "fixture_reports": fixture_reports,
        "failures": failures,
    }
