from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events
from unittest.mock import patch

from parameterized import parameterized

from posthog.schema import DateRange, MCPMissingCapabilitiesItem, MCPMissingCapabilitiesQuery

from products.access_control.backend.facade.user_access_control import UserAccessControlError
from products.mcp_analytics.backend.hogql_queries.missing_capabilities import MCPMissingCapabilitiesQueryRunner
from products.mcp_analytics.backend.tests import _MCPAnalyticsTeamScopedTestMixin


class TestMCPMissingCapabilitiesQueryRunner(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def _emit(
        self,
        *,
        intent: str = "export a dashboard as a PDF",
        event: str = "$mcp_missing_capability",
        client_name: str | None = "claude-ai",
        session_id: str = "s1",
        distinct_id: str = "d1",
        timestamp: datetime | None = None,
        event_uuid: UUID | None = None,
    ) -> None:
        properties: dict[str, Any] = {"$session_id": session_id, "$mcp_intent": intent}
        if client_name is not None:
            properties["$mcp_client_name"] = client_name
        _create_event(
            team=self.team,
            event=event,
            distinct_id=distinct_id,
            timestamp=timestamp or datetime.now(tz=UTC),
            properties=properties,
            event_uuid=event_uuid,
        )

    def _run(self, **kwargs: Any) -> list[MCPMissingCapabilitiesItem]:
        return self._response(**kwargs).results

    def _response(self, *, date_from: str = "-30d", **kwargs: Any) -> Any:
        runner = MCPMissingCapabilitiesQueryRunner(
            query=MCPMissingCapabilitiesQuery(dateRange=DateRange(date_from=date_from), **kwargs),
            team=self.team,
        )
        return runner.calculate()

    def test_returns_reports_newest_first_with_their_text(self) -> None:
        now = datetime.now(tz=UTC)
        self._emit(intent="older ask", timestamp=now - timedelta(hours=2))
        self._emit(intent="newer ask", timestamp=now - timedelta(hours=1))
        # Only $mcp_missing_capability is the unmet-demand signal; a tool call carrying an
        # intent is what the agent *did*, not what it couldn't do.
        self._emit(intent="a tool call intent", event="$mcp_tool_call")
        flush_persons_and_events()

        rows = self._run()

        assert [row.intent for row in rows] == ["newer ask", "older ask"]
        assert rows[0].session_id == "s1"
        assert rows[0].distinct_id == "d1"
        assert rows[0].harness == "Claude.ai"

    def test_date_range_excludes_older_reports(self) -> None:
        now = datetime.now(tz=UTC)
        self._emit(intent="last month", timestamp=now - timedelta(days=20))
        self._emit(intent="this week", timestamp=now - timedelta(days=1))
        flush_persons_and_events()

        assert [row.intent for row in self._run(date_from="-7d")] == ["this week"]

    @parameterized.expand(
        [
            ("mixed_case_substring", "DaShBoArD", ["export a dashboard as a PDF"]),
            ("wildcard_is_literal", "%", []),
        ]
    )
    def test_search_filters_reports(self, _name: str, term: str, expected: list[str]) -> None:
        self._emit(intent="export a dashboard as a PDF")
        self._emit(intent="rename a project")
        flush_persons_and_events()

        assert [row.intent for row in self._run(search=term)] == expected

    def test_labels_unidentified_and_self_reported_clients(self) -> None:
        self._emit(intent="no client identity", client_name=None)
        self._emit(intent="self-reported client", client_name="some-inhouse-agent")
        flush_persons_and_events()

        harness_by_intent = {row.intent: row.harness for row in self._run()}

        assert harness_by_intent == {
            "no client identity": "Unidentified client",
            "self-reported client": "some-inhouse-agent",
        }

    def test_pages_equal_timestamps_deterministically(self) -> None:
        now = datetime.now(tz=UTC)
        for index, intent in enumerate(["r1", "r2", "r3"]):
            self._emit(intent=intent, timestamp=now, event_uuid=UUID(int=index + 1))
        flush_persons_and_events()

        first_page = self._response(limit=2, offset=0)
        second_page = self._response(limit=2, offset=2)

        assert [row.intent for row in first_page.results] == ["r3", "r2"]
        assert first_page.has_next is True
        assert [row.intent for row in second_page.results] == ["r1"]
        assert second_page.has_next is False

    def test_carries_only_the_person_fields_the_row_renders(self) -> None:
        _create_person(team=self.team, distinct_ids=["d1"], properties={"email": "a@b.com", "plan": "enterprise"})
        self._emit()
        flush_persons_and_events()

        person_properties = self._run()[0].person_properties

        assert '"email":"a@b.com"' in person_properties.replace(" ", "")
        assert "enterprise" not in person_properties

    def test_blocks_access_when_flag_disabled(self) -> None:
        runner = MCPMissingCapabilitiesQueryRunner(query=MCPMissingCapabilitiesQuery(), team=self.team, user=self.user)
        with patch("posthoganalytics.feature_enabled", return_value=False):
            with self.assertRaises(UserAccessControlError):
                runner.validate_query_runner_access(self.user)
