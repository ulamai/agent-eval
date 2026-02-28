from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Callable

from agent_eval_suite.schema import TraceEvent

PROVIDERS = ("auto", "openai", "anthropic", "vertex", "foundry")

KNOWN_TOP_LEVEL_KEYS: dict[str, set[str]] = {
    "openai": {
        "id",
        "object",
        "created",
        "model",
        "messages",
        "response",
        "output",
        "events",
        "metadata",
        "system",
        "input",
        "tool_choice",
        "tools",
        "temperature",
    },
    "anthropic": {
        "id",
        "type",
        "role",
        "model",
        "content",
        "messages",
        "input",
        "usage",
        "stop_reason",
        "metadata",
        "anthropic_version",
        "system",
        "tools",
    },
    "vertex": {
        "contents",
        "candidates",
        "predictions",
        "metadata",
        "model",
        "safetySettings",
        "generationConfig",
    },
    "foundry": {
        "steps",
        "messages",
        "events",
        "response",
        "output",
        "metadata",
        "model",
        "azureml",
        "trace",
    },
}


def _safe_json_loads(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return value
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return value
    return value


def _extract_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if isinstance(item, str):
                chunks.append(item)
                continue
            if isinstance(item, dict):
                if isinstance(item.get("text"), str):
                    chunks.append(item["text"])
                elif isinstance(item.get("content"), str):
                    chunks.append(item["content"])
                elif isinstance(item.get("value"), str):
                    chunks.append(item["value"])
        return "\n".join(chunk for chunk in chunks if chunk)
    if isinstance(content, dict):
        if isinstance(content.get("text"), str):
            return content["text"]
        return json.dumps(content, sort_keys=True)
    return str(content)


def _extract_ts(record: dict[str, Any]) -> str:
    for key in ("ts", "timestamp", "time", "created_at"):
        value = record.get(key)
        if value is not None:
            return str(value)
    return ""


def _append_event(
    events: list[TraceEvent],
    actor: str,
    event_type: str,
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


def _to_actor(role: str) -> str:
    if role in {"user", "assistant", "tool", "system", "agent"}:
        return role
    return "agent"


def _extract_first_user_input(events: list[TraceEvent]) -> Any:
    for event in events:
        if event.actor == "user" and event.input is not None:
            return event.input
    return None


def _parse_openai_messages(messages: list[dict[str, Any]]) -> list[TraceEvent]:
    events: list[TraceEvent] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        ts = _extract_ts(message)
        role = str(message.get("role", "assistant"))
        actor = _to_actor(role)
        content = _extract_text(message.get("content"))
        if content:
            if actor == "user":
                _append_event(
                    events,
                    actor="user",
                    event_type="message",
                    ts=ts,
                    input_payload=content,
                )
            elif actor == "tool":
                _append_event(
                    events,
                    actor="tool",
                    event_type="tool_result",
                    ts=ts,
                    output_payload=content,
                    tool=message.get("name"),
                )
            else:
                _append_event(
                    events,
                    actor=actor,
                    event_type="message",
                    ts=ts,
                    output_payload=content,
                )

        function_call = message.get("function_call")
        if isinstance(function_call, dict):
            _append_event(
                events,
                actor="agent",
                event_type="tool_call",
                ts=ts,
                tool=function_call.get("name"),
                input_payload=_safe_json_loads(function_call.get("arguments")),
            )

        tool_calls = message.get("tool_calls", [])
        if isinstance(tool_calls, list):
            for call in tool_calls:
                if not isinstance(call, dict):
                    continue
                function = call.get("function", {}) if isinstance(call.get("function"), dict) else {}
                tool_name = function.get("name") or call.get("name")
                arguments = function.get("arguments", call.get("arguments"))
                _append_event(
                    events,
                    actor="agent",
                    event_type="tool_call",
                    ts=ts,
                    tool=str(tool_name) if tool_name is not None else None,
                    input_payload=_safe_json_loads(arguments),
                )
    return events


def _parse_openai_output_items(items: list[dict[str, Any]]) -> list[TraceEvent]:
    events: list[TraceEvent] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type", ""))
        ts = _extract_ts(item)
        if item_type == "message":
            content = _extract_text(item.get("content"))
            if content:
                _append_event(
                    events,
                    actor=_to_actor(str(item.get("role", "assistant"))),
                    event_type="message",
                    ts=ts,
                    output_payload=content,
                )
        elif item_type in {"function_call", "tool_call"}:
            _append_event(
                events,
                actor="agent",
                event_type="tool_call",
                ts=ts,
                tool=item.get("name"),
                input_payload=_safe_json_loads(
                    item.get("arguments", item.get("input", {}))
                ),
            )
        elif item_type in {"function_call_output", "tool_result"}:
            _append_event(
                events,
                actor="tool",
                event_type="tool_result",
                ts=ts,
                tool=item.get("name"),
                output_payload=item.get("output", item.get("content")),
            )
    return events


def parse_openai_record(record: dict[str, Any]) -> tuple[list[TraceEvent], Any]:
    events: list[TraceEvent] = []
    messages = record.get("messages")
    if isinstance(messages, list):
        events.extend(
            _parse_openai_messages([message for message in messages if isinstance(message, dict)])
        )

    response = record.get("response")
    if isinstance(response, dict):
        output = response.get("output")
        if isinstance(output, list):
            events.extend(_parse_openai_output_items([x for x in output if isinstance(x, dict)]))

    output = record.get("output")
    if isinstance(output, list):
        events.extend(_parse_openai_output_items([x for x in output if isinstance(x, dict)]))

    if not events and isinstance(record.get("events"), list):
        for item in record["events"]:
            if not isinstance(item, dict):
                continue
            _append_event(
                events,
                actor=_to_actor(str(item.get("actor", item.get("role", "agent")))),
                event_type=str(item.get("type", "message")),
                ts=_extract_ts(item),
                input_payload=item.get("input"),
                output_payload=item.get("output"),
                tool=item.get("tool"),
                error=item.get("error"),
            )

    return events, _extract_first_user_input(events)


def parse_anthropic_record(record: dict[str, Any]) -> tuple[list[TraceEvent], Any]:
    events: list[TraceEvent] = []
    messages = record.get("messages")
    if not isinstance(messages, list):
        messages = record.get("input")
    if not isinstance(messages, list):
        return events, None

    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role", "assistant"))
        actor = _to_actor(role)
        ts = _extract_ts(message)
        content = message.get("content")

        if isinstance(content, str):
            if actor == "user":
                _append_event(
                    events, actor="user", event_type="message", ts=ts, input_payload=content
                )
            else:
                _append_event(
                    events,
                    actor=actor,
                    event_type="message",
                    ts=ts,
                    output_payload=content,
                )
            continue

        if not isinstance(content, list):
            continue

        for block in content:
            if not isinstance(block, dict):
                continue
            block_type = str(block.get("type", ""))
            if block_type == "text":
                text = _extract_text(block.get("text"))
                if text:
                    if actor == "user":
                        _append_event(
                            events,
                            actor="user",
                            event_type="message",
                            ts=ts,
                            input_payload=text,
                        )
                    else:
                        _append_event(
                            events,
                            actor=actor,
                            event_type="message",
                            ts=ts,
                            output_payload=text,
                        )
            elif block_type == "tool_use":
                _append_event(
                    events,
                    actor="agent",
                    event_type="tool_call",
                    ts=ts,
                    tool=block.get("name"),
                    input_payload=block.get("input"),
                )
            elif block_type == "tool_result":
                _append_event(
                    events,
                    actor="tool",
                    event_type="tool_result",
                    ts=ts,
                    tool=block.get("name"),
                    output_payload=block.get("content"),
                )
    return events, _extract_first_user_input(events)


def _parse_vertex_contents(contents: list[dict[str, Any]]) -> list[TraceEvent]:
    events: list[TraceEvent] = []
    for content in contents:
        if not isinstance(content, dict):
            continue
        role = str(content.get("role", "assistant"))
        actor = _to_actor(role)
        ts = _extract_ts(content)
        parts = content.get("parts", [])
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict):
                continue
            if "text" in part:
                text = _extract_text(part.get("text"))
                if not text:
                    continue
                if actor == "user":
                    _append_event(
                        events,
                        actor="user",
                        event_type="message",
                        ts=ts,
                        input_payload=text,
                    )
                else:
                    _append_event(
                        events,
                        actor=actor,
                        event_type="message",
                        ts=ts,
                        output_payload=text,
                    )
            if isinstance(part.get("functionCall"), dict):
                function_call = part["functionCall"]
                _append_event(
                    events,
                    actor="agent",
                    event_type="tool_call",
                    ts=ts,
                    tool=function_call.get("name"),
                    input_payload=function_call.get("args", {}),
                )
            if isinstance(part.get("functionResponse"), dict):
                function_response = part["functionResponse"]
                _append_event(
                    events,
                    actor="tool",
                    event_type="tool_result",
                    ts=ts,
                    tool=function_response.get("name"),
                    output_payload=function_response.get("response"),
                )
    return events


def parse_vertex_record(record: dict[str, Any]) -> tuple[list[TraceEvent], Any]:
    events: list[TraceEvent] = []
    contents = record.get("contents")
    if isinstance(contents, list):
        events.extend(_parse_vertex_contents([item for item in contents if isinstance(item, dict)]))

    candidates = record.get("candidates")
    if isinstance(candidates, list):
        candidate_contents = [
            candidate.get("content")
            for candidate in candidates
            if isinstance(candidate, dict) and isinstance(candidate.get("content"), dict)
        ]
        events.extend(_parse_vertex_contents(candidate_contents))

    predictions = record.get("predictions")
    if isinstance(predictions, list):
        for prediction in predictions:
            if not isinstance(prediction, dict):
                continue
            if isinstance(prediction.get("content"), dict):
                events.extend(_parse_vertex_contents([prediction["content"]]))
            if isinstance(prediction.get("candidates"), list):
                candidate_contents = [
                    candidate.get("content")
                    for candidate in prediction["candidates"]
                    if isinstance(candidate, dict)
                    and isinstance(candidate.get("content"), dict)
                ]
                events.extend(_parse_vertex_contents(candidate_contents))

    return events, _extract_first_user_input(events)


def parse_foundry_record(record: dict[str, Any]) -> tuple[list[TraceEvent], Any]:
    events, user_input = parse_openai_record(record)
    if events:
        return events, user_input

    steps = record.get("steps")
    if not isinstance(steps, list):
        return events, user_input

    for step in steps:
        if not isinstance(step, dict):
            continue
        role = str(step.get("role", step.get("actor", "agent")))
        actor = _to_actor(role)
        event_type = str(step.get("type", "message"))
        _append_event(
            events,
            actor=actor,
            event_type=event_type,
            ts=_extract_ts(step),
            input_payload=step.get("input"),
            output_payload=step.get("output", step.get("content")),
            tool=step.get("tool", step.get("name")),
            error=step.get("error"),
        )
    return events, _extract_first_user_input(events)


def detect_provider(record: dict[str, Any]) -> str:
    if "anthropic_version" in record:
        return "anthropic"
    if isinstance(record.get("messages"), list):
        for message in record["messages"]:
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") in {
                        "tool_use",
                        "tool_result",
                    }:
                        return "anthropic"
        return "openai"

    if isinstance(record.get("contents"), list) or isinstance(record.get("candidates"), list):
        return "vertex"
    if isinstance(record.get("steps"), list):
        return "foundry"
    if "azureml" in json.dumps(record, default=str).lower():
        return "foundry"
    return "openai"


def _unknown_top_level_fields(record: dict[str, Any], provider: str) -> list[str]:
    known = KNOWN_TOP_LEVEL_KEYS.get(provider, set())
    if not known:
        return []
    unknown = [key for key in record.keys() if key not in known]
    return sorted(unknown)


PARSER_BY_PROVIDER: dict[str, Callable[[dict[str, Any]], tuple[list[TraceEvent], Any]]] = {
    "openai": parse_openai_record,
    "anthropic": parse_anthropic_record,
    "vertex": parse_vertex_record,
    "foundry": parse_foundry_record,
}


def load_trace_records(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    if source.suffix.lower() == ".jsonl":
        records: list[dict[str, Any]] = []
        with source.open("r", encoding="utf-8") as handle:
            for line in handle:
                text = line.strip()
                if not text:
                    continue
                record = json.loads(text)
                if isinstance(record, dict):
                    records.append(record)
        return records

    with source.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if isinstance(payload, dict):
        for key in ("traces", "runs", "records", "data", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    raise ValueError(f"unsupported input payload in {source}")


def import_to_suite(
    input_path: str | Path,
    provider: str,
    dataset_id: str,
    case_prefix: str = "case",
    strict: bool = False,
) -> dict[str, Any]:
    if provider not in PROVIDERS:
        raise ValueError(
            f"unsupported provider '{provider}'. supported values: {', '.join(PROVIDERS)}"
        )

    records = load_trace_records(input_path)
    cases: list[dict[str, Any]] = []
    provider_counts: dict[str, int] = {}
    diagnostics: list[dict[str, Any]] = []

    for index, record in enumerate(records, start=1):
        resolved_provider = provider if provider != "auto" else detect_provider(record)
        unknown_fields = _unknown_top_level_fields(record, resolved_provider)
        if unknown_fields:
            diagnostics.append(
                {
                    "record_index": index,
                    "provider": resolved_provider,
                    "type": "unknown_top_level_fields",
                    "fields": unknown_fields,
                }
            )
            if strict:
                raise ValueError(
                    f"record {index} has unknown top-level fields for provider "
                    f"{resolved_provider}: {', '.join(unknown_fields)}"
                )

        parser = PARSER_BY_PROVIDER[resolved_provider]
        trace_events, case_input = parser(record)
        if not trace_events:
            diagnostics.append(
                {
                    "record_index": index,
                    "provider": resolved_provider,
                    "type": "empty_trace",
                    "detail": "record parsed with zero events and was dropped",
                }
            )
            if strict:
                raise ValueError(
                    f"record {index} for provider {resolved_provider} produced empty trace"
                )
            continue

        trace_id = uuid.uuid4().hex
        for event_index, event in enumerate(trace_events):
            if not event.trace_id:
                event.trace_id = trace_id
            if not event.span_id:
                event.span_id = f"{event_index + 1:016x}"
            if event.parent_span_id is None and event_index > 0:
                event.parent_span_id = f"{event_index:016x}"
            event.attributes = dict(event.attributes)
            event.attributes.setdefault("gen_ai.system", resolved_provider)
            event.attributes.setdefault("gen_ai.operation.name", event.type)
            if event.tool:
                event.attributes.setdefault("gen_ai.tool.name", event.tool)

        provider_counts[resolved_provider] = provider_counts.get(resolved_provider, 0) + 1
        case = {
            "case_id": f"{case_prefix}-{index}",
            "input": case_input,
            "trace": [event.to_dict() for event in trace_events],
            "metadata": {
                "source_provider": resolved_provider,
                "source_index": index,
            },
        }
        cases.append(case)

    return {
        "dataset_id": dataset_id,
        "cases": cases,
        "metadata": {
            "import_source": str(input_path),
            "selected_provider": provider,
            "provider_case_counts": provider_counts,
            "imported_records": len(cases),
            "total_records": len(records),
            "dropped_records": len(records) - len(cases),
            "import_diagnostics": diagnostics,
        },
    }
