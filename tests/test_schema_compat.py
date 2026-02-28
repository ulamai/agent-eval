from __future__ import annotations

import unittest

from agent_eval_suite.schema import EvalSuite


class SchemaCompatTest(unittest.TestCase):
    def test_legacy_case_field_aliases(self) -> None:
        legacy_suite = {
            "dataset_id": "legacy-suite",
            "cases": [
                {
                    "case_id": "legacy-1",
                    "expected": "done",
                    "regex": ["done"],
                    "tool_contracts": {
                        "search": {
                            "required": ["q"],
                            "forbidden": ["token"],
                        }
                    },
                    "trace": [
                        {
                            "idx": 0,
                            "ts": "2026-02-28T10:00:00+00:00",
                            "actor": "assistant",
                            "type": "message",
                            "output": "done",
                        }
                    ],
                }
            ],
        }

        suite = EvalSuite.from_dict(legacy_suite)
        self.assertEqual("legacy-suite", suite.dataset_id)
        self.assertEqual(1, len(suite.cases))
        case = suite.cases[0]
        self.assertEqual("done", case.expected_output)
        self.assertEqual(["done"], case.regex_patterns)
        self.assertEqual(["q"], case.tool_contracts["search"].required_args)
        self.assertEqual(["token"], case.tool_contracts["search"].forbidden_args)


if __name__ == "__main__":
    unittest.main()
