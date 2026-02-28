from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_eval_suite.cli import main


class GovernanceAndReportingTest(unittest.TestCase):
    def test_schema_validate_strict_rejects_unknown_keys(self) -> None:
        payload = {
            "dataset_id": "strict-test",
            "metadata": {"schema_version": "1.0.0"},
            "cases": [
                {
                    "case_id": "strict-1",
                    "trace": [{"idx": 0, "actor": "assistant", "type": "message"}],
                }
            ],
            "unexpected_top_level": True,
        }

        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            suite_path = tmp_dir / "suite.json"
            suite_path.write_text(json.dumps(payload), encoding="utf-8")
            validate_exit = main(["schema", "validate", "--input", str(suite_path), "--strict"])
            self.assertEqual(1, validate_exit)

    def test_schema_migrate_then_validate_strict(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        legacy_suite = (
            project_root / "tests" / "fixtures" / "schema_backcompat" / "legacy_suite_sparse.json"
        )

        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            migrated = tmp_dir / "migrated.json"

            migrate_exit = main(
                [
                    "schema",
                    "migrate",
                    "--input",
                    str(legacy_suite),
                    "--output",
                    str(migrated),
                ]
            )
            self.assertEqual(0, migrate_exit)

            validate_exit = main(
                [
                    "schema",
                    "validate",
                    "--input",
                    str(migrated),
                    "--strict",
                    "--require-version",
                    "1.0.0",
                ]
            )
            self.assertEqual(0, validate_exit)

            payload = json.loads(migrated.read_text("utf-8"))
            self.assertEqual("1.0.0", payload["metadata"]["schema_version"])
            case = payload["cases"][0]
            self.assertEqual("pong", case["expected_output"])
            self.assertEqual(["pong"], case["regex_patterns"])
            self.assertEqual(["target"], case["tool_contracts"]["ping"]["required_args"])
            self.assertEqual(["secret"], case["tool_contracts"]["ping"]["forbidden_args"])
            self.assertTrue(all(event.get("trace_id") for event in case["trace"]))
            self.assertTrue(all(event.get("span_id") for event in case["trace"]))

    def test_adapter_conformance_and_contracts_check(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        adapters_dir = project_root / "tests" / "fixtures" / "adapters"
        schema_dir = project_root / "tests" / "fixtures" / "schema_backcompat"

        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            adapter_report = tmp_dir / "adapter_conformance.json"
            contracts_report = tmp_dir / "contracts_check.json"

            adapter_exit = main(
                [
                    "adapter-conformance",
                    "--fixtures-dir",
                    str(adapters_dir),
                    "--min-fixtures-per-provider",
                    "2",
                    "--out",
                    str(adapter_report),
                ]
            )
            self.assertEqual(0, adapter_exit)
            adapter_payload = json.loads(adapter_report.read_text("utf-8"))
            self.assertTrue(adapter_payload["passed"])
            self.assertGreaterEqual(
                adapter_payload["providers"]["openai"]["fixtures_total"], 2
            )
            self.assertGreaterEqual(
                adapter_payload["providers"]["anthropic"]["fixtures_total"], 2
            )
            self.assertGreaterEqual(
                adapter_payload["providers"]["vertex"]["fixtures_total"], 2
            )
            self.assertGreaterEqual(
                adapter_payload["providers"]["foundry"]["fixtures_total"], 2
            )

            contracts_exit = main(
                [
                    "contracts-check",
                    "--schema-fixtures-dir",
                    str(schema_dir),
                    "--adapter-fixtures-dir",
                    str(adapters_dir),
                    "--min-fixtures-per-provider",
                    "2",
                    "--out",
                    str(contracts_report),
                ]
            )
            self.assertEqual(0, contracts_exit)
            contracts_payload = json.loads(contracts_report.read_text("utf-8"))
            self.assertTrue(contracts_payload["passed"])

    def test_markdown_report_generation(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        suite_good = project_root / "examples" / "suite_good.json"
        suite_bad = project_root / "examples" / "suite_bad.json"

        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            baseline_dir = tmp_dir / "baseline"
            candidate_dir = tmp_dir / "candidate"
            compare_report = tmp_dir / "compare.json"
            gate_report = tmp_dir / "gate.json"
            replay_report = tmp_dir / "replay.json"
            markdown_report = tmp_dir / "report.md"

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
                        "report-baseline",
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
                        "report-candidate",
                    ]
                ),
            )
            self.assertEqual(
                0,
                main(
                    [
                        "compare",
                        "--baseline",
                        str(baseline_dir),
                        "--candidate",
                        str(candidate_dir),
                        "--out",
                        str(compare_report),
                    ]
                ),
            )
            self.assertEqual(
                1,
                main(
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
                ),
            )
            self.assertEqual(
                0,
                main(
                    [
                        "replay",
                        "--run",
                        str(candidate_dir),
                        "--out",
                        str(replay_report),
                    ]
                ),
            )
            report_exit = main(
                [
                    "report",
                    "markdown",
                    "--compare",
                    str(compare_report),
                    "--gate",
                    str(gate_report),
                    "--replay",
                    str(replay_report),
                    "--out",
                    str(markdown_report),
                    "--title",
                    "Release Eval Report",
                ]
            )
            self.assertEqual(0, report_exit)
            text = markdown_report.read_text("utf-8")
            self.assertIn("# Release Eval Report", text)
            self.assertIn("## Overview", text)
            self.assertIn("## Gate Decision", text)
            self.assertIn("## Replay & Environment", text)


if __name__ == "__main__":
    unittest.main()
