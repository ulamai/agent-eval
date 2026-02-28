from __future__ import annotations

import json
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

LATEST_SCHEMA_VERSION = "1.0.0"
SUPPORTED_SCHEMA_VERSIONS = {"0.1.0", "1.0.0"}

SUITE_ALLOWED_KEYS = {"dataset_id", "cases", "metadata"}
CASE_ALLOWED_KEYS = {
    "case_id",
    "input",
    "expected_output",
    "expected",
    "trace",
    "tool_contracts",
    "policy",
    "regex_patterns",
    "regex",
    "json_schema",
    "metadata",
}

TRACE_ALLOWED_KEYS = {
    "idx",
    "ts",
    "actor",
    "type",
    "input",
    "output",
    "tool",
    "error",
    "latency_ms",
    "trace_id",
    "span_id",
    "parent_span_id",
    "attributes",
    "attempt",
}


def _load_json(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"payload in {path} must be a JSON object")
    return payload


def _write_json(path: str | Path, payload: dict[str, Any]) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return target


def _normalize_trace(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    trace_id = uuid.uuid4().hex
    normalized: list[dict[str, Any]] = []
    for index, raw_event in enumerate(trace):
        event = dict(raw_event)
        event["idx"] = int(event.get("idx", index))
        event["ts"] = str(event.get("ts", ""))
        event["actor"] = str(event.get("actor", ""))
        event["type"] = str(event.get("type", ""))
        if "attributes" not in event or not isinstance(event.get("attributes"), dict):
            event["attributes"] = {}
        if not event.get("trace_id"):
            event["trace_id"] = trace_id
        if not event.get("span_id"):
            event["span_id"] = f"{index + 1:016x}"
        if event.get("parent_span_id") is None and index > 0:
            event["parent_span_id"] = f"{index:016x}"
        normalized.append(event)
    return normalized


def _normalize_case(raw_case: dict[str, Any]) -> dict[str, Any]:
    case = dict(raw_case)
    if "expected_output" not in case and "expected" in case:
        case["expected_output"] = case.get("expected")
    if "regex_patterns" not in case and "regex" in case:
        case["regex_patterns"] = case.get("regex")

    contracts = case.get("tool_contracts", {})
    if isinstance(contracts, dict):
        normalized_contracts: dict[str, Any] = {}
        for tool_name, contract in contracts.items():
            if not isinstance(contract, dict):
                continue
            normalized_contracts[tool_name] = {
                "required_args": list(
                    contract.get("required_args", contract.get("required", []))
                ),
                "forbidden_args": list(
                    contract.get("forbidden_args", contract.get("forbidden", []))
                ),
            }
        case["tool_contracts"] = normalized_contracts
    else:
        case["tool_contracts"] = {}

    policy = case.get("policy", {})
    if not isinstance(policy, dict):
        policy = {}
    case["policy"] = {
        "forbidden_tools": list(policy.get("forbidden_tools", [])),
        "required_tools": list(policy.get("required_tools", [])),
    }

    trace = case.get("trace", [])
    if isinstance(trace, list):
        dict_trace = [item for item in trace if isinstance(item, dict)]
    else:
        dict_trace = []
    case["trace"] = _normalize_trace(dict_trace)

    if "metadata" not in case or not isinstance(case.get("metadata"), dict):
        case["metadata"] = {}

    case["case_id"] = str(case.get("case_id", ""))
    return case


def migrate_suite_payload(
    payload: dict[str, Any], target_version: str = LATEST_SCHEMA_VERSION
) -> dict[str, Any]:
    if target_version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError(
            f"unsupported target schema version '{target_version}'. "
            f"supported: {', '.join(sorted(SUPPORTED_SCHEMA_VERSIONS))}"
        )
    migrated = deepcopy(payload)
    migrated["dataset_id"] = str(migrated.get("dataset_id", "dataset-unknown"))
    cases = migrated.get("cases", [])
    if not isinstance(cases, list):
        cases = []
    migrated["cases"] = [
        _normalize_case(case) for case in cases if isinstance(case, dict)
    ]
    metadata = migrated.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    metadata["schema_version"] = target_version
    migrated["metadata"] = metadata
    return migrated


def validate_suite_payload(
    payload: dict[str, Any],
    *,
    strict: bool = False,
    require_version: str | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    dataset_id = payload.get("dataset_id")
    if not isinstance(dataset_id, str) or not dataset_id:
        errors.append("dataset_id must be a non-empty string")

    if strict:
        unknown_suite_keys = sorted(set(payload.keys()) - SUITE_ALLOWED_KEYS)
        if unknown_suite_keys:
            errors.append(f"suite has unknown keys: {', '.join(unknown_suite_keys)}")

    metadata = payload.get("metadata", {})
    if not isinstance(metadata, dict):
        errors.append("metadata must be an object")
        metadata = {}
    schema_version = metadata.get("schema_version")
    if schema_version is None:
        warnings.append("metadata.schema_version missing")
    elif schema_version not in SUPPORTED_SCHEMA_VERSIONS:
        errors.append(
            f"metadata.schema_version '{schema_version}' is unsupported "
            f"(supported: {', '.join(sorted(SUPPORTED_SCHEMA_VERSIONS))})"
        )
    if require_version and schema_version != require_version:
        errors.append(
            f"metadata.schema_version must be '{require_version}', got '{schema_version}'"
        )

    cases = payload.get("cases")
    if not isinstance(cases, list):
        errors.append("cases must be an array")
        cases = []

    for case_index, case in enumerate(cases):
        if not isinstance(case, dict):
            errors.append(f"cases[{case_index}] must be an object")
            continue

        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            errors.append(f"cases[{case_index}].case_id must be a non-empty string")

        if strict:
            unknown_case_keys = sorted(set(case.keys()) - CASE_ALLOWED_KEYS)
            if unknown_case_keys:
                errors.append(
                    f"cases[{case_index}] has unknown keys: {', '.join(unknown_case_keys)}"
                )

        trace = case.get("trace", [])
        if not isinstance(trace, list):
            errors.append(f"cases[{case_index}].trace must be an array")
            continue
        for event_index, event in enumerate(trace):
            if not isinstance(event, dict):
                errors.append(
                    f"cases[{case_index}].trace[{event_index}] must be an object"
                )
                continue
            if strict:
                unknown_event_keys = sorted(set(event.keys()) - TRACE_ALLOWED_KEYS)
                if unknown_event_keys:
                    errors.append(
                        "cases[{0}].trace[{1}] has unknown keys: {2}".format(
                            case_index, event_index, ", ".join(unknown_event_keys)
                        )
                    )

            for required in ("idx", "actor", "type"):
                if required not in event:
                    errors.append(
                        f"cases[{case_index}].trace[{event_index}] missing required key '{required}'"
                    )
            if "trace_id" in event and not isinstance(event.get("trace_id"), str):
                errors.append(
                    f"cases[{case_index}].trace[{event_index}].trace_id must be a string"
                )
            if "span_id" in event and not isinstance(event.get("span_id"), str):
                errors.append(
                    f"cases[{case_index}].trace[{event_index}].span_id must be a string"
                )
            if "attributes" in event and not isinstance(event.get("attributes"), dict):
                errors.append(
                    f"cases[{case_index}].trace[{event_index}].attributes must be an object"
                )

    return {
        "passed": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "schema_version": schema_version,
    }


def validate_suite_file(
    input_path: str | Path,
    *,
    strict: bool = False,
    require_version: str | None = None,
) -> dict[str, Any]:
    payload = _load_json(input_path)
    report = validate_suite_payload(
        payload, strict=strict, require_version=require_version
    )
    report["input"] = str(input_path)
    return report


def migrate_suite_file(
    input_path: str | Path,
    output_path: str | Path,
    target_version: str = LATEST_SCHEMA_VERSION,
) -> dict[str, Any]:
    payload = _load_json(input_path)
    migrated = migrate_suite_payload(payload, target_version=target_version)
    _write_json(output_path, migrated)
    report = validate_suite_payload(
        migrated, strict=True, require_version=target_version
    )
    return {
        "input": str(input_path),
        "output": str(output_path),
        "target_version": target_version,
        "validation": report,
    }
