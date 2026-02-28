from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_eval_suite.cli import main
from agent_eval_suite.compare import compare_runs


class CompareTest(unittest.TestCase):
    def test_case_regressions_emitted(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        suite_good = project_root / "examples" / "suite_good.json"
        suite_bad = project_root / "examples" / "suite_bad.json"

        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            baseline_dir = tmp_dir / "baseline"
            candidate_dir = tmp_dir / "candidate"

            self.assertEqual(
                0,
                main(
                    [
                        "run",
                        "--suite",
                        str(suite_good),
                        "--out",
                        str(baseline_dir),
                        "--run-id",
                        "baseline-compare",
                    ]
                ),
            )
            self.assertEqual(
                0,
                main(
                    [
                        "run",
                        "--suite",
                        str(suite_bad),
                        "--out",
                        str(candidate_dir),
                        "--run-id",
                        "candidate-compare",
                    ]
                ),
            )

            report = compare_runs(baseline_dir, candidate_dir)
            self.assertIn("case_regressions", report)
            self.assertEqual(1, len(report["case_regressions"]))
            case = report["case_regressions"][0]
            self.assertEqual("case-1", case["case_id"])
            self.assertTrue(case["regressed"])
            self.assertFalse(case["candidate_passed"])
            self.assertIn("case regressed: case-1", report["regressions"])

    def test_legacy_summary_keys_supported(self) -> None:
        baseline_legacy = {
            "run_id": "legacy-baseline",
            "dataset_id": "legacy-dataset",
            "total": 10,
            "passed": 9,
            "failed": 1,
            "hard_fail_count": 1,
            "pass_rate": 0.9,
            "hard_fail_rate": 0.1,
            "judge_rates": {"policy": 0.9},
        }
        candidate_legacy = {
            "run_id": "legacy-candidate",
            "dataset_id": "legacy-dataset",
            "total": 10,
            "passed": 8,
            "failed": 2,
            "hard_fail_count": 2,
            "pass_rate": 0.8,
            "hard_fail_rate": 0.2,
            "judge_rates": {"policy": 0.8},
        }

        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            baseline_file = tmp_dir / "baseline-summary.json"
            candidate_file = tmp_dir / "candidate-summary.json"
            baseline_file.write_text(json.dumps(baseline_legacy), encoding="utf-8")
            candidate_file.write_text(json.dumps(candidate_legacy), encoding="utf-8")

            report = compare_runs(baseline_file, candidate_file)
            self.assertAlmostEqual(-0.1, report["metrics"]["pass_rate"]["delta"])
            self.assertAlmostEqual(
                0.1, report["metrics"]["hard_fail_rate"]["delta"], places=6
            )
            self.assertIn("policy", report["judge_metrics"])


if __name__ == "__main__":
    unittest.main()
