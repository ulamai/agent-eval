from __future__ import annotations

import json
import subprocess
from typing import Any

from agent_eval_suite.judges.base import BaseJudge
from agent_eval_suite.schema import EvalCase, JudgeResult

DEFAULT_TIMEOUT_SECONDS = 30


class LeanJudge(BaseJudge):
    judge_id = "lean"

    def _run_external_command(self, command: list[str], payload: Any) -> dict[str, Any]:
        completed = subprocess.run(
            command,
            input=json.dumps(payload).encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=int(self.config.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)),
        )
        if completed.returncode != 0:
            stderr = completed.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                f"lean command failed with exit {completed.returncode}: {stderr}"
            )
        try:
            return json.loads(completed.stdout.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError("lean command returned non-JSON output") from exc

    def evaluate(self, case: EvalCase) -> JudgeResult:
        payload = case.metadata.get("lean_payload")
        if payload is None:
            return JudgeResult(
                judge_id=self.judge_id,
                case_id=case.case_id,
                score=1.0,
                passed=True,
                reason="no lean payload configured",
                hard_fail=True,
                skipped=True,
            )

        command = self.config.get("command")
        if not isinstance(command, list) or not all(
            isinstance(item, str) for item in command
        ):
            return JudgeResult(
                judge_id=self.judge_id,
                case_id=case.case_id,
                score=1.0,
                passed=True,
                reason=(
                    "lean adapter not configured; set judge config "
                    "'lean.command' to an external checker executable"
                ),
                hard_fail=True,
                skipped=True,
            )

        try:
            result: Any = self._run_external_command(command, payload)
            passed = bool(result.get("passed", False))
            reason = result.get("reason", "lean result")
            evidence = {"lean_result": result}
            score = 1.0 if passed else 0.0
        except Exception as exc:  # pragma: no cover - plugin runtime surface
            passed = False
            score = 0.0
            reason = "lean check failed"
            evidence = {"error": str(exc)}

        return JudgeResult(
            judge_id=self.judge_id,
            case_id=case.case_id,
            score=score,
            passed=passed,
            reason=reason,
            hard_fail=True,
            evidence_refs=evidence,
        )
