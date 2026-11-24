import json
import datetime as dt
from typing import Any

from django.test import SimpleTestCase

from parameterized import parameterized

from products.metrics.backend.dashboard_import.activity import AgentAction, latest_agent_action
from products.metrics.backend.facade.enums import AgentActivityKind

T0 = dt.datetime(2026, 11, 23, 10, 0, tzinfo=dt.UTC)


def _at(seconds: int) -> dt.datetime:
    return T0 + dt.timedelta(seconds=seconds)


def _update(seconds: int, update: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "notification",
        "timestamp": _at(seconds).isoformat(),
        "notification": {"jsonrpc": "2.0", "method": "session/update", "params": {"update": update}},
    }


def _tool_call(
    seconds: int,
    call_id: str,
    *,
    tool: str | None = None,
    raw_input: dict[str, Any] | None = None,
    status: str | None = None,
    session_update: str = "tool_call",
) -> dict[str, Any]:
    update: dict[str, Any] = {"sessionUpdate": session_update, "toolCallId": call_id}
    if tool:
        update["_meta"] = {"claudeCode": {"toolName": tool}}
    if raw_input is not None:
        update["rawInput"] = raw_input
    if status:
        update["status"] = status
    return _update(seconds, update)


def _exec(command: str) -> dict[str, Any]:
    return {"command": command}


def _log(*entries: dict[str, Any]) -> str:
    return "\n".join(json.dumps(entry) for entry in entries)


class TestLatestAgentAction(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "exec_call_with_flags",
                [
                    _tool_call(
                        0,
                        "a",
                        tool="mcp__posthog__exec",
                        raw_input=_exec('call --json metric-names-list {"value": "latency"}'),
                    )
                ],
                AgentAction(
                    kind=AgentActivityKind.SEARCHING_METRICS,
                    started_at=_at(0),
                    last_activity_at=_at(0),
                    subject="latency",
                ),
            ),
            (
                "streamed_input_keeps_the_tool_name",
                [
                    _tool_call(0, "a", tool="mcp__posthog__exec", raw_input={}),
                    _tool_call(
                        2,
                        "a",
                        raw_input=_exec('call metrics-dashboard-panels-validate {"panels": [{}, {}, {}]}'),
                        session_update="tool_call_update",
                    ),
                ],
                AgentAction(
                    kind=AgentActivityKind.CHECKING_PANELS, started_at=_at(0), last_activity_at=_at(2), panel_count=3
                ),
            ),
            (
                "finished_call_is_thinking_from_its_end",
                [
                    _tool_call(0, "a", tool="mcp__posthog__metric-attributes-list", raw_input={"metricName": "up"}),
                    _tool_call(5, "a", status="completed", session_update="tool_call_update"),
                    _update(9, {"sessionUpdate": "agent_thought_chunk", "content": {"type": "text", "text": "…"}}),
                ],
                AgentAction(kind=AgentActivityKind.THINKING, started_at=_at(5), last_activity_at=_at(9)),
            ),
            (
                "parallel_calls_report_the_one_still_running",
                [
                    _tool_call(0, "a", tool="mcp__posthog__query-metrics", raw_input={"query": {}}),
                    _tool_call(1, "b", tool="mcp__posthog__metric-names-list", raw_input={"value": "cpu"}),
                    _tool_call(3, "b", status="completed", session_update="tool_call_update"),
                ],
                AgentAction(kind=AgentActivityKind.RUNNING_QUERY, started_at=_at(0), last_activity_at=_at(3)),
            ),
            (
                "local_read_reads_the_dashboard",
                [_tool_call(0, "a", tool="Read", raw_input={"file_path": "/inputs/dashboard.json"})],
                AgentAction(kind=AgentActivityKind.READING_DASHBOARD, started_at=_at(0), last_activity_at=_at(0)),
            ),
            (
                "infra_frames_are_not_agent_activity",
                [
                    {
                        "type": "notification",
                        "timestamp": _at(0).isoformat(),
                        "notification": {"method": "_posthog/console", "params": {"message": "Refreshed credentials"}},
                    }
                ],
                None,
            ),
        ]
    )
    def test_latest_action(self, _name: str, entries: list[dict[str, Any]], expected: AgentAction | None) -> None:
        assert latest_agent_action(_log(*entries)) == expected
