from __future__ import annotations

from typing import Any

from agent_eval_suite.judges.base import BaseJudge
from agent_eval_suite.schema import EvalCase, JudgeResult


class CostBudgetJudge(BaseJudge):
    judge_id = "cost_budget"

    def _extract_usage(self, case: EvalCase) -> tuple[float, float, float | None]:
        input_tokens = 0.0
        output_tokens = 0.0
        direct_cost: float | None = None

        usage = case.metadata.get("token_usage")
        if isinstance(usage, dict):
            input_tokens += float(usage.get("input_tokens", 0) or 0)
            output_tokens += float(usage.get("output_tokens", 0) or 0)
            if usage.get("cost_usd") is not None:
                direct_cost = float(usage.get("cost_usd") or 0)

        for event in case.trace:
            attrs = event.attributes if isinstance(event.attributes, dict) else {}
            input_tokens += float(
                attrs.get("usage.input_tokens", attrs.get("gen_ai.usage.input_tokens", 0)) or 0
            )
            output_tokens += float(
                attrs.get("usage.output_tokens", attrs.get("gen_ai.usage.output_tokens", 0))
                or 0
            )
            if attrs.get("cost_usd") is not None:
                direct_cost = float(attrs.get("cost_usd") or 0)

        return input_tokens, output_tokens, direct_cost

    def evaluate(self, case: EvalCase) -> JudgeResult:
        cfg = self.config
        max_input_tokens = cfg.get("max_input_tokens")
        max_output_tokens = cfg.get("max_output_tokens")
        max_total_tokens = cfg.get("max_total_tokens")
        max_cost_usd = cfg.get("max_cost_usd")
        input_cost_per_1k = float(cfg.get("input_cost_per_1k", 0.0) or 0.0)
        output_cost_per_1k = float(cfg.get("output_cost_per_1k", 0.0) or 0.0)

        has_budget = any(
            threshold is not None
            for threshold in (
                max_input_tokens,
                max_output_tokens,
                max_total_tokens,
                max_cost_usd,
            )
        )
        if not has_budget:
            return JudgeResult(
                judge_id=self.judge_id,
                case_id=case.case_id,
                score=1.0,
                passed=True,
                reason="no cost/token budgets configured",
                hard_fail=False,
                skipped=True,
            )

        input_tokens, output_tokens, direct_cost = self._extract_usage(case)
        total_tokens = input_tokens + output_tokens
        estimated_cost = (
            direct_cost
            if direct_cost is not None
            else (input_tokens / 1000.0) * input_cost_per_1k
            + (output_tokens / 1000.0) * output_cost_per_1k
        )

        violations: list[str] = []
        if max_input_tokens is not None and input_tokens > float(max_input_tokens):
            violations.append(
                f"input_tokens {input_tokens:.0f} exceeds max_input_tokens {float(max_input_tokens):.0f}"
            )
        if max_output_tokens is not None and output_tokens > float(max_output_tokens):
            violations.append(
                f"output_tokens {output_tokens:.0f} exceeds max_output_tokens {float(max_output_tokens):.0f}"
            )
        if max_total_tokens is not None and total_tokens > float(max_total_tokens):
            violations.append(
                f"total_tokens {total_tokens:.0f} exceeds max_total_tokens {float(max_total_tokens):.0f}"
            )
        if max_cost_usd is not None and estimated_cost > float(max_cost_usd):
            violations.append(
                f"cost_usd {estimated_cost:.6f} exceeds max_cost_usd {float(max_cost_usd):.6f}"
            )

        checks = sum(
            threshold is not None
            for threshold in (
                max_input_tokens,
                max_output_tokens,
                max_total_tokens,
                max_cost_usd,
            )
        )
        score = max(0.0, 1.0 - (len(violations) / float(max(1, checks))))

        return JudgeResult(
            judge_id=self.judge_id,
            case_id=case.case_id,
            score=score,
            passed=not violations,
            reason="budget checks passed" if not violations else "budget violations",
            hard_fail=False,
            evidence_refs={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "cost_usd": estimated_cost,
                "violations": violations,
            },
        )
