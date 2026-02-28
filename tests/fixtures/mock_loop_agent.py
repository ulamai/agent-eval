from __future__ import annotations

import json
import sys


def main() -> int:
    payload = json.loads(sys.stdin.read() or "{}")
    attempt = int(payload.get("attempt", 0))

    if attempt == 0:
        response = {
            "assistant_output": "{\"answer\":\"unknown\",\"status\":\"retry\"}",
            "tool_calls": [
                {
                    "tool": "search_weather",
                    "arguments": {"city": "San Francisco", "api_key": "not-allowed"},
                }
            ],
        }
    else:
        response = {
            "assistant_output": "{\"answer\":\"72F\",\"status\":\"ok\"}",
            "tool_calls": [
                {
                    "tool": "search_weather",
                    "arguments": {"city": "San Francisco"},
                }
            ],
        }

    sys.stdout.write(json.dumps(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
