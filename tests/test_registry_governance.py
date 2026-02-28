from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_eval_suite.cli import main


class RegistryGovernanceTest(unittest.TestCase):
    def test_baseline_promotion_waivers_and_gate(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        suite_good = project_root / "examples" / "suite_good.json"
        suite_bad = project_root / "examples" / "suite_bad.json"

        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            registry_path = tmp_dir / "registry.json"
            baseline_dir = tmp_dir / "baseline"
            candidate_dir = tmp_dir / "candidate"
            compare_report = tmp_dir / "compare.json"
            gate_report = tmp_dir / "gate.json"

            self.assertEqual(
                0,
                main(
                    ["run", "--suite", str(suite_good), "--out", str(baseline_dir), "--run-id", "base"]
                ),
            )
            self.assertEqual(
                0,
                main(
                    ["run", "--suite", str(suite_bad), "--out", str(candidate_dir), "--run-id", "cand"]
                ),
            )

            self.assertEqual(
                0,
                main(
                    [
                        "registry",
                        "baseline-promote",
                        "--name",
                        "main",
                        "--run",
                        str(baseline_dir),
                        "--approved-by",
                        "qa@ulamai",
                        "--rationale",
                        "golden baseline",
                        "--registry-path",
                        str(registry_path),
                    ]
                ),
            )

            self.assertEqual(
                0,
                main(
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
                ),
            )

            # Initially fails because one regressed case is present.
            first_gate_exit = main(
                [
                    "gate",
                    "--compare",
                    str(compare_report),
                    "--max-regressed-cases",
                    "0",
                    "--apply-waivers",
                    "--baseline-name",
                    "main",
                    "--registry-path",
                    str(registry_path),
                    "--out",
                    str(gate_report),
                ]
            )
            self.assertEqual(1, first_gate_exit)

            self.assertEqual(
                0,
                main(
                    [
                        "registry",
                        "waiver-add",
                        "--baseline-name",
                        "main",
                        "--case-id",
                        "case-1",
                        "--approved-by",
                        "qa@ulamai",
                        "--reason",
                        "known issue pending fix",
                        "--registry-path",
                        str(registry_path),
                    ]
                ),
            )

            second_gate_exit = main(
                [
                    "gate",
                    "--compare",
                    str(compare_report),
                    "--max-regressed-cases",
                    "0",
                    "--apply-waivers",
                    "--baseline-name",
                    "main",
                    "--registry-path",
                    str(registry_path),
                    "--out",
                    str(gate_report),
                ]
            )
            self.assertEqual(0, second_gate_exit)

            registry_payload = json.loads(registry_path.read_text("utf-8"))
            self.assertIn("approvals", registry_payload)
            self.assertIn("waivers", registry_payload)
            self.assertGreaterEqual(len(registry_payload.get("audit_log", [])), 2)


if __name__ == "__main__":
    unittest.main()
