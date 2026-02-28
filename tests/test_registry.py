from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_eval_suite.cli import main


class RegistryTest(unittest.TestCase):
    def test_dataset_and_baseline_registry_flow(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        suite_good = project_root / "examples" / "suite_good.json"
        suite_bad = project_root / "examples" / "suite_bad.json"

        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            registry_path = tmp_dir / "registry.json"
            baseline_dir = tmp_dir / "baseline"
            candidate_dir = tmp_dir / "candidate"
            compare_report = tmp_dir / "compare.json"

            self.assertEqual(
                0,
                main(
                    [
                        "registry",
                        "dataset-add",
                        "--suite",
                        str(suite_good),
                        "--dataset-id",
                        "sample-suite",
                        "--description",
                        "sample dataset",
                        "--tag",
                        "smoke",
                        "--registry-path",
                        str(registry_path),
                    ]
                ),
            )
            self.assertTrue(registry_path.exists())

            self.assertEqual(
                0, main(["run", "--suite", str(suite_good), "--out", str(baseline_dir)])
            )
            self.assertEqual(
                0, main(["run", "--suite", str(suite_bad), "--out", str(candidate_dir)])
            )

            self.assertEqual(
                0,
                main(
                    [
                        "registry",
                        "baseline-set",
                        "--name",
                        "main",
                        "--run",
                        str(baseline_dir),
                        "--registry-path",
                        str(registry_path),
                    ]
                ),
            )

            compare_exit = main(
                [
                    "compare",
                    "--baseline",
                    "main",
                    "--candidate",
                    str(candidate_dir),
                    "--registry-path",
                    str(registry_path),
                    "--out",
                    str(compare_report),
                ]
            )
            self.assertEqual(0, compare_exit)
            payload = json.loads(compare_report.read_text("utf-8"))
            self.assertEqual("main", payload["baseline_reference"]["input"])
            self.assertEqual("main", payload["baseline_reference"]["registry_entry"]["name"])

    def test_registry_baseline_show_not_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            registry_path = tmp_dir / "registry.json"
            exit_code = main(
                [
                    "registry",
                    "baseline-show",
                    "--name",
                    "missing",
                    "--registry-path",
                    str(registry_path),
                ]
            )
            self.assertEqual(1, exit_code)


if __name__ == "__main__":
    unittest.main()
