from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from agent_eval_suite.importers import load_trace_records
from agent_eval_suite.schema import TraceEvent

FRAMEWORKS = (
    "auto",
    "langgraph",
    "openai_agents",
    "autogen",
    "crewai",
    "semantic_kernel",
)


def _extract_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        if isinstance(value.get("text"), str):
            return value["text"]
        return json.dumps(value, sort_keys=True)
    if isinstance(value, list):
        chunks = [_extract_text(item) for item in value]
        return "\n".join(chunk for chunk in chunks if chunk)
    return str(value)


def _append(
    events: list[TraceEvent],
    actor: str,
    event_type: str,
    *,
    ts: str = "",
    input_payload: Any = None,
    output_payload: Any = None,
    tool: str | None = None,
    error: str | None = None,
) -> None:
    events.append(
        TraceEvent(
            idx=len(events),
            ts=ts,
            actor=actor,
            type=event_type,
            input=input_payload,
            output=output_payload,
            tool=tool,
            error=error,
        )
    )


def detect_framework(record: dict[str, Any]) -> str:
    text = json.dumps(record, sort_keys=True).lower()
    if "langgraph" in text or "on_tool_start" in text or "on_tool_end" in text:
        return "langgraph"
    if "assistantagent" in text or "autogen" in text:
        return "autogen"
    if "crewai" in text or "crew" in text and "task" in text:
        return "crewai"
    if "semantic_kernel" in text or "kernel" in text and "invocation" in text:
        return "semantic_kernel"
    if "openai_agent" in text or "response.output_text" in text:
        return "openai_agents"
    return "openai_agents"


def _parse_langgraph(record: dict[str, Any]) -> tuple[list[TraceEvent], Any]:
    events: list[TraceEvent] = []
    source_events = record.get("events", record.get("steps", []))
    if not isinstance(source_events, list):
        return events, None

    for row in source_events:
        if not isinstance(row, dict):
            continue
        event_name = str(row.get("event", row.get("type", "")))
        ts = str(row.get("ts", row.get("timestamp", "")))
        if event_name in {"on_tool_start", "tool_call"}:
            _append(
                events,
                actor="agent",
                event_type="tool_call",
                ts=ts,
                tool=row.get("tool", row.get("name")),
                input_payload=row.get("input", row.get("arguments", {})),
            )
        elif event_name in {"on_tool_end", "tool_result"}:
            _append(
                events,
                actor="tool",
                event_type="tool_result",
                ts=ts,
                tool=row.get("tool", row.get("name")),
                output_payload=row.get("output", row.get("result")),
                error=row.get("error"),
            )
        else:
            role = str(row.get("role", row.get("actor", "assistant")))
            text = _extract_text(row.get("content", row.get("output", row.get("input"))))
            if role == "user":
                _append(events, actor="user", event_type="message", ts=ts, input_payload=text)
            else:
                _append(events, actor="assistant", event_type="message", ts=ts, output_payload=text)

    first_input = next((event.input for event in events if event.actor == "user"), None)
    return events, first_input


def _parse_openai_agents(record: dict[str, Any]) -> tuple[list[TraceEvent], Any]:
    events: list[TraceEvent] = []
    source_events = record.get("events", record.get("messages", []))
    if not isinstance(source_events, list):
        return events, None

    for row in source_events:
        if not isinstance(row, dict):
            continue
        row_type = str(row.get("type", "message"))
        ts = str(row.get("ts", row.get("timestamp", "")))
        if row_type in {"tool_call", "function_call"}:
            _append(
                events,
                actor="agent",
                event_type="tool_call",
                ts=ts,
                tool=row.get("name", row.get("tool")),
                input_payload=row.get("arguments", row.get("input", {})),
            )
        elif row_type in {"tool_result", "function_result"}:
            _append(
                events,
                actor="tool",
                event_type="tool_result",
                ts=ts,
                tool=row.get("name", row.get("tool")),
                output_payload=row.get("output", row.get("result")),
                error=row.get("error"),
            )
        else:
            role = str(row.get("role", row.get("actor", "assistant")))
            content = _extract_text(row.get("content", row.get("text", row.get("output"))))
            if role == "user":
                _append(events, actor="user", event_type="message", ts=ts, input_payload=content)
            else:
                _append(
                    events,
                    actor="assistant" if role != "tool" else "tool",
                    event_type="message" if role != "tool" else "tool_result",
                    ts=ts,
                    output_payload=content,
                    tool=row.get("name"),
                )

    first_input = next((event.input for event in events if event.actor == "user"), None)
    return events, first_input


def _parse_autogen(record: dict[str, Any]) -> tuple[list[TraceEvent], Any]:
    return _parse_openai_agents(record)


def _parse_crewai(record: dict[str, Any]) -> tuple[list[TraceEvent], Any]:
    return _parse_langgraph(record)


def _parse_semantic_kernel(record: dict[str, Any]) -> tuple[list[TraceEvent], Any]:
    events: list[TraceEvent] = []
    invocations = record.get("invocations", record.get("events", []))
    if not isinstance(invocations, list):
        return events, None

    for row in invocations:
        if not isinstance(row, dict):
            continue
        ts = str(row.get("ts", row.get("timestamp", "")))
        if row.get("plugin") or row.get("function"):
            _append(
                events,
                actor="agent",
                event_type="tool_call",
                ts=ts,
                tool=str(row.get("function", row.get("plugin"))),
                input_payload=row.get("input", row.get("arguments", {})),
            )
            _append(
                events,
                actor="tool",
                event_type="tool_result",
                ts=ts,
                tool=str(row.get("function", row.get("plugin"))),
                output_payload=row.get("output", row.get("result")),
                error=row.get("error"),
            )
        else:
            text = _extract_text(row.get("content", row.get("text")))
            role = str(row.get("role", "assistant"))
            if role == "user":
                _append(events, actor="user", event_type="message", ts=ts, input_payload=text)
            else:
                _append(events, actor="assistant", event_type="message", ts=ts, output_payload=text)

    first_input = next((event.input for event in events if event.actor == "user"), None)
    return events, first_input


PARSERS = {
    "langgraph": _parse_langgraph,
    "openai_agents": _parse_openai_agents,
    "autogen": _parse_autogen,
    "crewai": _parse_crewai,
    "semantic_kernel": _parse_semantic_kernel,
}


def import_framework_to_suite(
    input_path: str | Path,
    framework: str,
    dataset_id: str,
    case_prefix: str = "case",
    strict: bool = False,
) -> dict[str, Any]:
    if framework not in FRAMEWORKS:
        raise ValueError(
            f"unsupported framework '{framework}'. supported: {', '.join(FRAMEWORKS)}"
        )

    records = load_trace_records(input_path)
    cases: list[dict[str, Any]] = []
    framework_counts: dict[str, int] = {}
    diagnostics: list[dict[str, Any]] = []

    for index, record in enumerate(records, start=1):
        resolved_framework = framework if framework != "auto" else detect_framework(record)
        parser = PARSERS[resolved_framework]
        events, case_input = parser(record)

        if not events:
            diagnostics.append(
                {
                    "record_index": index,
                    "framework": resolved_framework,
                    "type": "empty_trace",
                    "detail": "record parsed with zero events and was dropped",
                }
            )
            if strict:
                raise ValueError(
                    f"record {index} for framework {resolved_framework} produced empty trace"
                )
            continue

        trace_id = uuid.uuid4().hex
        for event_index, event in enumerate(events):
            event.trace_id = event.trace_id or trace_id
            event.span_id = event.span_id or f"{event_index + 1:016x}"
            if event.parent_span_id is None and event_index > 0:
                event.parent_span_id = f"{event_index:016x}"
            attrs = dict(event.attributes)
            attrs.setdefault("gen_ai.framework", resolved_framework)
            attrs.setdefault("gen_ai.operation.name", event.type)
            if event.tool:
                attrs.setdefault("gen_ai.tool.name", event.tool)
            event.attributes = attrs

        framework_counts[resolved_framework] = framework_counts.get(resolved_framework, 0) + 1
        cases.append(
            {
                "case_id": f"{case_prefix}-{index}",
                "input": case_input,
                "trace": [event.to_dict() for event in events],
                "metadata": {
                    "source_framework": resolved_framework,
                    "source_index": index,
                },
            }
        )

    return {
        "dataset_id": dataset_id,
        "cases": cases,
        "metadata": {
            "import_source": str(input_path),
            "selected_framework": framework,
            "framework_case_counts": framework_counts,
            "imported_records": len(cases),
            "total_records": len(records),
            "dropped_records": len(records) - len(cases),
            "import_diagnostics": diagnostics,
        },
    }
