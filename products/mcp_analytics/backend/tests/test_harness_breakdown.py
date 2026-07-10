import re
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import (
    DateRange,
    EventPropertyFilter,
    MCPHarnessBreakdownItem,
    MCPHarnessBreakdownQuery,
    PropertyOperator,
)

from posthog.rbac.user_access_control import UserAccessControlError

from products.mcp_analytics.backend import mcp_harness
from products.mcp_analytics.backend.hogql_queries.harness_breakdown import MCPHarnessBreakdownQueryRunner
from products.mcp_analytics.backend.tests import _MCPAnalyticsTeamScopedTestMixin


def test_harness_labels_tuple_matches_multiif_branches() -> None:
    # The tuple and the multiIf are two expressions of one fact (the labels we emit);
    # this keeps them from drifting. Each branch ends `, '<Label>',`; the else arm is 'Other'.
    sql = mcp_harness.harness_label_sql("h")
    emitted = set(re.findall(r"'([^']+)',\s*$", sql, re.MULTILINE)) | {"Other"}
    assert emitted == set(mcp_harness.HARNESS_LABELS)


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

    def test_tool_name_scopes_to_effective_tool_and_new_sdk(self) -> None:
        new_sdk = {"$mcp_source": "posthog_mcp_analytics"}
        self._emit(distinct_id="d1", properties={"$mcp_client_name": "claude-ai", **new_sdk})
        self._emit(
            distinct_id="d2",
            properties={"$mcp_tool_name": "other_tool", "$mcp_client_name": "cursor-vscode", **new_sdk},
        )
        # Single-exec wrapper: the effective tool is in $mcp_exec_tool_call_name.
        self._emit(
            distinct_id="d3",
            properties={
                "$mcp_tool_name": "exec",
                "$mcp_exec_tool_call_name": "query_run",
                "$mcp_client_name": "windsurf",
                **new_sdk,
            },
        )
        # Same tool but missing the new-SDK source marker -> excluded.
        self._emit(distinct_id="d4", properties={"$mcp_client_name": "claude-ai"})
        flush_persons_and_events()

        runner = MCPHarnessBreakdownQueryRunner(
            query=MCPHarnessBreakdownQuery(dateRange=DateRange(date_from="-90d"), toolName="query_run"),
            team=self.team,
        )
        rows = {row.harness: row for row in runner.calculate().results}

        assert set(rows) == {"Claude.ai", "Windsurf"}

    @parameterized.expand(
        [
            ("vendor_cowork", {"mcp_vendor_client": "Cowork"}, "Cowork"),
            ("vendor_claudecode", {"mcp_vendor_client": "ClaudeCode"}, "Claude Code"),
            ("session_codex", {"mcp_session_client_name": "codex-mcp-client"}, "OpenAI Codex"),
            ("session_cursor", {"mcp_session_client_name": "cursor-vscode"}, "Cursor"),
            # The posthog-node MCP analytics SDK reports clientInfo.name as $mcp_client_name,
            # not the hosted server's mcp_session_client_name. Both must classify.
            ("sdk_client_name_claudeai", {"$mcp_client_name": "claude-ai"}, "Claude.ai"),
            (
                "sdk_client_name_mcp_remote_stripped",
                {"$mcp_client_name": "claude-ai (via mcp-remote 0.1.37)"},
                "Claude.ai",
            ),
            ("ua_claude_cli", {"$mcp_client_user_agent": "claude-code/2.1.0 (cli)"}, "Claude Code"),
            (
                "ua_claude_sdk",
                {"$mcp_client_user_agent": "claude-code/2.1.0 (sdk-ts, agent-sdk/0.3)"},
                "Claude Agent SDK",
            ),
            # Surface-specific exacts must win over the generic claude-code prefix.
            (
                "ua_claude_vscode",
                {"$mcp_client_user_agent": "claude-code/2.1.0 (claude-vscode, agent-sdk/0.3)"},
                "Claude Code (VS Code)",
            ),
            (
                "ua_claude_desktop",
                {"$mcp_client_user_agent": "claude-code/2.1.0 (claude-desktop, agent-sdk/0.3)"},
                "Claude Desktop",
            ),
            ("ua_openai", {"$mcp_client_user_agent": "openai-mcp/1.0.0"}, "OpenAI"),
            # grok.com Connectors: the grok- UA must beat the generic "connectors-manager"
            # clientInfo.name it also reports, or the vendor is lost to 'Other'.
            (
                "grok_connectors_ua_beats_generic_name",
                {
                    "$mcp_client_user_agent": "grok-connectors-manager/0.1.0",
                    "$mcp_client_name": "connectors-manager",
                },
                "Grok",
            ),
            # xAI API surface: no grok UA, buckets via its grok- clientInfo.name.
            ("grok_shell_client_name", {"$mcp_client_name": "grok-shell-posthog"}, "Grok"),
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

    def test_property_filter_applies(self) -> None:
        # properties is the only user-supplied input reaching the WHERE clause;
        # confirm it actually filters (via property_to_expr), not just passes through.
        self._emit(properties={"mcp_session_client_name": "codex-mcp-client", "$mcp_tool_name": "query_run"})
        self._emit(properties={"mcp_session_client_name": "cursor-vscode", "$mcp_tool_name": "insight_get"})
        flush_persons_and_events()

        runner = MCPHarnessBreakdownQueryRunner(
            query=MCPHarnessBreakdownQuery(
                dateRange=DateRange(date_from="-90d"),
                properties=[
                    EventPropertyFilter(key="$mcp_tool_name", value=["query_run"], operator=PropertyOperator.EXACT)
                ],
            ),
            team=self.team,
        )
        by_harness = {row.harness: row for row in runner.calculate().results}

        assert "OpenAI Codex" in by_harness
        assert "Cursor" not in by_harness

    def test_allows_access_when_flag_enabled(self) -> None:
        # The mixin enables only the mcp-analytics flag, mirroring the DRF gate.
        runner = MCPHarnessBreakdownQueryRunner(query=MCPHarnessBreakdownQuery(), team=self.team, user=self.user)
        assert runner.validate_query_runner_access(self.user) is True

    def test_blocks_access_when_flag_disabled(self) -> None:
        runner = MCPHarnessBreakdownQueryRunner(query=MCPHarnessBreakdownQuery(), team=self.team, user=self.user)
        with patch("posthoganalytics.feature_enabled", return_value=False):
            with self.assertRaises(UserAccessControlError):
                runner.validate_query_runner_access(self.user)
