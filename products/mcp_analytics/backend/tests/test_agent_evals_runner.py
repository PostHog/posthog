import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from unittest.mock import patch

from django.core.management.base import CommandError
from django.test import SimpleTestCase

from mcp.types import CallToolResult, ImageContent, TextContent
from parameterized import parameterized

from products.mcp_analytics.backend.agent_evals import runner
from products.mcp_analytics.backend.agent_evals.agent_loop import AgentTrial, TrialUsage
from products.mcp_analytics.backend.agent_evals.runner import RunConfig, tool_result_text
from products.mcp_analytics.backend.agent_evals.scenarios import Scenario
from products.mcp_analytics.backend.management.commands.run_mcp_evals import _headers

SCENARIO = Scenario(
    id="flags-list-active", intent="List all our active feature flags.", success_criteria="Returns the flags."
)
CONFIG = RunConfig(
    url="http://localhost:8787/mcp?token=secret",
    headers={},
    scenarios=(SCENARIO,),
    trials=1,
    concurrency=1,
    model="claude-opus-5-5",
    effort="medium",
    max_turns=3,
)
ANSWERED = AgentTrial(
    scenario_id=SCENARIO.id,
    trial=1,
    outcome="answered",
    final_text="Two flags.",
    tool_calls=(),
    turns=1,
    usage=TrialUsage(),
    duration_ms=5,
)


class TestRunnerBoundaries(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "query_token",
                "GET https://mcp.example.com/mcp?token=abc failed",
                "GET https://mcp.example.com/mcp failed",
            ),
            (
                "userinfo_in_another_url",
                "redirect to 'http://u:p@other.example.com/x?k=1'",
                "redirect to 'http://other.example.com/x'",
            ),
        ]
    )
    def test_recorded_failures_carry_no_url_credentials(self, _name: str, message: str, expected: str) -> None:
        assert runner.describe_failure(ConnectionError(message)) == expected

    @parameterized.expand(
        [
            (
                "userinfo_and_query_are_dropped",
                "https://user:secret@mcp.example.com/mcp?token=abc#x",
                "https://mcp.example.com/mcp",
            ),
            ("the_port_is_kept", "http://localhost:8787/mcp", "http://localhost:8787/mcp"),
            ("ipv6_keeps_its_brackets", "http://[::1]:8787/mcp", "http://[::1]:8787/mcp"),
        ]
    )
    def test_server_url_is_recorded_without_credentials(self, _name: str, url: str, expected: str) -> None:
        assert runner._without_credentials(url) == expected

    @parameterized.expand(
        [
            ("the_token_becomes_a_bearer_header", [], "tok", {"Authorization": "Bearer tok"}),
            ("an_explicit_authorization_wins", ["authorization: Basic x"], "tok", {"authorization": "Basic x"}),
            ("values_are_trimmed", ["x-posthog-project-id:  2 "], None, {"x-posthog-project-id": "2"}),
        ]
    )
    def test_headers(self, _name: str, raw: list[str], token: str | None, expected: dict[str, str]) -> None:
        assert _headers(raw, token) == expected

    @parameterized.expand([("no_separator", "x-posthog-project-id"), ("empty_name", ": 2")])
    def test_a_malformed_header_is_rejected(self, _name: str, raw: str) -> None:
        with self.assertRaises(CommandError):
            _headers([raw], None)

    @parameterized.expand(
        [
            (
                "text_parts_join_by_line",
                CallToolResult(content=[TextContent(type="text", text="a"), TextContent(type="text", text="b")]),
                "a\nb",
            ),
            (
                "media_is_described_not_inlined",
                CallToolResult(content=[ImageContent(type="image", data="aGk=", mimeType="image/png")]),
                "[image image/png, 4 base64 characters]",
            ),
            (
                "structured_content_fills_an_empty_result",
                CallToolResult(content=[], structuredContent={"count": 2}),
                '{"count": 2}',
            ),
        ]
    )
    def test_tool_result_text(self, _name: str, result: CallToolResult, expected: str) -> None:
        assert tool_result_text(result) == expected


def _session(fail_on: str):
    @asynccontextmanager
    async def session(config: RunConfig) -> AsyncIterator[tuple[object, None]]:
        if fail_on == "open":
            raise ExceptionGroup(
                "unhandled errors in a TaskGroup", [ConnectionError(f"connection refused: {config.url}")]
            )
        yield object(), None
        if fail_on == "close":
            raise ConnectionError("stream closed")

    return session


class TestTrialFailureBoundary(SimpleTestCase):
    @parameterized.expand(
        [
            ("a_teardown_failure_keeps_the_finished_trial", "close", ("answered", None)),
            (
                "an_open_failure_is_an_mcp_error_with_the_real_cause_and_no_token",
                "open",
                ("mcp_error", "connection refused: http://localhost:8787/mcp"),
            ),
        ]
    )
    def test_a_session_failure_stays_inside_its_trial(self, _name: str, fail_on: str, expected: tuple) -> None:
        async def fake_run_trial(*args: object) -> AgentTrial:
            return ANSWERED

        with patch.object(runner, "_mcp_session", _session(fail_on)), patch.object(runner, "run_trial", fake_run_trial):
            trial = asyncio.run(runner._run_scenario(CONFIG, None, [], [], SCENARIO, 1))  # type: ignore[arg-type]

        assert (trial.outcome, trial.error) == expected
