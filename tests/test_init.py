from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent_eval_suite.cli import main


class InitCommandTest(unittest.TestCase):
    def test_init_scaffold_and_no_overwrite_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)

            exit_code = main(["init", "--out", str(tmp_dir)])
            self.assertEqual(0, exit_code)

            self.assertTrue((tmp_dir / "suites" / "starter_suite.json").exists())
            self.assertTrue((tmp_dir / "config" / "judges.json").exists())
            self.assertTrue((tmp_dir / "config" / "gate.json").exists())
            self.assertTrue((tmp_dir / "ci" / "github-actions-agent-eval.yml").exists())

            second_exit = main(["init", "--out", str(tmp_dir)])
            self.assertEqual(1, second_exit)

            forced_exit = main(["init", "--out", str(tmp_dir), "--force"])
            self.assertEqual(0, forced_exit)


if __name__ == "__main__":
    unittest.main()
