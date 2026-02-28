from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_eval_suite.cli import main


class ProvenanceTest(unittest.TestCase):
    def test_attest_and_verify(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        suite_good = project_root / "examples" / "suite_good.json"

        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            run_dir = tmp_dir / "run"
            attest_file = tmp_dir / "attestation.json"
            verify_file = tmp_dir / "verify.json"

            self.assertEqual(
                0,
                main(
                    [
                        "run",
                        "--suite",
                        str(suite_good),
                        "--out",
                        str(run_dir),
                        "--run-id",
                        "prov-run",
                    ]
                ),
            )

            self.assertEqual(
                0,
                main(
                    [
                        "attest",
                        "--run",
                        str(run_dir),
                        "--out",
                        str(attest_file),
                        "--secret",
                        "test-secret",
                    ]
                ),
            )
            self.assertTrue(attest_file.exists())

            self.assertEqual(
                0,
                main(
                    [
                        "verify-attestation",
                        "--run",
                        str(run_dir),
                        "--attestation",
                        str(attest_file),
                        "--secret",
                        "test-secret",
                        "--out",
                        str(verify_file),
                    ]
                ),
            )
            verify_payload = json.loads(verify_file.read_text("utf-8"))
            self.assertTrue(verify_payload["passed"])

            # Tamper with summary to force mismatch.
            summary_file = run_dir / "run" / "summary.json"
            summary = json.loads(summary_file.read_text("utf-8"))
            summary["pass_rate"] = 0.1234
            summary_file.write_text(json.dumps(summary), encoding="utf-8")

            verify_exit = main(
                [
                    "verify-attestation",
                    "--run",
                    str(run_dir),
                    "--attestation",
                    str(attest_file),
                    "--secret",
                    "test-secret",
                ]
            )
            self.assertEqual(1, verify_exit)


if __name__ == "__main__":
    unittest.main()
