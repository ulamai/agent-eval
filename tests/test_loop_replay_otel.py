from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from agent_eval_suite.cli import main


class LoopReplayOtelTest(unittest.TestCase):
    def test_run_loop_replay_and_otel_export(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        fixture_script = project_root / "tests" / "fixtures" / "mock_loop_agent.py"

        suite_payload = {
            "dataset_id": "loop-suite",
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
            run_dir = tmp_dir / "run-loop"
            replay_report = tmp_dir / "replay.json"
            otel_file = tmp_dir / "otel.jsonl"
            suite_file.write_text(json.dumps(suite_payload), encoding="utf-8")

            loop_exit = main(
                [
                    "run-loop",
                    "--suite",
                    str(suite_file),
                    "--out",
                    str(run_dir),
                    "--run-id",
                    "loop-run-1",
                    "--propose-command",
                    f"{sys.executable} {fixture_script}",
                    "--max-repairs",
                    "1",
                ]
            )
            self.assertEqual(0, loop_exit)

            summary = json.loads((run_dir / "run" / "summary.json").read_text("utf-8"))
            self.assertEqual(1, summary["passed_cases"])
            self.assertEqual(0, summary["hard_fail_cases"])

            trajectory = json.loads(
                (run_dir / "cases" / "loop-1" / "trajectory.json").read_text("utf-8")
            )
            self.assertEqual(1, trajectory["metadata"]["selected_attempt"])
            self.assertEqual(2, len(trajectory["metadata"]["attempt_history"]))

            replay_exit = main(
                ["replay", "--run", str(run_dir), "--out", str(replay_report)]
            )
            self.assertEqual(0, replay_exit)
            replay_payload = json.loads(replay_report.read_text("utf-8"))
            self.assertTrue(replay_payload["replay_passed"])

            export_exit = main(
                ["export-otel", "--run", str(run_dir), "--out", str(otel_file)]
            )
            self.assertEqual(0, export_exit)
            lines = [line for line in otel_file.read_text("utf-8").splitlines() if line]
            self.assertGreaterEqual(len(lines), 1)
            first = json.loads(lines[0])
            self.assertIn("trace_id", first)
            self.assertIn("span_id", first)
            self.assertEqual("agent-eval-suite", first["resource"]["service.name"])


if __name__ == "__main__":
    unittest.main()
