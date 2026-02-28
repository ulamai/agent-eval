from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_REGISTRY_PATH = ".agent_eval/registry.json"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"registry file {path} is not a JSON object")
    return payload


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _ensure_parent(path)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(65536)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _append_audit(registry: dict[str, Any], action: str, details: dict[str, Any]) -> None:
    log = registry.get("audit_log")
    if not isinstance(log, list):
        log = []
    log.append({"at": _utc_now(), "action": action, "details": details})
    registry["audit_log"] = log[-500:]


def _normalize_registry(payload: dict[str, Any]) -> dict[str, Any]:
    datasets = payload.get("datasets", {})
    baselines = payload.get("baselines", {})
    waivers = payload.get("waivers", [])
    approvals = payload.get("approvals", {})
    audit_log = payload.get("audit_log", [])
    if not isinstance(datasets, dict):
        datasets = {}
    if not isinstance(baselines, dict):
        baselines = {}
    if not isinstance(waivers, list):
        waivers = []
    if not isinstance(approvals, dict):
        approvals = {}
    if not isinstance(audit_log, list):
        audit_log = []
    return {
        "version": "0.2.0",
        "datasets": datasets,
        "baselines": baselines,
        "waivers": waivers,
        "approvals": approvals,
        "audit_log": audit_log,
    }


def load_registry(path: str | Path = DEFAULT_REGISTRY_PATH) -> dict[str, Any]:
    registry_path = Path(path)
    if not registry_path.exists():
        return {
            "version": "0.2.0",
            "datasets": {},
            "baselines": {},
            "waivers": [],
            "approvals": {},
            "audit_log": [],
        }
    return _normalize_registry(_load_json(registry_path))


def save_registry(payload: dict[str, Any], path: str | Path = DEFAULT_REGISTRY_PATH) -> Path:
    registry_path = Path(path)
    normalized = _normalize_registry(payload)
    _write_json(registry_path, normalized)
    return registry_path


def register_dataset(
    suite_path: str | Path,
    dataset_id: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    path: str | Path = DEFAULT_REGISTRY_PATH,
) -> dict[str, Any]:
    suite_file = Path(suite_path)
    payload = _load_json(suite_file)
    resolved_dataset_id = dataset_id or str(payload.get("dataset_id", "dataset-unknown"))
    cases = payload.get("cases", [])
    case_count = len(cases) if isinstance(cases, list) else 0

    registry = load_registry(path)
    entry = {
        "dataset_id": resolved_dataset_id,
        "suite_path": str(suite_file.resolve()),
        "description": description or "",
        "tags": sorted(set(tags or [])),
        "registered_at": _utc_now(),
        "case_count": case_count,
        "checksum_sha256": _checksum(suite_file),
    }
    registry["datasets"][resolved_dataset_id] = entry
    _append_audit(
        registry,
        "dataset.register",
        {"dataset_id": resolved_dataset_id, "suite_path": entry["suite_path"]},
    )
    save_registry(registry, path)
    return entry


def list_datasets(path: str | Path = DEFAULT_REGISTRY_PATH) -> list[dict[str, Any]]:
    registry = load_registry(path)
    rows = []
    for dataset_id, entry in sorted(registry["datasets"].items()):
        row = {"dataset_id": dataset_id}
        if isinstance(entry, dict):
            row.update(entry)
        rows.append(row)
    return rows


def _load_run_summary(run_path: Path) -> dict[str, Any]:
    summary_path = run_path / "run" / "summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(
            f"summary not found at {summary_path}; expected evidence pack directory"
        )
    return _load_json(summary_path)


def set_baseline(
    name: str,
    run_path: str | Path,
    dataset_id: str | None = None,
    notes: str | None = None,
    path: str | Path = DEFAULT_REGISTRY_PATH,
) -> dict[str, Any]:
    run_dir = Path(run_path).resolve()
    summary = _load_run_summary(run_dir)
    resolved_dataset_id = dataset_id or str(summary.get("dataset_id", "dataset-unknown"))
    entry = {
        "name": name,
        "run_path": str(run_dir),
        "dataset_id": resolved_dataset_id,
        "run_id": summary.get("run_id"),
        "summary_path": str((run_dir / "run" / "summary.json")),
        "notes": notes or "",
        "set_at": _utc_now(),
    }

    registry = load_registry(path)
    registry["baselines"][name] = entry
    _append_audit(
        registry,
        "baseline.set",
        {
            "name": name,
            "run_id": entry.get("run_id"),
            "dataset_id": entry.get("dataset_id"),
        },
    )
    save_registry(registry, path)
    return entry


def promote_baseline(
    *,
    name: str,
    run_path: str | Path,
    approved_by: str,
    rationale: str,
    dataset_id: str | None = None,
    notes: str | None = None,
    path: str | Path = DEFAULT_REGISTRY_PATH,
) -> dict[str, Any]:
    baseline = set_baseline(
        name=name,
        run_path=run_path,
        dataset_id=dataset_id,
        notes=notes,
        path=path,
    )

    registry = load_registry(path)
    approvals = registry.get("approvals")
    if not isinstance(approvals, dict):
        approvals = {}
    rows = approvals.get(name)
    if not isinstance(rows, list):
        rows = []

    approval = {
        "approval_id": str(uuid.uuid4()),
        "name": name,
        "run_id": baseline.get("run_id"),
        "approved_by": approved_by,
        "rationale": rationale,
        "approved_at": _utc_now(),
    }
    rows.append(approval)
    approvals[name] = rows[-100:]
    registry["approvals"] = approvals
    _append_audit(
        registry,
        "baseline.promote",
        {
            "name": name,
            "run_id": baseline.get("run_id"),
            "approved_by": approved_by,
        },
    )
    save_registry(registry, path)
    return {"baseline": baseline, "approval": approval}


def list_approvals(
    name: str | None = None, path: str | Path = DEFAULT_REGISTRY_PATH
) -> list[dict[str, Any]]:
    registry = load_registry(path)
    approvals = registry.get("approvals", {})
    if not isinstance(approvals, dict):
        return []

    rows: list[dict[str, Any]] = []
    names = [name] if name else sorted(approvals.keys())
    for baseline_name in names:
        values = approvals.get(baseline_name)
        if not isinstance(values, list):
            continue
        for row in values:
            if isinstance(row, dict):
                rows.append(row)
    rows.sort(key=lambda row: str(row.get("approved_at", "")), reverse=True)
    return rows


def add_waiver(
    *,
    baseline_name: str,
    reason: str,
    approved_by: str,
    case_id: str | None = None,
    judge_id: str | None = None,
    regression_key: str | None = None,
    expires_at: str | None = None,
    path: str | Path = DEFAULT_REGISTRY_PATH,
) -> dict[str, Any]:
    waiver = {
        "waiver_id": str(uuid.uuid4()),
        "baseline_name": baseline_name,
        "case_id": case_id,
        "judge_id": judge_id,
        "regression_key": regression_key,
        "reason": reason,
        "approved_by": approved_by,
        "created_at": _utc_now(),
        "expires_at": expires_at,
    }

    registry = load_registry(path)
    waivers = registry.get("waivers")
    if not isinstance(waivers, list):
        waivers = []
    waivers.append(waiver)
    registry["waivers"] = waivers[-2000:]
    _append_audit(
        registry,
        "waiver.add",
        {
            "waiver_id": waiver["waiver_id"],
            "baseline_name": baseline_name,
            "case_id": case_id,
            "judge_id": judge_id,
            "expires_at": expires_at,
        },
    )
    save_registry(registry, path)
    return waiver


def list_waivers(
    *,
    baseline_name: str | None = None,
    active_only: bool = False,
    as_of: str | None = None,
    path: str | Path = DEFAULT_REGISTRY_PATH,
) -> list[dict[str, Any]]:
    registry = load_registry(path)
    waivers = registry.get("waivers", [])
    if not isinstance(waivers, list):
        return []

    now = _parse_iso(as_of) if as_of else datetime.now(UTC)
    rows: list[dict[str, Any]] = []
    for item in waivers:
        if not isinstance(item, dict):
            continue
        if baseline_name and item.get("baseline_name") != baseline_name:
            continue
        expiry = _parse_iso(item.get("expires_at"))
        is_active = expiry is None or expiry > now
        row = dict(item)
        row["active"] = is_active
        if active_only and not is_active:
            continue
        rows.append(row)
    rows.sort(key=lambda row: str(row.get("created_at", "")), reverse=True)
    return rows


def get_active_waivers_for_baseline(
    baseline_name: str, path: str | Path = DEFAULT_REGISTRY_PATH
) -> list[dict[str, Any]]:
    return list_waivers(
        baseline_name=baseline_name,
        active_only=True,
        path=path,
    )


def list_audit_log(
    path: str | Path = DEFAULT_REGISTRY_PATH, limit: int = 100
) -> list[dict[str, Any]]:
    registry = load_registry(path)
    rows = registry.get("audit_log", [])
    if not isinstance(rows, list):
        return []
    result = [row for row in rows if isinstance(row, dict)]
    result.sort(key=lambda row: str(row.get("at", "")), reverse=True)
    return result[: max(1, limit)]


def get_baseline(name: str, path: str | Path = DEFAULT_REGISTRY_PATH) -> dict[str, Any] | None:
    registry = load_registry(path)
    baseline = registry["baselines"].get(name)
    if isinstance(baseline, dict):
        return baseline
    return None


def list_baselines(path: str | Path = DEFAULT_REGISTRY_PATH) -> list[dict[str, Any]]:
    registry = load_registry(path)
    rows = []
    for name, entry in sorted(registry["baselines"].items()):
        row = {"name": name}
        if isinstance(entry, dict):
            row.update(entry)
        rows.append(row)
    return rows


def resolve_baseline_reference(
    reference: str, path: str | Path = DEFAULT_REGISTRY_PATH
) -> tuple[str, dict[str, Any] | None]:
    reference_path = Path(reference)
    if reference_path.exists():
        return str(reference_path), None

    baseline = get_baseline(reference, path=path)
    if baseline and isinstance(baseline.get("run_path"), str):
        return str(baseline["run_path"]), baseline
    raise FileNotFoundError(
        f"baseline reference '{reference}' is neither an existing path nor a registered baseline name"
    )
