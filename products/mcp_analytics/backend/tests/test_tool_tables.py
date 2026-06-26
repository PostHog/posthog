from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from parameterized import parameterized

from posthog.schema import DateRange, MCPToolFailuresQuery, MCPToolTopUsersQuery

from products.mcp_analytics.backend.hogql_queries.tool_tables import (
    MCPToolFailuresQueryRunner,
    MCPToolTopUsersQueryRunner,
)
from products.mcp_analytics.backend.tests import _MCPAnalyticsTeamScopedTestMixin

NEW_SDK_SOURCE = "posthog_mcp_analytics"


class TestMCPToolTopUsersQueryRunner(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def _emit(
        self,
        *,
        tool_name: str = "query_run",
        distinct_id: str = "d1",
        client_name: str | None = None,
        source: str | None = NEW_SDK_SOURCE,
        is_error: bool = False,
        exec_tool: str | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        properties: dict[str, Any] = {
            "$mcp_tool_name": tool_name,
            "$mcp_is_error": is_error,
        }
        if source is not None:
            properties["$mcp_source"] = source
        if client_name is not None:
            properties["$mcp_client_name"] = client_name
        if exec_tool is not None:
            properties["$mcp_exec_tool_call_name"] = exec_tool
        _create_event(
            team=self.team,
            event="$mcp_tool_call",
            distinct_id=distinct_id,
            timestamp=timestamp or datetime.now(tz=UTC),
            properties=properties,
        )

    def _run(self, tool_name: str = "query_run") -> list[Any]:
        runner = MCPToolTopUsersQueryRunner(
            query=MCPToolTopUsersQuery(toolName=tool_name, dateRange=DateRange(date_from="-7d")),
            team=self.team,
        )
        return runner.calculate().results

    @parameterized.expand(
        [
            ("sdk_claudeai", "claude-ai", ["Claude.ai"]),
            ("sdk_mcp_remote_stripped", "claude-ai (via mcp-remote 0.1.37)", ["Claude.ai"]),
            ("sdk_cursor", "cursor-vscode", ["Cursor"]),
            ("sdk_unknown_to_other", "totally-unknown-thing", ["Other"]),
        ]
    )
    def test_resolves_harness_labels(self, _name: str, client_name: str, expected: list[str]) -> None:
        self._emit(client_name=client_name)
        flush_persons_and_events()

        rows = self._run()

        assert len(rows) == 1
        assert rows[0].harnesses == expected

    def test_aggregates_per_user_and_dedupes_harnesses(self) -> None:
        self._emit(distinct_id="d1", client_name="claude-ai", is_error=False)
        self._emit(distinct_id="d1", client_name="claude-ai (via mcp-remote 0.1.37)", is_error=True)
        self._emit(distinct_id="d1", client_name="cursor-vscode", is_error=False)
        flush_persons_and_events()

        rows = self._run()

        assert len(rows) == 1
        row = rows[0]
        assert row.distinct_id == "d1"
        assert row.calls == 3
        assert row.errors == 1
        assert row.error_rate_pct == 33.3
        # Claude.ai once despite two raw spellings; sorted distinct labels.
        assert row.harnesses == ["Claude.ai", "Cursor"]

    def test_excludes_other_tools_and_resolves_effective_tool_name(self) -> None:
        self._emit(distinct_id="d1", tool_name="other_tool", client_name="claude-ai")
        # Single-exec wrapper: outer tool name is the wrapper, the effective tool is in $mcp_exec_tool_call_name.
        self._emit(distinct_id="d2", tool_name="exec", exec_tool="query_run", client_name="cursor-vscode")
        flush_persons_and_events()

        rows = self._run(tool_name="query_run")

        assert {r.distinct_id for r in rows} == {"d2"}

    def test_excludes_events_without_new_sdk_source(self) -> None:
        self._emit(distinct_id="d1", client_name="claude-ai", source=None)
        flush_persons_and_events()

        assert self._run() == []

    def test_carries_person_properties(self) -> None:
        _create_person(team=self.team, distinct_ids=["d1"], properties={"email": "a@b.com"})
        self._emit(distinct_id="d1", client_name="claude-ai")
        flush_persons_and_events()

        rows = self._run()

        assert '"email":"a@b.com"' in rows[0].person_properties.replace(" ", "")
        assert not rows[0].person_properties.startswith('"')  # raw JSON object, not a double-encoded string


class TestMCPToolFailuresQueryRunner(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def _emit_exception(
        self,
        *,
        tool_name: str = "query_run",
        message: str = "boom",
        client_name: str | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        properties: dict[str, Any] = {"$mcp_tool_name": tool_name, "$exception_message": message}
        if client_name is not None:
            properties["$mcp_client_name"] = client_name
        _create_event(
            team=self.team,
            event="$exception",
            distinct_id="d1",
            timestamp=timestamp or datetime.now(tz=UTC),
            properties=properties,
        )

    def _run(self, tool_name: str = "query_run") -> list[Any]:
        runner = MCPToolFailuresQueryRunner(
            query=MCPToolFailuresQuery(toolName=tool_name, dateRange=DateRange(date_from="-7d")),
            team=self.team,
        )
        return runner.calculate().results

    @parameterized.expand(
        [
            ("sdk_claudeai", "claude-ai", ["Claude.ai"]),
            ("sdk_mcp_remote_stripped", "claude-ai (via mcp-remote 0.1.37)", ["Claude.ai"]),
            ("sdk_unknown_to_other", "weird-client", ["Other"]),
        ]
    )
    def test_resolves_harness_labels(self, _name: str, client_name: str, expected: list[str]) -> None:
        self._emit_exception(client_name=client_name)
        flush_persons_and_events()

        rows = self._run()

        assert len(rows) == 1
        assert rows[0].harnesses == expected

    def test_groups_by_message_and_counts_occurrences(self) -> None:
        self._emit_exception(message="boom", client_name="claude-ai")
        self._emit_exception(message="boom", client_name="cursor-vscode")
        self._emit_exception(message="other", client_name="claude-ai")
        flush_persons_and_events()

        rows = self._run()
        by_message = {r.message: r for r in rows}

        assert by_message["boom"].occurrences == 2
        assert by_message["boom"].harnesses == ["Claude.ai", "Cursor"]
        assert by_message["other"].occurrences == 1

    def test_excludes_other_tools(self) -> None:
        self._emit_exception(tool_name="other_tool", message="boom", client_name="claude-ai")
        flush_persons_and_events()

        assert self._run(tool_name="query_run") == []

    def test_date_range_excludes_older_events(self) -> None:
        now = datetime.now(tz=UTC)
        self._emit_exception(message="old", client_name="claude-ai", timestamp=now - timedelta(days=30))
        self._emit_exception(message="recent", client_name="claude-ai", timestamp=now)
        flush_persons_and_events()

        rows = self._run()

        assert {r.message for r in rows} == {"recent"}
