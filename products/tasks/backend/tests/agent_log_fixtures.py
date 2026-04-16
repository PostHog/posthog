"""Shared fixtures for multi-turn session log tests.

The sandbox agent writes one JSON object per line to S3. The multi-turn runner
parses those lines to track turn completion. These helpers build the minimum
shape that _check_logs recognizes.
"""

import json
from dataclasses import dataclass


def _agent_message_line(text: str) -> str:
    return json.dumps(
        {
            "notification": {
                "method": "session/update",
                "params": {
                    "update": {
                        "sessionUpdate": "agent_message",
                        "content": {"type": "text", "text": text},
                    }
                },
            }
        }
    )


def _end_turn_line() -> str:
    return json.dumps({"notification": {"result": {"stopReason": "end_turn"}}})


def _user_message_line(text: str) -> str:
    return json.dumps(
        {
            "notification": {
                "method": "session/update",
                "params": {
                    "update": {
                        "sessionUpdate": "user_message",
                        "content": {"type": "text", "text": text},
                    }
                },
            }
        }
    )


def _usage_update_line(used: int = 1000) -> str:
    return json.dumps(
        {
            "notification": {
                "method": "session/update",
                "params": {
                    "update": {
                        "sessionUpdate": "usage_update",
                        "used": used,
                    }
                },
            }
        }
    )


@dataclass
class FakeTaskRun:
    id: str = "run-1"
    log_url: str = "s3://fake/log"
    status: str = "running"
    error_message: str | None = None
