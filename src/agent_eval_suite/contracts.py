from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_eval_suite.adapter_conformance import run_adapter_conformance
from agent_eval_suite.schema_governance import (
    LATEST_SCHEMA_VERSION,
    migrate_suite_payload,
    validate_suite_payload,
)


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"fixture {path} must be a JSON object")
    return payload


def run_schema_backcompat_checks(fixtures_dir: str | Path) -> dict[str, Any]:
    root = Path(fixtures_dir)
    if not root.exists():
        raise FileNotFoundError(f"schema fixtures directory not found: {root}")

    fixture_reports: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for fixture in sorted(root.glob("*.json")):
        try:
            payload = _load_json(fixture)
            migrated = migrate_suite_payload(payload, target_version=LATEST_SCHEMA_VERSION)
            validation = validate_suite_payload(
                migrated, strict=True, require_version=LATEST_SCHEMA_VERSION
            )
            if not validation["passed"]:
                failures.append(
                    {
                        "fixture": str(fixture),
                        "type": "validation_failed",
                        "errors": validation["errors"],
                    }
                )
                fixture_reports.append(
                    {
                        "fixture": str(fixture),
                        "passed": False,
                        "errors": validation["errors"],
                    }
                )
            else:
                fixture_reports.append({"fixture": str(fixture), "passed": True})
        except Exception as exc:
            failures.append(
                {"fixture": str(fixture), "type": "exception", "error": str(exc)}
            )
            fixture_reports.append(
                {"fixture": str(fixture), "passed": False, "error": str(exc)}
            )

    return {
        "passed": len(failures) == 0,
        "fixtures_dir": str(root),
        "fixture_reports": fixture_reports,
        "failures": failures,
    }


def run_contract_checks(
    *,
    schema_fixtures_dir: str | Path,
    adapter_fixtures_dir: str | Path,
    min_fixtures_per_provider: int = 1,
) -> dict[str, Any]:
    schema_report = run_schema_backcompat_checks(schema_fixtures_dir)
    adapter_report = run_adapter_conformance(
        adapter_fixtures_dir,
        min_fixtures_per_provider=min_fixtures_per_provider,
        strict_import=True,
    )
    passed = schema_report["passed"] and adapter_report["passed"]
    failures: list[dict[str, Any]] = []
    if not schema_report["passed"]:
        failures.append({"type": "schema_backcompat", "report": schema_report})
    if not adapter_report["passed"]:
        failures.append({"type": "adapter_conformance", "report": adapter_report})

    return {
        "passed": passed,
        "schema_backcompat": schema_report,
        "adapter_conformance": adapter_report,
        "failures": failures,
    }
