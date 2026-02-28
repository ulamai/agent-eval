from __future__ import annotations

import json
import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from agent_eval_suite.cli import main
from agent_eval_suite.importers import import_to_suite
from agent_eval_suite.schema import EvalSuite


class ImportTraceTest(unittest.TestCase):
    def test_openai_import_trace_cli(self) -> None:
        payload = {
            "messages": [
                {"role": "user", "content": "weather in sf"},
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "type": "function",
                            "function": {
                                "name": "search_weather",
                                "arguments": "{\"city\":\"San Francisco\"}",
                            },
                        }
                    ],
                },
                {"role": "tool", "name": "search_weather", "content": "{\"temp_f\":72}"},
                {"role": "assistant", "content": "It is 72F"},
            ]
        }

        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            input_file = tmp_dir / "openai.json"
            out_file = tmp_dir / "suite.json"
            input_file.write_text(json.dumps(payload), encoding="utf-8")

            exit_code = main(
                [
                    "import-trace",
                    "--provider",
                    "openai",
                    "--input",
                    str(input_file),
                    "--out",
                    str(out_file),
                    "--dataset-id",
                    "openai-import",
                    "--case-prefix",
                    "oa",
                ]
            )
            self.assertEqual(0, exit_code)

            suite = EvalSuite.from_path(out_file)
            self.assertEqual("openai-import", suite.dataset_id)
            self.assertEqual(1, len(suite.cases))
            self.assertEqual("oa-1", suite.cases[0].case_id)
            event_types = [event.type for event in suite.cases[0].trace]
            self.assertIn("tool_call", event_types)
            self.assertIn("tool_result", event_types)

    def test_auto_detect_mixed_provider_records(self) -> None:
        records = {
            "records": [
                {
                    "messages": [
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "name": "search_docs",
                                    "input": {"q": "policy"},
                                },
                                {"type": "text", "text": "done"},
                            ],
                        }
                    ]
                },
                {
                    "contents": [
                        {
                            "role": "user",
                            "parts": [{"text": "weather in sf"}],
                        },
                        {
                            "role": "model",
                            "parts": [
                                {
                                    "functionCall": {
                                        "name": "search_weather",
                                        "args": {"city": "San Francisco"},
                                    }
                                },
                                {
                                    "functionResponse": {
                                        "name": "search_weather",
                                        "response": {"temp_f": 72},
                                    }
                                },
                                {"text": "It is 72F"},
                            ],
                        },
                    ]
                },
                {
                    "steps": [
                        {"role": "user", "type": "message", "input": "ping"},
                        {"role": "assistant", "type": "message", "output": "pong"},
                    ]
                },
            ]
        }

        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            input_file = tmp_dir / "mixed.json"
            input_file.write_text(json.dumps(records), encoding="utf-8")

            suite = import_to_suite(
                input_path=input_file,
                provider="auto",
                dataset_id="mixed-import",
                case_prefix="mix",
            )
            self.assertEqual(3, len(suite["cases"]))
            counts = suite["metadata"]["provider_case_counts"]
            self.assertEqual(1, counts["anthropic"])
            self.assertEqual(1, counts["vertex"])
            self.assertEqual(1, counts["foundry"])

    def test_non_strict_import_emits_unknown_field_diagnostics(self) -> None:
        payload = {
            "messages": [{"role": "user", "content": "ping"}],
            "unexpected_field": {"raw": 1},
        }
        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            input_file = tmp_dir / "openai.json"
            input_file.write_text(json.dumps(payload), encoding="utf-8")

            suite = import_to_suite(
                input_path=input_file,
                provider="openai",
                dataset_id="diag-import",
                strict=False,
            )
            diagnostics = suite["metadata"]["import_diagnostics"]
            self.assertEqual(1, len(diagnostics))
            self.assertEqual("unknown_top_level_fields", diagnostics[0]["type"])
            self.assertIn("unexpected_field", diagnostics[0]["fields"])

    def test_strict_import_rejects_unknown_fields(self) -> None:
        payload = {
            "messages": [{"role": "user", "content": "ping"}],
            "unexpected_field": {"raw": 1},
        }
        with tempfile.TemporaryDirectory() as tmp_dir_str:
            tmp_dir = Path(tmp_dir_str)
            input_file = tmp_dir / "openai.json"
            out_file = tmp_dir / "suite.json"
            input_file.write_text(json.dumps(payload), encoding="utf-8")

            stderr_buffer = io.StringIO()
            with redirect_stderr(stderr_buffer):
                exit_code = main(
                    [
                        "import-trace",
                        "--provider",
                        "openai",
                        "--strict",
                        "--input",
                        str(input_file),
                        "--out",
                        str(out_file),
                    ]
                )
            self.assertEqual(1, exit_code)
            error_payload = json.loads(stderr_buffer.getvalue().strip())
            self.assertEqual("validation_error", error_payload["error"]["code"])


if __name__ == "__main__":
    unittest.main()
