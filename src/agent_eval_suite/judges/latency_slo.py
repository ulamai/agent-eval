from __future__ import annotations

from math import ceil

from agent_eval_suite.judges.base import BaseJudge
from agent_eval_suite.schema import EvalCase, JudgeResult


class LatencySLOJudge(BaseJudge):
    judge_id = "latency_slo"

    @staticmethod
    def _percentile(values: list[float], pct: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        idx = max(0, min(len(ordered) - 1, ceil((pct / 100.0) * len(ordered)) - 1))
        return float(ordered[idx])

    def evaluate(self, case: EvalCase) -> JudgeResult:
        latencies: list[float] = []
        for event in case.trace:
            if isinstance(event.latency_ms, int):
                latencies.append(float(event.latency_ms))
                continue
            attrs = event.attributes if isinstance(event.attributes, dict) else {}
            value = attrs.get("latency_ms")
            if value is not None:
                try:
                    latencies.append(float(value))
                except (TypeError, ValueError):
                    continue

        max_event_latency_ms = self.config.get("max_event_latency_ms")
        max_total_latency_ms = self.config.get("max_total_latency_ms")
        max_p95_latency_ms = self.config.get("max_p95_latency_ms")
        max_p99_latency_ms = self.config.get("max_p99_latency_ms")

        has_slo = any(
            threshold is not None
            for threshold in (
                max_event_latency_ms,
                max_total_latency_ms,
                max_p95_latency_ms,
                max_p99_latency_ms,
            )
        )
        if not has_slo:
            return JudgeResult(
                judge_id=self.judge_id,
                case_id=case.case_id,
                score=1.0,
                passed=True,
                reason="no latency SLO configured",
                hard_fail=False,
                skipped=True,
            )

        if not latencies:
            return JudgeResult(
                judge_id=self.judge_id,
                case_id=case.case_id,
                score=0.0,
                passed=False,
                reason="latency SLO configured but no latency data",
                hard_fail=False,
                evidence_refs={"violations": ["missing latency metrics"]},
            )

        total_latency = sum(latencies)
        p95 = self._percentile(latencies, 95)
        p99 = self._percentile(latencies, 99)
        worst = max(latencies)

        violations: list[str] = []
        if max_event_latency_ms is not None and worst > float(max_event_latency_ms):
            violations.append(
                f"max_event_latency_ms {worst:.2f} exceeds limit {float(max_event_latency_ms):.2f}"
            )
        if max_total_latency_ms is not None and total_latency > float(max_total_latency_ms):
            violations.append(
                f"total_latency_ms {total_latency:.2f} exceeds limit {float(max_total_latency_ms):.2f}"
            )
        if max_p95_latency_ms is not None and p95 > float(max_p95_latency_ms):
            violations.append(
                f"p95_latency_ms {p95:.2f} exceeds limit {float(max_p95_latency_ms):.2f}"
            )
        if max_p99_latency_ms is not None and p99 > float(max_p99_latency_ms):
            violations.append(
                f"p99_latency_ms {p99:.2f} exceeds limit {float(max_p99_latency_ms):.2f}"
            )

        checks = sum(
            threshold is not None
            for threshold in (
                max_event_latency_ms,
                max_total_latency_ms,
                max_p95_latency_ms,
                max_p99_latency_ms,
            )
        )
        score = max(0.0, 1.0 - (len(violations) / float(max(1, checks))))

        return JudgeResult(
            judge_id=self.judge_id,
            case_id=case.case_id,
            score=score,
            passed=not violations,
            reason="latency SLO passed" if not violations else "latency SLO violations",
            hard_fail=False,
            evidence_refs={
                "latency_count": len(latencies),
                "max_latency_ms": worst,
                "total_latency_ms": total_latency,
                "p95_latency_ms": p95,
                "p99_latency_ms": p99,
                "violations": violations,
            },
        )
