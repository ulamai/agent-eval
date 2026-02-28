from __future__ import annotations

from collections import Counter

from agent_eval_suite.judges.base import BaseJudge
from agent_eval_suite.schema import EvalCase, JudgeResult


class LoopGuardJudge(BaseJudge):
    judge_id = "loop_guard"

    def evaluate(self, case: EvalCase) -> JudgeResult:
        max_steps = int(self.config.get("max_steps", 40))
        max_attempts = int(self.config.get("max_attempts", 3))
        max_identical_messages = int(self.config.get("max_identical_assistant_messages", 3))

        attempts = set()
        assistant_messages: list[str] = []
        for event in case.trace:
            if isinstance(event.attempt, int):
                attempts.add(event.attempt)
            if event.actor in {"assistant", "agent"} and isinstance(event.output, str):
                assistant_messages.append(event.output.strip())

        message_counts = Counter([msg for msg in assistant_messages if msg])
        worst_duplicate = max(message_counts.values()) if message_counts else 0

        violations: list[str] = []
        if len(case.trace) > max_steps:
            violations.append(f"trace has {len(case.trace)} events > max_steps {max_steps}")
        if attempts and len(attempts) > max_attempts:
            violations.append(f"attempts {len(attempts)} > max_attempts {max_attempts}")
        if worst_duplicate > max_identical_messages:
            violations.append(
                "assistant repeated identical output "
                f"{worst_duplicate} times > max_identical_assistant_messages {max_identical_messages}"
            )

        checks = 3
        score = max(0.0, 1.0 - (len(violations) / float(checks)))
        return JudgeResult(
            judge_id=self.judge_id,
            case_id=case.case_id,
            score=score,
            passed=not violations,
            reason="loop guard passed" if not violations else "looping behavior risk",
            hard_fail=True,
            evidence_refs={
                "event_count": len(case.trace),
                "attempts_seen": sorted(attempts),
                "max_identical_assistant_messages": worst_duplicate,
                "violations": violations,
            },
        )
