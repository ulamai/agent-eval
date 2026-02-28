from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from agent_eval_suite.artifacts import write_json

ARCHETYPES = (
    "support_agent",
    "research_agent",
    "ops_agent",
    "coding_agent",
)


def _support_case(index: int, rng: random.Random) -> dict[str, Any]:
    city = rng.choice(["San Francisco", "New York", "Austin", "Chicago"])
    return {
        "case_id": f"support-{index}",
        "input": f"What is the weather in {city}?",
        "expected_output": {"answer": "72F", "status": "ok"},
        "tool_contracts": {
            "search_weather": {
                "required_args": ["city"],
                "forbidden_args": ["api_key"],
            }
        },
        "policy": {
            "required_tools": ["search_weather"],
            "forbidden_tools": ["delete_database"],
        },
        "regex_patterns": ["72F", "ok"],
        "json_schema": {
            "type": "object",
            "required": ["answer", "status"],
            "properties": {
                "answer": {"type": "string"},
                "status": {"type": "string", "enum": ["ok"]},
            },
        },
        "trace": [],
        "metadata": {
            "domain": "support",
            "tool_responses": {"search_weather": {"temp_f": 72, "city": city}},
        },
    }


def _research_case(index: int, rng: random.Random) -> dict[str, Any]:
    topic = rng.choice(["SOC2", "ISO27001", "GDPR", "HIPAA"])
    return {
        "case_id": f"research-{index}",
        "input": f"Summarize the key requirements of {topic}.",
        "expected_output": {"summary": "...", "sources": ["..."]},
        "tool_contracts": {
            "search_docs": {
                "required_args": ["q"],
                "forbidden_args": ["token"],
            }
        },
        "policy": {
            "required_tools": ["search_docs"],
            "forbidden_tools": ["exec_shell"],
        },
        "regex_patterns": [topic],
        "json_schema": {
            "type": "object",
            "required": ["summary", "sources"],
            "properties": {
                "summary": {"type": "string"},
                "sources": {"type": "array", "items": {"type": "string"}},
            },
        },
        "trace": [],
        "metadata": {
            "domain": "research",
            "tool_responses": {
                "search_docs": {
                    "hits": [f"{topic} requirement 1", f"{topic} requirement 2"]
                }
            },
        },
    }


def _ops_case(index: int, rng: random.Random) -> dict[str, Any]:
    service = rng.choice(["api", "db", "queue", "worker"])
    return {
        "case_id": f"ops-{index}",
        "input": f"Run health checks for {service}.",
        "expected_output": {"service": service, "status": "healthy"},
        "tool_contracts": {
            "health_check": {
                "required_args": ["service"],
                "forbidden_args": ["force"],
            }
        },
        "policy": {
            "required_tools": ["health_check"],
            "forbidden_tools": ["drop_database"],
        },
        "regex_patterns": ["healthy"],
        "json_schema": {
            "type": "object",
            "required": ["service", "status"],
            "properties": {
                "service": {"type": "string"},
                "status": {"type": "string", "enum": ["healthy"]},
            },
        },
        "trace": [],
        "metadata": {
            "domain": "ops",
            "tool_responses": {"health_check": {"service": service, "ok": True}},
        },
    }


def _coding_case(index: int, rng: random.Random) -> dict[str, Any]:
    language = rng.choice(["python", "typescript", "go", "rust"])
    return {
        "case_id": f"coding-{index}",
        "input": f"Write a {language} function to parse JSON safely.",
        "expected_output": {"language": language, "status": "ok"},
        "tool_contracts": {
            "run_tests": {
                "required_args": ["path"],
                "forbidden_args": ["sudo"],
            }
        },
        "policy": {
            "required_tools": ["run_tests"],
            "forbidden_tools": ["delete_repo"],
        },
        "regex_patterns": ["json", "ok"],
        "json_schema": {
            "type": "object",
            "required": ["language", "status"],
            "properties": {
                "language": {"type": "string"},
                "status": {"type": "string", "enum": ["ok"]},
            },
        },
        "trace": [],
        "metadata": {
            "domain": "coding",
            "tool_responses": {"run_tests": {"passed": True, "language": language}},
        },
    }


BUILDERS = {
    "support_agent": _support_case,
    "research_agent": _research_case,
    "ops_agent": _ops_case,
    "coding_agent": _coding_case,
}


def generate_benchmark_suite(
    *,
    archetype: str,
    cases: int,
    seed: int = 0,
    dataset_id: str | None = None,
) -> dict[str, Any]:
    if archetype not in ARCHETYPES:
        raise ValueError(f"unsupported archetype '{archetype}'. supported: {', '.join(ARCHETYPES)}")
    if cases <= 0:
        raise ValueError("cases must be > 0")

    rng = random.Random(seed)
    builder = BUILDERS[archetype]
    payload = {
        "dataset_id": dataset_id or f"public-{archetype}",
        "metadata": {
            "schema_version": "1.0.0",
            "benchmark_type": "public",
            "archetype": archetype,
            "seed": seed,
            "case_count": cases,
        },
        "cases": [builder(index + 1, rng) for index in range(cases)],
    }
    return payload


def write_benchmark_suite(
    *,
    archetype: str,
    cases: int,
    out_path: str | Path,
    seed: int = 0,
    dataset_id: str | None = None,
) -> Path:
    payload = generate_benchmark_suite(
        archetype=archetype,
        cases=cases,
        seed=seed,
        dataset_id=dataset_id,
    )
    target = Path(out_path)
    write_json(target, payload)
    return target
