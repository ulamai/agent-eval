from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from agent_eval_suite.schema import EvalCase, JudgeResult


class BaseJudge(ABC):
    judge_id = "base"

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}

    @abstractmethod
    def evaluate(self, case: EvalCase) -> JudgeResult:
        raise NotImplementedError
