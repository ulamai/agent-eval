from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_eval_suite.cli import main


class BenchmarkGenerateTest(unittest.TestCase):
    def test_generate_benchmark_suite(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            out_file = tmp_dir / "benchmark.json"
            exit_code = main(
                [
                    "benchmark-generate",
                    "--archetype",
                    "support_agent",
                    "--cases",
                    "4",
                    "--seed",
                    "7",
                    "--out",
                    str(out_file),
                ]
            )
            self.assertEqual(0, exit_code)
            payload = json.loads(out_file.read_text("utf-8"))
            self.assertEqual("public-support_agent", payload["dataset_id"])
            self.assertEqual(4, len(payload["cases"]))
            self.assertEqual("support_agent", payload["metadata"]["archetype"])


if __name__ == "__main__":
    unittest.main()
