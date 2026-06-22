from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from posthog.schema import DateRange, MCPHarnessBreakdownItem, MCPHarnessBreakdownQuery

from products.mcp_analytics.backend.hogql_queries.harness_breakdown import MCPHarnessBreakdownQueryRunner
from products.mcp_analytics.backend.tests import _MCPAnalyticsTeamScopedTestMixin


class TestMCPHarnessBreakdownQueryRunner(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def _emit(
        self,
        *,
        properties: dict[str, Any],
        is_error: bool = False,
        session_id: str = "s1",
        distinct_id: str = "d1",
        timestamp: datetime | None = None,
    ) -> None:
        _create_event(
            team=self.team,
            event="$mcp_tool_call",
            distinct_id=distinct_id,
            timestamp=timestamp or datetime.now(tz=UTC),
            properties={
                "$session_id": session_id,
                "$mcp_tool_name": "query_run",
                "$mcp_is_error": is_error,
                **properties,
            },
        )

    def _breakdown(self, date_from: str = "-90d") -> dict[str, MCPHarnessBreakdownItem]:
        runner = MCPHarnessBreakdownQueryRunner(
            query=MCPHarnessBreakdownQuery(dateRange=DateRange(date_from=date_from)),
            team=self.team,
        )
        return {row.harness: row for row in runner.calculate().results}

    @parameterized.expand(
        [
            ("vendor_cowork", {"mcp_vendor_client": "Cowork"}, "Cowork"),
            ("vendor_claudecode", {"mcp_vendor_client": "ClaudeCode"}, "Claude Code"),
            ("session_codex", {"mcp_session_client_name": "codex-mcp-client"}, "OpenAI Codex"),
            ("session_cursor", {"mcp_session_client_name": "cursor-vscode"}, "Cursor"),
            ("ua_claude_cli", {"$mcp_client_user_agent": "claude-code/2.1.0 (cli)"}, "Claude Code"),
            (
                "ua_claude_sdk",
                {"$mcp_client_user_agent": "claude-code/2.1.0 (sdk-ts, agent-sdk/0.3)"},
                "Claude Agent SDK",
            ),
            ("ua_openai", {"$mcp_client_user_agent": "openai-mcp/1.0.0"}, "OpenAI"),
            ("session_librechat", {"mcp_session_client_name": "@librechat/api-client"}, "LibreChat"),
            (
                "mcp_remote_suffix_stripped",
                {"mcp_session_client_name": "codex-mcp-client (via mcp-remote 0.1.37)"},
                "OpenAI Codex",
            ),
            ("oauth_fallback", {"$mcp_oauth_client_name": "lovable"}, "Lovable"),
            ("unknown_to_other", {"mcp_session_client_name": "totally-unknown-thing"}, "Other"),
        ]
    )
    def test_resolves_harness_label(self, _name: str, properties: dict[str, Any], expected: str) -> None:
        self._emit(properties=properties)
        flush_persons_and_events()

        by_harness = self._breakdown()

        assert expected in by_harness, f"expected {expected!r}, got {sorted(by_harness)}"
        assert by_harness[expected].total_calls == 1

    def test_vendor_header_wins_over_generic_session_name(self) -> None:
        # Anthropic's pooled surfaces self-report the generic "Anthropic/ClaudeAI"
        # session name; the vendor header is what separates Cowork from Claude.ai.
        self._emit(properties={"mcp_vendor_client": "Cowork", "mcp_session_client_name": "Anthropic/ClaudeAI"})
        flush_persons_and_events()

        by_harness = self._breakdown()

        assert "Cowork" in by_harness
        assert "Claude.ai" not in by_harness

    def test_aggregates_calls_errors_and_sessions(self) -> None:
        self._emit(properties={"mcp_session_client_name": "codex-mcp-client"}, session_id="a", is_error=False)
        self._emit(properties={"mcp_session_client_name": "codex-mcp-client"}, session_id="a", is_error=True)
        self._emit(properties={"mcp_session_client_name": "codex-mcp-client"}, session_id="b", is_error=False)
        flush_persons_and_events()

        row = self._breakdown()["OpenAI Codex"]

        assert row.total_calls == 3
        assert row.errors == 1
        assert row.sessions == 2
        assert row.error_rate_pct == 33.3

    def test_date_range_excludes_older_events(self) -> None:
        now = datetime.now(tz=UTC)
        self._emit(properties={"mcp_session_client_name": "codex-mcp-client"}, timestamp=now - timedelta(days=30))
        self._emit(properties={"mcp_session_client_name": "cursor-vscode"}, timestamp=now)
        flush_persons_and_events()

        by_harness = self._breakdown(date_from="-7d")

        assert "Cursor" in by_harness
        assert "OpenAI Codex" not in by_harness
