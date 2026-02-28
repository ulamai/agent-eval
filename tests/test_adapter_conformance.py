from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_eval_suite.importers import import_to_suite


def _load_fixture(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class AdapterConformanceTest(unittest.TestCase):
    def test_provider_conformance(self) -> None:
        fixtures_dir = Path(__file__).resolve().parent / "fixtures" / "adapters"
        matrix = [
            {
                "provider": "openai",
                "fixture": fixtures_dir / "openai_record.json",
                "required_event_types": {"message", "tool_call", "tool_result"},
            },
            {
                "provider": "anthropic",
                "fixture": fixtures_dir / "anthropic_record.json",
                "required_event_types": {"message", "tool_call", "tool_result"},
            },
            {
                "provider": "vertex",
                "fixture": fixtures_dir / "vertex_record.json",
                "required_event_types": {"message", "tool_call", "tool_result"},
            },
            {
                "provider": "foundry",
                "fixture": fixtures_dir / "foundry_record.json",
                "required_event_types": {"message", "tool_call", "tool_result"},
            },
        ]

        for row in matrix:
            suite = import_to_suite(
                input_path=row["fixture"],
                provider=row["provider"],
                dataset_id=f"{row['provider']}-dataset",
                case_prefix=row["provider"],
            )
            self.assertEqual(1, len(suite["cases"]))
            case = suite["cases"][0]
            self.assertEqual(f"{row['provider']}-1", case["case_id"])
            self.assertEqual(row["provider"], case["metadata"]["source_provider"])
            trace = case["trace"]
            self.assertGreaterEqual(len(trace), 2)

            trace_ids = {event.get("trace_id") for event in trace}
            self.assertEqual(1, len(trace_ids))
            trace_id = next(iter(trace_ids))
            self.assertIsInstance(trace_id, str)
            self.assertEqual(32, len(trace_id))

            span_ids = [event.get("span_id") for event in trace]
            self.assertEqual(len(span_ids), len(set(span_ids)))
            self.assertTrue(all(isinstance(span, str) and len(span) == 16 for span in span_ids))

            for index, event in enumerate(trace):
                if index == 0:
                    self.assertIsNone(event.get("parent_span_id"))
                else:
                    self.assertEqual(trace[index - 1]["span_id"], event.get("parent_span_id"))
                attrs = event.get("attributes", {})
                self.assertEqual(row["provider"], attrs.get("gen_ai.system"))
                self.assertEqual(event["type"], attrs.get("gen_ai.operation.name"))

            event_types = {event["type"] for event in trace}
            self.assertTrue(row["required_event_types"].issubset(event_types))

    def test_auto_detection_conformance(self) -> None:
        fixtures_dir = Path(__file__).resolve().parent / "fixtures" / "adapters"
        records = [
            _load_fixture(fixtures_dir / "openai_record.json"),
            _load_fixture(fixtures_dir / "anthropic_record.json"),
            _load_fixture(fixtures_dir / "vertex_record.json"),
            _load_fixture(fixtures_dir / "foundry_record.json"),
        ]

        with tempfile.TemporaryDirectory() as tmp_dir_str:
            source = Path(tmp_dir_str) / "mixed.json"
            source.write_text(json.dumps({"records": records}), encoding="utf-8")

            suite = import_to_suite(
                input_path=source,
                provider="auto",
                dataset_id="mixed-conformance",
                case_prefix="mixed",
            )

        self.assertEqual(4, len(suite["cases"]))
        counts = suite["metadata"]["provider_case_counts"]
        self.assertEqual(1, counts["openai"])
        self.assertEqual(1, counts["anthropic"])
        self.assertEqual(1, counts["vertex"])
        self.assertEqual(1, counts["foundry"])


if __name__ == "__main__":
    unittest.main()
