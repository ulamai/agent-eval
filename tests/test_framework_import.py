from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_eval_suite.cli import main


class FrameworkImportTest(unittest.TestCase):
    def test_import_framework_cli(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        fixture = project_root / "tests" / "fixtures" / "frameworks" / "langgraph_record.json"

        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            out_file = tmp_dir / "suite.json"
            exit_code = main(
                [
                    "import-framework",
                    "--framework",
                    "langgraph",
                    "--input",
                    str(fixture),
                    "--out",
                    str(out_file),
                    "--dataset-id",
                    "framework-langgraph",
                ]
            )
            self.assertEqual(0, exit_code)
            payload = json.loads(out_file.read_text("utf-8"))
            self.assertEqual("framework-langgraph", payload["dataset_id"])
            self.assertEqual(1, len(payload["cases"]))
            self.assertEqual("langgraph", payload["cases"][0]["metadata"]["source_framework"])

    def test_import_framework_auto_detect_mixed(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        fixture_1 = project_root / "tests" / "fixtures" / "frameworks" / "langgraph_record.json"
        fixture_2 = project_root / "tests" / "fixtures" / "frameworks" / "openai_agents_record.json"

        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            mixed = tmp_dir / "mixed.json"
            out_file = tmp_dir / "suite.json"
            mixed.write_text(
                json.dumps(
                    {
                        "records": [
                            json.loads(fixture_1.read_text("utf-8")),
                            json.loads(fixture_2.read_text("utf-8")),
                        ]
                    }
                ),
                encoding="utf-8",
            )

            exit_code = main(
                [
                    "import-framework",
                    "--framework",
                    "auto",
                    "--input",
                    str(mixed),
                    "--out",
                    str(out_file),
                    "--dataset-id",
                    "framework-auto",
                ]
            )
            self.assertEqual(0, exit_code)
            payload = json.loads(out_file.read_text("utf-8"))
            counts = payload["metadata"]["framework_case_counts"]
            self.assertEqual(1, counts["langgraph"])
            self.assertEqual(1, counts["openai_agents"])


if __name__ == "__main__":
    unittest.main()
