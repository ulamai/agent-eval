from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from agent_eval_suite.cli import main


class CliErrorsTest(unittest.TestCase):
    def test_missing_file_returns_structured_error(self) -> None:
        stderr_buffer = io.StringIO()
        with redirect_stderr(stderr_buffer):
            exit_code = main(
                [
                    "run",
                    "--suite",
                    "/tmp/does-not-exist-suite.json",
                    "--out",
                    "/tmp/unused-out",
                ]
            )

        self.assertEqual(1, exit_code)
        payload = json.loads(stderr_buffer.getvalue().strip())
        self.assertEqual("file_not_found", payload["error"]["code"])

    def test_invalid_json_returns_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            suite_path = tmp_dir / "broken.json"
            suite_path.write_text("{", encoding="utf-8")

            stderr_buffer = io.StringIO()
            with redirect_stderr(stderr_buffer):
                exit_code = main(
                    [
                        "run",
                        "--suite",
                        str(suite_path),
                        "--out",
                        str(tmp_dir / "out"),
                    ]
                )
            self.assertEqual(1, exit_code)
            payload = json.loads(stderr_buffer.getvalue().strip())
            self.assertEqual("invalid_json", payload["error"]["code"])


if __name__ == "__main__":
    unittest.main()
