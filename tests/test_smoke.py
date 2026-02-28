from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_eval_suite.cli import main


class SmokeTest(unittest.TestCase):
    def test_run_compare_gate(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        suite_good = project_root / "examples" / "suite_good.json"
        suite_bad = project_root / "examples" / "suite_bad.json"

        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            baseline_dir = tmp_dir / "baseline"
            candidate_dir = tmp_dir / "candidate"
            compare_report = tmp_dir / "compare.json"
            gate_report = tmp_dir / "gate.json"

            baseline_exit = main(
                [
                    "run",
                    "--suite",
                    str(suite_good),
                    "--out",
                    str(baseline_dir),
                    "--run-id",
                    "baseline-1",
                ]
            )
            self.assertEqual(0, baseline_exit)
            self.assertTrue((baseline_dir / "run" / "summary.json").exists())

            candidate_exit = main(
                [
                    "run",
                    "--suite",
                    str(suite_bad),
                    "--out",
                    str(candidate_dir),
                    "--run-id",
                    "candidate-1",
                ]
            )
            self.assertEqual(0, candidate_exit)

            compare_exit = main(
                [
                    "compare",
                    "--baseline",
                    str(baseline_dir),
                    "--candidate",
                    str(candidate_dir),
                    "--out",
                    str(compare_report),
                ]
            )
            self.assertEqual(0, compare_exit)
            self.assertTrue(compare_report.exists())

            with compare_report.open("r", encoding="utf-8") as handle:
                compare_payload = json.load(handle)
            self.assertLess(compare_payload["metrics"]["pass_rate"]["delta"], 0)

            gate_exit = main(
                [
                    "gate",
                    "--compare",
                    str(compare_report),
                    "--min-pass-rate",
                    "1.0",
                    "--max-hard-fail-increase",
                    "0.0",
                    "--out",
                    str(gate_report),
                ]
            )
            self.assertEqual(1, gate_exit)
            self.assertTrue(gate_report.exists())


if __name__ == "__main__":
    unittest.main()
