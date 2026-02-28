from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from agent_eval_suite.cli import main


class ReplayExecTest(unittest.TestCase):
    def test_replay_exec_requires_loop_run(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        suite_good = project_root / "examples" / "suite_good.json"

        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            run_dir = tmp_dir / "run"
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
                        "normal-run",
                    ]
                ),
            )

            stderr_buffer = io.StringIO()
            with redirect_stderr(stderr_buffer):
                exit_code = main(["replay-exec", "--run", str(run_dir)])
            self.assertEqual(1, exit_code)
            payload = json.loads(stderr_buffer.getvalue().strip())
            self.assertEqual("validation_error", payload["error"]["code"])


if __name__ == "__main__":
    unittest.main()
