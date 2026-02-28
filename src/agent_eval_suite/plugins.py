from __future__ import annotations

from importlib import import_module
from importlib.metadata import entry_points
from typing import Any

from agent_eval_suite.judges.base import BaseJudge

BUILTIN_JUDGES: dict[str, str] = {
    "tool_contract": "agent_eval_suite.judges.tool_contract:ToolContractJudge",
    "policy": "agent_eval_suite.judges.policy:PolicyJudge",
    "regex": "agent_eval_suite.judges.regex:RegexJudge",
    "json_schema": "agent_eval_suite.judges.json_schema:JSONSchemaJudge",
    "trajectory_step": "agent_eval_suite.judges.trajectory_step:TrajectoryStepJudge",
    "repair_path": "agent_eval_suite.judges.repair_path:RepairPathJudge",
    "cost_budget": "agent_eval_suite.judges.cost_budget:CostBudgetJudge",
    "latency_slo": "agent_eval_suite.judges.latency_slo:LatencySLOJudge",
    "retry_storm": "agent_eval_suite.judges.retry_storm:RetryStormJudge",
    "loop_guard": "agent_eval_suite.judges.loop_guard:LoopGuardJudge",
    "tool_abuse": "agent_eval_suite.judges.tool_abuse:ToolAbuseJudge",
    "prompt_injection": "agent_eval_suite.judges.prompt_injection:PromptInjectionJudge",
    "lean": "agent_eval_suite.judges.lean:LeanJudge",
}

DEFAULT_JUDGES = ["tool_contract", "policy", "trajectory_step", "regex", "json_schema"]


def _load_object(import_path: str) -> type[BaseJudge]:
    if ":" not in import_path:
        raise ValueError(f"invalid import path '{import_path}', expected module:Class")
    module_name, attr_name = import_path.split(":", 1)
    module = import_module(module_name)
    judge_cls = getattr(module, attr_name)
    if not issubclass(judge_cls, BaseJudge):
        raise TypeError(f"{import_path} is not a BaseJudge subclass")
    return judge_cls


def resolve_judge(name: str) -> str:
    if name in BUILTIN_JUDGES:
        return BUILTIN_JUDGES[name]

    points = entry_points(group="agent_eval_suite.judges")
    for point in points:
        if point.name == name:
            return f"{point.module}:{point.attr}"

    if ":" in name:
        return name

    raise KeyError(
        f"unknown judge '{name}'. Use a built-in judge, entry point, or module:Class."
    )


def instantiate_judge(name: str, config: dict[str, Any] | None = None) -> BaseJudge:
    import_path = resolve_judge(name)
    judge_cls = _load_object(import_path)
    return judge_cls(config=config)
