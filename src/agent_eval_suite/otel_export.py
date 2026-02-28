from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            text = line.strip()
            if not text:
                continue
            payload = json.loads(text)
            if isinstance(payload, dict):
                rows.append(payload)
    return rows


def _fallback_trace_id(run_id: str, case_id: str) -> str:
    seed = f"{run_id}:{case_id}".encode("utf-8")
    return hashlib.sha256(seed).hexdigest()[:32]


def _fallback_span_id(run_id: str, case_id: str, idx: int) -> str:
    seed = f"{run_id}:{case_id}:{idx}".encode("utf-8")
    return hashlib.sha256(seed).hexdigest()[:16]


def export_run_to_otel(run_path: str | Path, out_path: str | Path) -> Path:
    run_dir = Path(run_path)
    run_config = _load_json(run_dir / "run" / "config.json")
    events = _read_jsonl(run_dir / "run" / "events.jsonl")

    out_rows: list[dict[str, Any]] = []
    for event in events:
        run_id = str(event.get("run_id", run_config.get("run_id", "")))
        case_id = str(event.get("case_id", ""))
        idx = int(event.get("idx", 0))
        trace_id = event.get("trace_id") or _fallback_trace_id(run_id, case_id)
        span_id = event.get("span_id") or _fallback_span_id(run_id, case_id, idx)
        parent_span_id = event.get("parent_span_id")

        attributes = dict(event.get("attributes", {}))
        attributes.update(
            {
                "gen_ai.operation.name": event.get("type"),
                "gen_ai.tool.name": event.get("tool"),
                "gen_ai.system": event.get("source_provider")
                or event.get("provider")
                or "unknown",
                "gen_ai.request.model": run_config.get("model"),
                "gen_ai.agent.name": run_config.get("agent_version"),
                "agent_eval.case_id": case_id,
                "agent_eval.run_id": run_id,
                "agent_eval.attempt": event.get("attempt"),
            }
        )

        out_rows.append(
            {
                "resource": {
                    "service.name": "agent-eval-suite",
                    "service.version": run_config.get("schema_version"),
                },
                "scope": {"name": "agent_eval_suite", "version": run_config.get("schema_version")},
                "trace_id": trace_id,
                "span_id": span_id,
                "parent_span_id": parent_span_id,
                "name": event.get("type"),
                "kind": "INTERNAL",
                "start_time": event.get("ts"),
                "end_time": event.get("ts"),
                "status": {"code": "ERROR" if event.get("error") else "OK"},
                "attributes": attributes,
                "events": [
                    {
                        "name": "agent.trace.event",
                        "attributes": {
                            "actor": event.get("actor"),
                            "input": event.get("input"),
                            "output": event.get("output"),
                            "error": event.get("error"),
                            "latency_ms": event.get("latency_ms"),
                        },
                    }
                ],
            }
        )

    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        for row in out_rows:
            handle.write(json.dumps(row, sort_keys=True))
            handle.write("\n")
    return target
