from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_REGISTRY_PATH = ".agent_eval/registry.json"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


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


def _normalize_registry(payload: dict[str, Any]) -> dict[str, Any]:
    datasets = payload.get("datasets", {})
    baselines = payload.get("baselines", {})
    if not isinstance(datasets, dict):
        datasets = {}
    if not isinstance(baselines, dict):
        baselines = {}
    return {"version": "0.1.0", "datasets": datasets, "baselines": baselines}


def load_registry(path: str | Path = DEFAULT_REGISTRY_PATH) -> dict[str, Any]:
    registry_path = Path(path)
    if not registry_path.exists():
        return {"version": "0.1.0", "datasets": {}, "baselines": {}}
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
    save_registry(registry, path)
    return entry


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
