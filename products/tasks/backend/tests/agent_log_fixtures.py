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


def _tool_call_line(name: str = "grep") -> str:
    # A tool call is activity that does NOT change the trailing agent_message, so it can land
    # between an observed message and a null-cost usage_update without altering last_message.
    return json.dumps(
        {
            "notification": {
                "method": "session/update",
                "params": {"update": {"sessionUpdate": "tool_call", "title": name}},
            }
        }
    )


def _agent_message_chunk_line(text: str) -> str:
    # The agent sometimes streams its response as consecutive agent_message_chunk slices;
    # _check_logs concatenates them when reconstructing the turn's final message.
    return json.dumps(
        {
            "notification": {
                "method": "session/update",
                "params": {
                    "update": {
                        "sessionUpdate": "agent_message_chunk",
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


def _agent_error_line(message: str, category: str | None = None) -> str:
    """Build a `_posthog/error` notification line as the sandbox agent emits on a
    terminal failure. `category` mirrors classifyAgentError() output and is absent
    on older agent builds."""
    params: dict = {"message": message}
    if category is not None:
        params["error_category"] = category
    return json.dumps({"notification": {"method": "_posthog/error", "params": params}})


def _usage_update_line(used: int = 1000, cost: float | None = None) -> str:
    # cost is null until the turn finalizes; an explicit null-cost tail with no end_turn is
    # the dropped-finalization fingerprint poll_for_turn salvages on.
    return json.dumps(
        {
            "notification": {
                "method": "session/update",
                "params": {
                    "update": {
                        "sessionUpdate": "usage_update",
                        "used": used,
                        "cost": cost,
                    }
                },
            }
        }
    )


def _console_line(message: str = "agentsh network events", method: str = "_posthog/console") -> str:
    # An observability side-channel the relay interleaves into the turn log (agentsh network audit,
    # sandbox credential refresh, stdout). It carries no turn-state and can land AFTER the agent's
    # closing usage_update — the dropped-finalization tail check must skip it, not stop on it.
    return json.dumps({"notification": {"method": method, "params": {"level": "debug", "message": message}}})


def _progress_line(status: str = "failed", step: str = "agent", label: str = "Running agent") -> str:
    # A `_posthog/progress` notification. The workflow's failure/cancel handlers emit one with
    # status="failed" BEFORE the TaskRun reaches its terminal status — that line must stay decisive
    # in the dropped-finalization tail check, not be skipped as informational setup progress.
    return json.dumps(
        {
            "notification": {
                "method": "_posthog/progress",
                "params": {"step": step, "status": status, "label": label, "group": "setup"},
            }
        }
    )


def _cost_less_usage_update_line(used: int = 1000) -> str:
    # Older sandbox builds omit cost entirely — must NOT read as the null-cost fingerprint.
    return json.dumps(
        {
            "notification": {
                "method": "session/update",
                "params": {"update": {"sessionUpdate": "usage_update", "used": used}},
            }
        }
    )


@dataclass
class FakeTaskRun:
    id: str = "run-1"
    log_url: str = "s3://fake/log"
    status: str = "running"
    error_message: str | None = None
