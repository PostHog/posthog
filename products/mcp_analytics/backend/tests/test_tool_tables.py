from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from parameterized import parameterized

from posthog.schema import (
    DateRange,
    IntervalType,
    MCPToolDailyStatsQuery,
    MCPToolDescriptionsQuery,
    MCPToolFailureOccurrencesQuery,
    MCPToolFailuresQuery,
    MCPToolNeighborsQuery,
    MCPToolSampleIntentsQuery,
    MCPToolStatsQuery,
    MCPToolTopUsersQuery,
    NeighborDirection,
)

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.mcp_analytics.backend.hogql_queries.tool_tables import (
    MCPToolDailyStatsQueryRunner,
    MCPToolDescriptionsQueryRunner,
    MCPToolFailureOccurrencesQueryRunner,
    MCPToolFailuresQueryRunner,
    MCPToolNeighborsQueryRunner,
    MCPToolSampleIntentsQueryRunner,
    MCPToolStatsQueryRunner,
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
    def _emit(
        self,
        *,
        tool_name: str = "query_run",
        distinct_id: str = "d1",
        client_name: str | None = None,
        source: str | None = NEW_SDK_SOURCE,
        is_error: bool = True,
        error_type: str | None = None,
        error_status: str | None = None,
        exec_tool: str | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        properties: dict[str, Any] = {"$mcp_tool_name": tool_name, "$mcp_is_error": is_error}
        if source is not None:
            properties["$mcp_source"] = source
        if client_name is not None:
            properties["$mcp_client_name"] = client_name
        if error_type is not None:
            properties["$mcp_error_type"] = error_type
        if error_status is not None:
            properties["$mcp_error_status"] = error_status
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
        runner = MCPToolFailuresQueryRunner(
            query=MCPToolFailuresQuery(toolName=tool_name, dateRange=DateRange(date_from="-7d")),
            team=self.team,
        )
        return runner.calculate().results

    @parameterized.expand(
        [
            ("type_and_status", "api_5xx", "500", "api_5xx (HTTP 500)", "api_5xx", "500"),
            ("type_only", "validation", None, "validation", "validation", ""),
            ("neither_falls_back_to_unknown", None, None, "unknown", "unknown", ""),
            # Event-supplied fields are unbounded; the label must be capped so an attacker
            # emitting huge unique values can't inflate the grouping key and response size.
            ("long_type_truncated_to_200_chars", "x" * 300, None, "x" * 200, "x" * 200, ""),
        ]
    )
    def test_composes_failure_label(
        self,
        _name: str,
        error_type: str | None,
        error_status: str | None,
        expected: str,
        expected_type: str,
        expected_status: str,
    ) -> None:
        self._emit(error_type=error_type, error_status=error_status, client_name="claude-ai")
        flush_persons_and_events()

        rows = self._run()

        assert len(rows) == 1
        assert rows[0].message == expected
        # Raw bucket parts ride along so the drill-down can requery the bucket without parsing the label.
        assert rows[0].error_type == expected_type
        assert rows[0].error_status == expected_status

    def test_only_counts_errored_calls(self) -> None:
        # The fix's core behavior: failures are sourced from $mcp_is_error on $mcp_tool_call,
        # so successful calls must never appear (they did when the table read $exception events).
        self._emit(is_error=False, error_type="validation", client_name="claude-ai")
        self._emit(is_error=True, error_type="internal", client_name="claude-ai")
        flush_persons_and_events()

        assert [r.message for r in self._run()] == ["internal"]

    def test_groups_by_label_dedupes_harnesses_and_counts(self) -> None:
        self._emit(error_type="internal", client_name="claude-ai")
        self._emit(error_type="internal", client_name="cursor-vscode")
        self._emit(error_type="validation", client_name="claude-ai")
        flush_persons_and_events()

        by_label = {r.message: r for r in self._run()}

        assert by_label["internal"].occurrences == 2
        assert by_label["internal"].harnesses == ["Claude.ai", "Cursor"]
        assert by_label["validation"].occurrences == 1

    def test_excludes_other_tools_and_resolves_effective_tool_name(self) -> None:
        self._emit(tool_name="other_tool", error_type="internal", client_name="claude-ai")
        # Single-exec wrapper: the effective tool is in $mcp_exec_tool_call_name, not $mcp_tool_name.
        self._emit(tool_name="exec", exec_tool="query_run", error_type="validation", client_name="cursor-vscode")
        flush_persons_and_events()

        assert [r.message for r in self._run(tool_name="query_run")] == ["validation"]

    def test_excludes_events_without_new_sdk_source(self) -> None:
        self._emit(source=None, error_type="internal", client_name="claude-ai")
        flush_persons_and_events()

        assert self._run() == []

    def test_date_range_excludes_older_events(self) -> None:
        now = datetime.now(tz=UTC)
        self._emit(error_type="internal", timestamp=now - timedelta(days=30))
        self._emit(error_type="validation", timestamp=now)
        flush_persons_and_events()

        assert {r.message for r in self._run()} == {"validation"}


class TestMCPToolFailureOccurrencesQueryRunner(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def _emit(
        self,
        *,
        tool_name: str = "query_run",
        distinct_id: str = "d1",
        client_name: str | None = None,
        source: str | None = NEW_SDK_SOURCE,
        is_error: bool = True,
        error_type: str | None = None,
        error_status: str | None = None,
        error_message: str | None = None,
        session_id: str | None = None,
        intent: str | None = None,
        exec_tool: str | None = None,
        timestamp: datetime | None = None,
    ) -> None:
        properties: dict[str, Any] = {"$mcp_tool_name": tool_name, "$mcp_is_error": is_error}
        if source is not None:
            properties["$mcp_source"] = source
        if client_name is not None:
            properties["$mcp_client_name"] = client_name
        if error_type is not None:
            properties["$mcp_error_type"] = error_type
        if error_status is not None:
            properties["$mcp_error_status"] = error_status
        if error_message is not None:
            properties["$mcp_error_message"] = error_message
        if session_id is not None:
            properties["$mcp_session_id"] = session_id
        if intent is not None:
            properties["$mcp_intent"] = intent
        if exec_tool is not None:
            properties["$mcp_exec_tool_call_name"] = exec_tool
        _create_event(
            team=self.team,
            event="$mcp_tool_call",
            distinct_id=distinct_id,
            timestamp=timestamp or datetime.now(tz=UTC),
            properties=properties,
        )

    def _run(self, error_type: str, error_status: str | None = None, tool_name: str = "query_run") -> list[Any]:
        runner = MCPToolFailureOccurrencesQueryRunner(
            query=MCPToolFailureOccurrencesQuery(
                toolName=tool_name,
                errorType=error_type,
                errorStatus=error_status,
                dateRange=DateRange(date_from="-7d"),
            ),
            team=self.team,
        )
        return runner.calculate().results

    @parameterized.expand(
        [
            # The no-status branch must not match statused events in the same error type, and vice versa.
            ("statused_bucket", "api_5xx", "500", {"d500"}),
            ("no_status_bucket_within_type", "api_5xx", None, {"dnostatus"}),
            ("typeless_events_form_unknown_bucket", "unknown", None, {"dtypeless"}),
        ]
    )
    def test_filters_to_exactly_one_bucket(
        self, _name: str, query_type: str, query_status: str | None, expected_ids: set[str]
    ) -> None:
        self._emit(distinct_id="d500", error_type="api_5xx", error_status="500")
        self._emit(distinct_id="d502", error_type="api_5xx", error_status="502")
        self._emit(distinct_id="dnostatus", error_type="api_5xx")
        self._emit(distinct_id="dtypeless")
        self._emit(distinct_id="dother", error_type="internal")
        flush_persons_and_events()

        rows = self._run(query_type, query_status)

        assert {r.distinct_id for r in rows} == expected_ids

    def test_carries_event_fields_newest_first_with_empty_message_fallback(self) -> None:
        now = datetime.now(tz=UTC)
        self._emit(
            distinct_id="d1",
            error_type="internal",
            error_message="boom: table not found",
            session_id="conv1",
            intent='{"goal":"x"}',
            client_name="claude-ai (via mcp-remote 0.1.37)",
            timestamp=now,
        )
        # Pre-capture event: no $mcp_error_message on the event must surface as an empty string.
        # '{}' is the SDK's no-intent sentinel — normalized to empty like the sibling runners.
        self._emit(distinct_id="d2", error_type="internal", intent="{}", timestamp=now - timedelta(minutes=5))
        flush_persons_and_events()

        rows = self._run("internal")

        assert [r.distinct_id for r in rows] == ["d1", "d2"]
        assert rows[0].error_message == "boom: table not found"
        assert rows[0].session_id == "conv1"
        assert "goal" in rows[0].intent
        assert rows[0].harness == "Claude.ai"
        assert rows[1].error_message == ""
        assert rows[1].intent == ""

    def test_caps_event_supplied_session_id_and_intent_lengths(self) -> None:
        self._emit(
            distinct_id="d1",
            error_type="internal",
            session_id="s" * 500,
            intent='{"goal":"' + "x" * 2000 + '"}',
        )
        flush_persons_and_events()

        rows = self._run("internal")

        assert len(rows) == 1
        assert len(rows[0].session_id) == 200
        assert len(rows[0].intent) == 1000

    @parameterized.expand(
        [
            (["query:read"], 403),
            (["mcp_analytics:read"], 403),
            (["query:read", "mcp_analytics:read"], 200),
        ]
    )
    def test_query_endpoint_scope_parity_for_api_keys(self, scopes: list[str], expected_status: int) -> None:
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="test", user=self.user, secure_value=hash_key_value(value), scopes=scopes)

        response = self.client.post(
            f"/api/projects/{self.team.pk}/query/",
            {"query": {"kind": "MCPToolFailureOccurrencesQuery", "toolName": "query_run", "errorType": "internal"}},
            HTTP_AUTHORIZATION=f"Bearer {value}",
        )

        assert response.status_code == expected_status, response.json()

    def test_excludes_non_errored_other_tools_and_old_sdk_events(self) -> None:
        self._emit(distinct_id="match", error_type="internal")
        self._emit(distinct_id="ok", error_type="internal", is_error=False)
        self._emit(distinct_id="othertool", tool_name="other_tool", error_type="internal")
        self._emit(distinct_id="oldsdk", error_type="internal", source=None)
        # Single-exec wrapper: the effective tool is in $mcp_exec_tool_call_name, not $mcp_tool_name.
        self._emit(distinct_id="viaexec", tool_name="exec", exec_tool="query_run", error_type="internal")
        flush_persons_and_events()

        rows = self._run("internal")

        assert {r.distinct_id for r in rows} == {"match", "viaexec"}


def _emit_tool_call(
    team: Any,
    *,
    tool_name: str = "query_run",
    distinct_id: str = "d1",
    source: str | None = NEW_SDK_SOURCE,
    is_error: bool = False,
    duration_ms: float | None = None,
    intent: str | None = None,
    intent_source: str | None = None,
    description: str | None = None,
    client_name: str | None = None,
    session_id: str | None = None,
    exec_tool: str | None = None,
    timestamp: datetime | None = None,
) -> None:
    properties: dict[str, Any] = {"$mcp_tool_name": tool_name, "$mcp_is_error": is_error}
    if source is not None:
        properties["$mcp_source"] = source
    if duration_ms is not None:
        properties["$mcp_duration_ms"] = duration_ms
    if intent is not None:
        properties["$mcp_intent"] = intent
    if intent_source is not None:
        properties["$mcp_intent_source"] = intent_source
    if description is not None:
        properties["$mcp_tool_description"] = description
    if client_name is not None:
        properties["$mcp_client_name"] = client_name
    if session_id is not None:
        properties["$mcp_session_id"] = session_id
    if exec_tool is not None:
        properties["$mcp_exec_tool_call_name"] = exec_tool
    _create_event(
        team=team,
        event="$mcp_tool_call",
        distinct_id=distinct_id,
        timestamp=timestamp or datetime.now(tz=UTC),
        properties=properties,
    )


class TestMCPToolStatsQueryRunner(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def _run(self, tool_name: str = "query_run") -> list[Any]:
        runner = MCPToolStatsQueryRunner(
            query=MCPToolStatsQuery(toolName=tool_name, dateRange=DateRange(date_from="-7d")),
            team=self.team,
        )
        return runner.calculate().results

    def test_empty_when_no_calls(self) -> None:
        assert self._run() == []

    def test_aggregates_scalars_and_intent_coverage(self) -> None:
        _emit_tool_call(self.team, distinct_id="d1", duration_ms=100, intent='{"goal":"x"}', session_id="s1")
        _emit_tool_call(self.team, distinct_id="d1", duration_ms=300, is_error=True, session_id="s1")
        _emit_tool_call(self.team, distinct_id="d2", duration_ms=200, intent="{}", session_id="s2")
        # Off-tool event must not leak into the aggregation (shared tool filter wiring).
        _emit_tool_call(self.team, distinct_id="d3", tool_name="other", duration_ms=999)
        flush_persons_and_events()

        rows = self._run()

        assert len(rows) == 1
        row = rows[0]
        assert row.calls == 3
        assert row.errors == 1
        assert row.users == 2
        assert row.conversations == 2
        # Only the '{"goal":"x"}' call counts; '{}' and missing do not.
        assert row.with_intent == 1
        assert row.p50_ms is not None and row.p95_ms is not None

    def test_excludes_events_without_new_sdk_source(self) -> None:
        _emit_tool_call(self.team, source=None, duration_ms=100)
        flush_persons_and_events()

        assert self._run() == []


class TestMCPToolDailyStatsQueryRunner(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def _run(self, tool_name: str = "query_run") -> list[Any]:
        runner = MCPToolDailyStatsQueryRunner(
            query=MCPToolDailyStatsQuery(toolName=tool_name, dateRange=DateRange(date_from="-30d")),
            team=self.team,
        )
        return runner.calculate().results

    def test_groups_by_day_in_order(self) -> None:
        now = datetime.now(tz=UTC)
        _emit_tool_call(self.team, distinct_id="d1", session_id="s1", timestamp=now - timedelta(days=2))
        _emit_tool_call(self.team, distinct_id="d2", session_id="s2", timestamp=now)
        _emit_tool_call(self.team, distinct_id="d3", session_id="s3", timestamp=now)
        flush_persons_and_events()

        rows = self._run()

        assert len(rows) == 2
        assert rows[0].day < rows[1].day
        assert rows[0].calls == 1
        assert rows[1].calls == 2
        assert rows[1].sessions == 2

    def test_buckets_by_hour_when_interval_is_hour(self) -> None:
        # Two calls in the same day but different hours split into two hourly buckets — a sub-day
        # window would otherwise collapse to a single day point. Guards the interval plumbing.
        now = datetime.now(tz=UTC)
        _emit_tool_call(self.team, distinct_id="d1", session_id="s1", timestamp=now - timedelta(hours=1, minutes=30))
        _emit_tool_call(self.team, distinct_id="d2", session_id="s2", timestamp=now - timedelta(minutes=5))
        flush_persons_and_events()

        runner = MCPToolDailyStatsQueryRunner(
            query=MCPToolDailyStatsQuery(
                toolName="query_run", dateRange=DateRange(date_from="-6h"), interval=IntervalType.HOUR
            ),
            team=self.team,
        )
        rows = runner.calculate().results

        assert len(rows) == 2
        assert rows[0].day < rows[1].day
        assert rows[0].calls == 1
        assert rows[1].calls == 1


class TestMCPToolDescriptionsQueryRunner(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def _run(self, tool_name: str = "query_run") -> list[Any]:
        runner = MCPToolDescriptionsQueryRunner(
            query=MCPToolDescriptionsQuery(toolName=tool_name, dateRange=DateRange(date_from="-30d")),
            team=self.team,
        )
        return runner.calculate().results

    def test_distinct_descriptions_most_recent_first(self) -> None:
        now = datetime.now(tz=UTC)
        _emit_tool_call(self.team, description="old desc", timestamp=now - timedelta(days=3))
        _emit_tool_call(self.team, description="old desc", timestamp=now - timedelta(days=2))
        _emit_tool_call(self.team, description="new desc", timestamp=now)
        flush_persons_and_events()

        rows = self._run()

        assert [r.description for r in rows] == ["new desc", "old desc"]

    def test_excludes_empty_descriptions(self) -> None:
        _emit_tool_call(self.team, description="")
        _emit_tool_call(self.team, description="real")
        flush_persons_and_events()

        rows = self._run()

        assert [r.description for r in rows] == ["real"]


class TestMCPToolSampleIntentsQueryRunner(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def _run(self, tool_name: str = "query_run") -> list[Any]:
        runner = MCPToolSampleIntentsQueryRunner(
            query=MCPToolSampleIntentsQuery(toolName=tool_name, dateRange=DateRange(date_from="-7d")),
            team=self.team,
        )
        return runner.calculate().results

    def test_resolves_harness_label_and_carries_source(self) -> None:
        _emit_tool_call(
            self.team, intent='{"goal":"x"}', intent_source="llm", client_name="claude-ai (via mcp-remote 0.1.37)"
        )
        flush_persons_and_events()

        rows = self._run()

        assert len(rows) == 1
        assert rows[0].harness == "Claude.ai"
        assert rows[0].intent_source == "llm"
        # intent round-trips through ClickHouse JSON storage (re-serialized), so assert content not bytes.
        assert "goal" in rows[0].intent

    def test_excludes_empty_or_blank_intent(self) -> None:
        _emit_tool_call(self.team, distinct_id="d1", intent="", client_name="claude-ai")
        _emit_tool_call(self.team, distinct_id="d2", intent="{}", client_name="claude-ai")
        _emit_tool_call(self.team, distinct_id="d3", intent='{"goal":"y"}', client_name="claude-ai")
        flush_persons_and_events()

        rows = self._run()

        assert len(rows) == 1
        assert "goal" in rows[0].intent


class TestMCPToolNeighborsQueryRunner(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def _run(self, direction: NeighborDirection, tool_name: str = "query_run") -> list[Any]:
        runner = MCPToolNeighborsQueryRunner(
            query=MCPToolNeighborsQuery(
                toolName=tool_name, neighborDirection=direction, dateRange=DateRange(date_from="-7d")
            ),
            team=self.team,
        )
        return runner.calculate().results

    @parameterized.expand(
        [
            ("before", NeighborDirection.BEFORE, "tool_a"),
            ("after", NeighborDirection.AFTER, "tool_b"),
        ]
    )
    def test_finds_adjacent_tool_in_conversation(
        self, _name: str, direction: NeighborDirection, expected_neighbor: str
    ) -> None:
        now = datetime.now(tz=UTC)
        _emit_tool_call(self.team, tool_name="tool_a", session_id="conv1", timestamp=now - timedelta(minutes=2))
        _emit_tool_call(self.team, tool_name="query_run", session_id="conv1", timestamp=now - timedelta(minutes=1))
        _emit_tool_call(self.team, tool_name="tool_b", session_id="conv1", timestamp=now)
        flush_persons_and_events()

        rows = self._run(direction)

        assert len(rows) == 1
        assert rows[0].neighbor_tool == expected_neighbor
        assert rows[0].co_occurrences == 1
