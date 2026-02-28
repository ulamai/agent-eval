from __future__ import annotations

from datetime import datetime

from agent_eval_suite.schema import TraceEvent


def _is_hex(value: str, length: int) -> bool:
    if len(value) != length:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def validate_trace(trace: list[TraceEvent]) -> list[str]:
    issues: list[str] = []
    expected_idx = 0
    seen_span_ids: set[str] = set()

    for event in trace:
        if event.idx != expected_idx:
            issues.append(
                f"event idx mismatch: expected {expected_idx}, received {event.idx}"
            )
            expected_idx = event.idx + 1
        else:
            expected_idx += 1

        if not event.actor:
            issues.append(f"event {event.idx}: actor is required")
        if not event.type:
            issues.append(f"event {event.idx}: type is required")
        if event.type == "tool_call" and not event.tool:
            issues.append(f"event {event.idx}: tool_call missing tool name")
        if event.latency_ms is not None and event.latency_ms < 0:
            issues.append(f"event {event.idx}: latency_ms must be >= 0")

        if event.trace_id and not _is_hex(event.trace_id, 32):
            issues.append(f"event {event.idx}: trace_id must be 32 hex chars")
        if event.span_id:
            if not _is_hex(event.span_id, 16):
                issues.append(f"event {event.idx}: span_id must be 16 hex chars")
            elif event.span_id in seen_span_ids:
                issues.append(f"event {event.idx}: duplicate span_id {event.span_id}")
            seen_span_ids.add(event.span_id)
        if event.parent_span_id and not _is_hex(event.parent_span_id, 16):
            issues.append(f"event {event.idx}: parent_span_id must be 16 hex chars")

        if event.ts:
            try:
                datetime.fromisoformat(event.ts.replace("Z", "+00:00"))
            except ValueError:
                issues.append(f"event {event.idx}: ts is not ISO-8601")

    return issues
