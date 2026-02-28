from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0.0"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class TraceEvent:
    idx: int
    ts: str
    actor: str
    type: str
    input: Any = None
    output: Any = None
    tool: str | None = None
    error: str | None = None
    latency_ms: int | None = None
    trace_id: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    attempt: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TraceEvent":
        attributes = data.get("attributes", {})
        if not isinstance(attributes, dict):
            attributes = {}
        return cls(
            idx=int(data.get("idx", 0)),
            ts=str(data.get("ts", "")),
            actor=str(data.get("actor", "")),
            type=str(data.get("type", "")),
            input=data.get("input"),
            output=data.get("output"),
            tool=data.get("tool"),
            error=data.get("error"),
            latency_ms=data.get("latency_ms"),
            trace_id=data.get("trace_id"),
            span_id=data.get("span_id"),
            parent_span_id=data.get("parent_span_id"),
            attributes=attributes,
            attempt=data.get("attempt"),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ToolContractSpec:
    required_args: list[str] = field(default_factory=list)
    forbidden_args: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolContractSpec":
        return cls(
            required_args=list(data.get("required_args", data.get("required", []))),
            forbidden_args=list(data.get("forbidden_args", data.get("forbidden", []))),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PolicySpec:
    forbidden_tools: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PolicySpec":
        return cls(
            forbidden_tools=list(data.get("forbidden_tools", [])),
            required_tools=list(data.get("required_tools", [])),
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class EvalCase:
    case_id: str
    input: Any = None
    expected_output: Any = None
    trace: list[TraceEvent] = field(default_factory=list)
    tool_contracts: dict[str, ToolContractSpec] = field(default_factory=dict)
    policy: PolicySpec = field(default_factory=PolicySpec)
    regex_patterns: list[str] = field(default_factory=list)
    json_schema: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvalCase":
        contracts = {
            tool_name: ToolContractSpec.from_dict(spec or {})
            for tool_name, spec in (data.get("tool_contracts") or {}).items()
        }
        trace_events = [TraceEvent.from_dict(event) for event in data.get("trace", [])]
        return cls(
            case_id=str(data["case_id"]),
            input=data.get("input"),
            expected_output=data.get("expected_output", data.get("expected")),
            trace=trace_events,
            tool_contracts=contracts,
            policy=PolicySpec.from_dict(data.get("policy", {})),
            regex_patterns=list(data.get("regex_patterns", data.get("regex", []))),
            json_schema=data.get("json_schema"),
            metadata=dict(data.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "input": self.input,
            "expected_output": self.expected_output,
            "trace": [event.to_dict() for event in self.trace],
            "tool_contracts": {
                name: spec.to_dict() for name, spec in self.tool_contracts.items()
            },
            "policy": self.policy.to_dict(),
            "regex_patterns": self.regex_patterns,
            "json_schema": self.json_schema,
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class EvalSuite:
    dataset_id: str
    cases: list[EvalCase]
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvalSuite":
        return cls(
            dataset_id=str(data.get("dataset_id", "dataset-unknown")),
            cases=[EvalCase.from_dict(case) for case in data.get("cases", [])],
            metadata=dict(data.get("metadata", {})),
        )

    @classmethod
    def from_path(cls, path: str | Path) -> "EvalSuite":
        with Path(path).open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return cls.from_dict(payload)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "cases": [case.to_dict() for case in self.cases],
            "metadata": self.metadata,
        }


@dataclass(slots=True)
class JudgeResult:
    judge_id: str
    case_id: str
    score: float
    passed: bool
    reason: str
    hard_fail: bool
    evidence_refs: dict[str, Any] = field(default_factory=dict)
    skipped: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class CaseResult:
    case_id: str
    passed: bool
    hard_failed: bool
    judge_results: list[JudgeResult]
    replay_issues: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "passed": self.passed,
            "hard_failed": self.hard_failed,
            "judge_results": [result.to_dict() for result in self.judge_results],
            "replay_issues": self.replay_issues,
        }


@dataclass(slots=True)
class RunConfig:
    run_id: str
    dataset_id: str
    agent_version: str
    model: str
    started_at: str
    seed: int
    judges: list[str]
    judge_configs: dict[str, Any] = field(default_factory=dict)
    execution_mode: str = "trace_score"
    execution_config: dict[str, Any] = field(default_factory=dict)
    pinned_env: dict[str, Any] = field(default_factory=dict)
    prompt_hash: str | None = None
    policy_hash: str | None = None
    container_image: str | None = None
    git_commit: str | None = None
    dependency_lock_hash: str | None = None
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunConfig":
        return cls(
            run_id=str(data.get("run_id", "")),
            dataset_id=str(data.get("dataset_id", "")),
            agent_version=str(data.get("agent_version", "unknown")),
            model=str(data.get("model", "unknown")),
            started_at=str(data.get("started_at", "")),
            seed=int(data.get("seed", 0)),
            judges=list(data.get("judges", [])),
            judge_configs=dict(data.get("judge_configs", {})),
            execution_mode=str(data.get("execution_mode", "trace_score")),
            execution_config=dict(data.get("execution_config", {})),
            pinned_env=dict(data.get("pinned_env", {})),
            prompt_hash=data.get("prompt_hash"),
            policy_hash=data.get("policy_hash"),
            container_image=data.get("container_image"),
            git_commit=data.get("git_commit"),
            dependency_lock_hash=data.get("dependency_lock_hash"),
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
        )


@dataclass(slots=True)
class RunSummary:
    run_id: str
    dataset_id: str
    total_cases: int
    passed_cases: int
    failed_cases: int
    hard_fail_cases: int
    pass_rate: float
    hard_fail_rate: float
    judge_pass_rates: dict[str, float]
    schema_version: str = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunSummary":
        return cls(
            run_id=str(data.get("run_id", "")),
            dataset_id=str(data.get("dataset_id", "")),
            total_cases=int(data.get("total_cases", 0)),
            passed_cases=int(data.get("passed_cases", 0)),
            failed_cases=int(data.get("failed_cases", 0)),
            hard_fail_cases=int(data.get("hard_fail_cases", 0)),
            pass_rate=float(data.get("pass_rate", 0.0)),
            hard_fail_rate=float(data.get("hard_fail_rate", 0.0)),
            judge_pass_rates=dict(data.get("judge_pass_rates", {})),
            schema_version=str(data.get("schema_version", SCHEMA_VERSION)),
        )
