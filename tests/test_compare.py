from __future__ import annotations

import json
import io
import tempfile
import unittest
from contextlib import redirect_stderr
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

    def test_compatibility_check_blocks_mismatch_when_enforced(self) -> None:
        baseline = {
            "run_id": "a",
            "dataset_id": "dataset-a",
            "total_cases": 1,
            "passed_cases": 1,
            "failed_cases": 0,
            "hard_fail_cases": 0,
            "pass_rate": 1.0,
            "hard_fail_rate": 0.0,
            "judge_pass_rates": {},
        }
        candidate = {
            "run_id": "b",
            "dataset_id": "dataset-b",
            "total_cases": 1,
            "passed_cases": 1,
            "failed_cases": 0,
            "hard_fail_cases": 0,
            "pass_rate": 1.0,
            "hard_fail_rate": 0.0,
            "judge_pass_rates": {},
        }

        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            baseline_file = tmp_dir / "baseline.json"
            candidate_file = tmp_dir / "candidate.json"
            baseline_file.write_text(json.dumps(baseline), encoding="utf-8")
            candidate_file.write_text(json.dumps(candidate), encoding="utf-8")

            report = compare_runs(baseline_file, candidate_file)
            self.assertFalse(report["compatibility"]["passed"])
            self.assertEqual(
                "dataset_id_match", report["compatibility"]["failures"][0]["name"]
            )

            with self.assertRaises(ValueError):
                compare_runs(
                    baseline_file, candidate_file, enforce_compatibility=True
                )

    def test_cli_compare_allow_incompatible(self) -> None:
        baseline = {
            "run_id": "a",
            "dataset_id": "dataset-a",
            "total_cases": 1,
            "passed_cases": 1,
            "failed_cases": 0,
            "hard_fail_cases": 0,
            "pass_rate": 1.0,
            "hard_fail_rate": 0.0,
            "judge_pass_rates": {},
        }
        candidate = {
            "run_id": "b",
            "dataset_id": "dataset-b",
            "total_cases": 1,
            "passed_cases": 1,
            "failed_cases": 0,
            "hard_fail_cases": 0,
            "pass_rate": 1.0,
            "hard_fail_rate": 0.0,
            "judge_pass_rates": {},
        }
        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            baseline_file = tmp_dir / "baseline.json"
            candidate_file = tmp_dir / "candidate.json"
            compare_file = tmp_dir / "compare.json"
            baseline_file.write_text(json.dumps(baseline), encoding="utf-8")
            candidate_file.write_text(json.dumps(candidate), encoding="utf-8")

            stderr_buffer = io.StringIO()
            with redirect_stderr(stderr_buffer):
                strict_exit = main(
                    [
                        "compare",
                        "--baseline",
                        str(baseline_file),
                        "--candidate",
                        str(candidate_file),
                        "--out",
                        str(compare_file),
                    ]
                )
            self.assertEqual(1, strict_exit)
            strict_error = json.loads(stderr_buffer.getvalue().strip())
            self.assertEqual("validation_error", strict_error["error"]["code"])

            allow_exit = main(
                [
                    "compare",
                    "--baseline",
                    str(baseline_file),
                    "--candidate",
                    str(candidate_file),
                    "--allow-incompatible",
                    "--out",
                    str(compare_file),
                ]
            )
            self.assertEqual(0, allow_exit)
            report = json.loads(compare_file.read_text("utf-8"))
            self.assertFalse(report["compatibility"]["passed"])


if __name__ == "__main__":
    unittest.main()
