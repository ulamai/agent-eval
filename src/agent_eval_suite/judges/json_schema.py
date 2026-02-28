from __future__ import annotations

import json
from typing import Any

from agent_eval_suite.judges.base import BaseJudge
from agent_eval_suite.judges.utils import extract_final_output
from agent_eval_suite.schema import EvalCase, JudgeResult


def _is_type(value: Any, expected_type: str) -> bool:
    if expected_type == "object":
        return isinstance(value, dict)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "null":
        return value is None
    return True


def _validate_subset(schema: dict[str, Any], value: Any, path: str = "$") -> list[str]:
    errors: list[str] = []

    expected_type = schema.get("type")
    if isinstance(expected_type, str) and not _is_type(value, expected_type):
        errors.append(f"{path}: expected type {expected_type}")
        return errors

    enum_values = schema.get("enum")
    if isinstance(enum_values, list) and value not in enum_values:
        errors.append(f"{path}: value not in enum")

    if expected_type == "object" and isinstance(value, dict):
        required = schema.get("required", [])
        if isinstance(required, list):
            for key in required:
                if key not in value:
                    errors.append(f"{path}: missing required key '{key}'")

        properties = schema.get("properties", {})
        if isinstance(properties, dict):
            for key, prop_schema in properties.items():
                if key in value and isinstance(prop_schema, dict):
                    errors.extend(
                        _validate_subset(prop_schema, value[key], f"{path}.{key}")
                    )

    if expected_type == "array" and isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(
                    _validate_subset(item_schema, item, f"{path}[{index}]")
                )

    return errors


class JSONSchemaJudge(BaseJudge):
    judge_id = "json_schema"

    def evaluate(self, case: EvalCase) -> JudgeResult:
        if not case.json_schema:
            return JudgeResult(
                judge_id=self.judge_id,
                case_id=case.case_id,
                score=1.0,
                passed=True,
                reason="no json schema configured",
                hard_fail=True,
                skipped=True,
            )

        raw_output = extract_final_output(case)
        if raw_output is None:
            return JudgeResult(
                judge_id=self.judge_id,
                case_id=case.case_id,
                score=0.0,
                passed=False,
                reason="final output missing for json schema evaluation",
                hard_fail=True,
            )

        if isinstance(raw_output, str):
            try:
                parsed_output = json.loads(raw_output)
            except json.JSONDecodeError as exc:
                return JudgeResult(
                    judge_id=self.judge_id,
                    case_id=case.case_id,
                    score=0.0,
                    passed=False,
                    reason="final output is not valid JSON",
                    hard_fail=True,
                    evidence_refs={"error": str(exc)},
                )
        else:
            parsed_output = raw_output

        errors = _validate_subset(case.json_schema, parsed_output)
        passed = not errors
        score = 1.0 if passed else 0.0

        return JudgeResult(
            judge_id=self.judge_id,
            case_id=case.case_id,
            score=score,
            passed=passed,
            reason="json schema checks passed" if passed else "json schema mismatch",
            hard_fail=True,
            evidence_refs={"errors": errors},
        )
