from __future__ import annotations

import json
import shlex
import subprocess
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from agent_eval_suite.runner import EvalRunner
from agent_eval_suite.schema import EvalCase, EvalSuite, TraceEvent


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, (dict, list, str, int, float, bool)) or value is None:
        return value
    return str(value)


def _parse_command(command: str) -> list[str]:
    parts = shlex.split(command)
    if not parts:
        raise ValueError("command is empty")
    return parts


def _run_agent_command(command: list[str], payload: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        input=json.dumps(payload).encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout_seconds,
    )
    stdout = completed.stdout.decode("utf-8", errors="replace").strip()
    stderr = completed.stderr.decode("utf-8", errors="replace").strip()

    if completed.returncode != 0:
        return {
            "assistant_output": None,
            "tool_calls": [],
            "error": f"command exited {completed.returncode}: {stderr}",
            "raw_stdout": stdout,
        }

    if not stdout:
        return {"assistant_output": "", "tool_calls": []}

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return {"assistant_output": stdout, "tool_calls": []}

    if isinstance(payload, dict):
        tool_calls = payload.get("tool_calls", [])
        if not isinstance(tool_calls, list):
            tool_calls = []
        return {
            "assistant_output": payload.get("assistant_output", payload.get("output")),
            "tool_calls": tool_calls,
            "error": payload.get("error"),
            "metadata": payload.get("metadata", {}),
        }
    return {"assistant_output": payload, "tool_calls": []}


def _event_timestamp(base_ts: datetime, offset_seconds: int) -> str:
    return (base_ts + timedelta(seconds=offset_seconds)).isoformat()


def _build_attempt_trace(
    case: EvalCase,
    attempt: int,
    assistant_output: Any,
    tool_calls: list[dict[str, Any]],
    tool_responses: dict[str, Any],
    command_error: str | None = None,
) -> list[TraceEvent]:
    trace_id = uuid.uuid4().hex
    base_ts = datetime.now(UTC)
    events: list[TraceEvent] = []

    def append_event(
        actor: str,
        event_type: str,
        input_payload: Any = None,
        output_payload: Any = None,
        tool: str | None = None,
        error: str | None = None,
    ) -> None:
        idx = len(events)
        span_id = f"{idx + 1:016x}"
        parent_span_id = f"{idx:016x}" if idx > 0 else None
        events.append(
            TraceEvent(
                idx=idx,
                ts=_event_timestamp(base_ts, idx),
                actor=actor,
                type=event_type,
                input=_to_jsonable(input_payload),
                output=_to_jsonable(output_payload),
                tool=tool,
                error=error,
                trace_id=trace_id,
                span_id=span_id,
                parent_span_id=parent_span_id,
                attributes={
                    "gen_ai.operation.name": event_type,
                    "gen_ai.tool.name": tool,
                },
                attempt=attempt,
            )
        )

    append_event(actor="user", event_type="message", input_payload=case.input)
    if command_error:
        append_event(
            actor="agent",
            event_type="message",
            output_payload=assistant_output,
            error=command_error,
        )
        return events

    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        tool_name = call.get("tool") or call.get("name")
        arguments = call.get("arguments", call.get("input", {}))
        append_event(
            actor="agent",
            event_type="tool_call",
            tool=str(tool_name) if tool_name is not None else None,
            input_payload=arguments,
        )
        response = tool_responses.get(str(tool_name), {"error": "unknown_tool"})
        response_error = None
        response_output = response
        if isinstance(response, dict) and "error" in response:
            response_error = str(response.get("error"))
            response_output = response.get("output")
        append_event(
            actor="tool",
            event_type="tool_result",
            tool=str(tool_name) if tool_name is not None else None,
            output_payload=response_output,
            error=response_error,
        )

    append_event(actor="assistant", event_type="message", output_payload=assistant_output)
    return events


class ProposeExecuteRepairRunner:
    def __init__(
        self,
        eval_runner: EvalRunner,
        propose_command: str,
        repair_command: str | None = None,
        max_repairs: int = 2,
        timeout_seconds: int = 30,
    ):
        self.eval_runner = eval_runner
        self.propose_command = _parse_command(propose_command)
        self.repair_command = _parse_command(repair_command) if repair_command else None
        self.max_repairs = max_repairs
        self.timeout_seconds = timeout_seconds

    def _run_case_attempt(
        self,
        case: EvalCase,
        attempt: int,
        previous_attempts: list[dict[str, Any]],
    ) -> tuple[EvalCase, dict[str, Any]]:
        command = self.propose_command
        mode = "propose"
        if attempt > 0 and self.repair_command is not None:
            command = self.repair_command
            mode = "repair"

        payload = {
            "mode": mode,
            "case_id": case.case_id,
            "input": case.input,
            "expected_output": case.expected_output,
            "attempt": attempt,
            "previous_attempts": previous_attempts,
            "tool_contracts": {
                name: spec.to_dict() for name, spec in case.tool_contracts.items()
            },
            "policy": case.policy.to_dict(),
            "metadata": case.metadata,
        }

        response = _run_agent_command(command, payload, self.timeout_seconds)
        attempt_trace = _build_attempt_trace(
            case=case,
            attempt=attempt,
            assistant_output=response.get("assistant_output"),
            tool_calls=response.get("tool_calls", []),
            tool_responses=case.metadata.get("tool_responses", {}),
            command_error=response.get("error"),
        )
        attempt_case = EvalCase(
            case_id=case.case_id,
            input=case.input,
            expected_output=case.expected_output,
            trace=attempt_trace,
            tool_contracts=case.tool_contracts,
            policy=case.policy,
            regex_patterns=case.regex_patterns,
            json_schema=case.json_schema,
            metadata=case.metadata,
        )
        return attempt_case, response

    def run(self, suite: EvalSuite) -> EvalSuite:
        output_cases: list[EvalCase] = []
        for case in suite.cases:
            history: list[dict[str, Any]] = []
            selected_case: EvalCase | None = None
            selected_result = None

            for attempt in range(self.max_repairs + 1):
                attempt_case, raw_response = self._run_case_attempt(case, attempt, history)
                case_result = self.eval_runner.evaluate_case(attempt_case)

                history.append(
                    {
                        "attempt": attempt,
                        "passed": case_result.passed,
                        "hard_failed": case_result.hard_failed,
                        "response": raw_response,
                        "judge_results": [
                            result.to_dict() for result in case_result.judge_results
                        ],
                        "replay_issues": case_result.replay_issues,
                    }
                )
                selected_case = attempt_case
                selected_result = case_result
                if case_result.passed:
                    break

            if selected_case is None or selected_result is None:
                selected_case = case
                selected_result = self.eval_runner.evaluate_case(case)

            selected_case.metadata = dict(selected_case.metadata)
            selected_case.metadata["attempt_history"] = history
            selected_case.metadata["selected_attempt"] = history[-1]["attempt"] if history else 0
            selected_case.metadata["max_repairs"] = self.max_repairs
            selected_case.metadata["loop_passed"] = selected_result.passed
            output_cases.append(selected_case)

        metadata = dict(suite.metadata)
        metadata["execution_mode"] = "propose_execute_repair"
        return EvalSuite(dataset_id=suite.dataset_id, cases=output_cases, metadata=metadata)
