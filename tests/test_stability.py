from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from agent_eval_suite.cli import main


class StabilityTest(unittest.TestCase):
    def test_stability_check_trace_score(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        suite_good = project_root / "examples" / "suite_good.json"

        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            out_file = tmp_dir / "stability.json"
            exit_code = main(
                [
                    "stability-check",
                    "--suite",
                    str(suite_good),
                    "--runs",
                    "3",
                    "--out",
                    str(out_file),
                ]
            )
            self.assertEqual(0, exit_code)
            payload = json.loads(out_file.read_text("utf-8"))
            self.assertEqual([], payload["flaky_case_ids"])
            self.assertEqual(0, payload["summary"]["flaky_cases"])

    def test_stability_check_detects_flaky_loop_case(self) -> None:
        suite_payload = {
            "dataset_id": "stability-loop-suite",
            "cases": [
                {
                    "case_id": "loop-1",
                    "input": "weather in sf",
                    "regex_patterns": ["72F", "ok"],
                    "json_schema": {
                        "type": "object",
                        "required": ["answer", "status"],
                        "properties": {
                            "answer": {"type": "string"},
                            "status": {"type": "string", "enum": ["ok"]},
                        },
                    },
                    "tool_contracts": {
                        "search_weather": {
                            "required_args": ["city"],
                            "forbidden_args": ["api_key"],
                        }
                    },
                    "policy": {
                        "required_tools": ["search_weather"],
                        "forbidden_tools": ["delete_database"],
                    },
                    "metadata": {
                        "tool_responses": {
                            "search_weather": {"temp_f": 72},
                        }
                    },
                }
            ],
        }

        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            suite_file = tmp_dir / "suite.json"
            out_file = tmp_dir / "stability.json"
            counter_file = tmp_dir / "counter.txt"
            script_file = tmp_dir / "flaky_loop_agent.py"
            suite_file.write_text(json.dumps(suite_payload), encoding="utf-8")

            script_file.write_text(
                """
from __future__ import annotations
import json
import sys
from pathlib import Path

counter_path = Path(sys.argv[1])
raw = counter_path.read_text('utf-8').strip() if counter_path.exists() else '0'
count = int(raw) + 1
counter_path.write_text(str(count), encoding='utf-8')

if count % 2 == 1:
    response = {
        "assistant_output": "{\\\"answer\\\":\\\"unknown\\\",\\\"status\\\":\\\"retry\\\"}",
        "tool_calls": [{"tool": "search_weather", "arguments": {"city": "San Francisco", "api_key": "bad"}}],
    }
else:
    response = {
        "assistant_output": "{\\\"answer\\\":\\\"72F\\\",\\\"status\\\":\\\"ok\\\"}",
        "tool_calls": [{"tool": "search_weather", "arguments": {"city": "San Francisco"}}],
    }

sys.stdout.write(json.dumps(response))
""".strip()
                + "\n",
                encoding="utf-8",
            )

            exit_code = main(
                [
                    "stability-check",
                    "--suite",
                    str(suite_file),
                    "--runs",
                    "4",
                    "--execution-mode",
                    "propose_execute_repair",
                    "--propose-command",
                    f"{sys.executable} {script_file} {counter_file}",
                    "--max-repairs",
                    "0",
                    "--out",
                    str(out_file),
                ]
            )
            self.assertEqual(1, exit_code)
            payload = json.loads(out_file.read_text("utf-8"))
            self.assertIn("loop-1", payload["flaky_case_ids"])
            self.assertIn("loop-1", payload["quarantine_recommended_case_ids"])


if __name__ == "__main__":
    unittest.main()
