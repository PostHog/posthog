from datetime import UTC, datetime
from typing import Any

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from parameterized import parameterized

from posthog.schema import DateRange, MCPProtocolVersionBreakdownQuery

from posthog.models import PropertyDefinition

from products.mcp_analytics.backend.hogql_queries.protocol_version_breakdown import (
    PROTOCOL_VERSION_SERIES_LIMIT,
    MCPProtocolVersionBreakdownQueryRunner,
)
from products.mcp_analytics.backend.tests import _MCPAnalyticsTeamScopedTestMixin


class TestMCPProtocolVersionBreakdownQueryRunner(_MCPAnalyticsTeamScopedTestMixin, ClickhouseTestMixin, APIBaseTest):
    def _emit(self, *, properties: dict[str, Any], distinct_id: str) -> None:
        _create_event(
            team=self.team,
            event="$mcp_tool_call",
            distinct_id=distinct_id,
            timestamp=datetime.now(tz=UTC),
            properties={"$mcp_tool_name": "query_run", **properties},
        )

    def _define_as_datetime(self) -> None:
        PropertyDefinition.objects.create(
            team=self.team,
            name="$mcp_protocol_version",
            property_type="DateTime",
            type=PropertyDefinition.Type.EVENT,
        )

    def _emit_calls(self, calls_by_version: dict[str | None, int]) -> None:
        for version, calls in calls_by_version.items():
            properties = {} if version is None else {"$mcp_protocol_version": version}
            for call in range(calls):
                self._emit(distinct_id=f"{version}-{call}", properties=properties)
        flush_persons_and_events()

    def _rows(self) -> list[tuple[str, bool, int]]:
        runner = MCPProtocolVersionBreakdownQueryRunner(
            query=MCPProtocolVersionBreakdownQuery(dateRange=DateRange(date_from="-90d")),
            team=self.team,
        )
        return [(row.protocol_version, row.is_current, row.total_calls) for row in runner.calculate().results]

    @parameterized.expand(
        [
            ("stateless_revision", "2026-07-28", True),
            ("later_revision", "2027-01-15", True),
            ("draft_revision", "draft", True),
            ("legacy_revision", "2025-11-25", False),
            ("date_shaped_non_revision", "2026-01-26", False),
            ("non_date_value", "v2", False),
        ]
    )
    def test_returns_raw_revision_despite_datetime_typed_property(
        self, _name: str, version: str, is_current: bool
    ) -> None:
        self._define_as_datetime()
        self._emit_calls({version: 1})

        assert self._rows() == [(version, is_current, 1)]

    def test_missing_or_blank_revision_is_unknown(self) -> None:
        self._define_as_datetime()
        self._emit(distinct_id="blank", properties={"$mcp_protocol_version": "  "})
        self._emit_calls({None: 1, "2025-06-18": 1})

        assert self._rows() == [("2025-06-18", False, 1), ("Unknown", False, 2)]

    def test_orders_draft_then_dated_newest_first_then_other_values_then_unknown(self) -> None:
        self._emit_calls({"2025-06-18": 50, None: 40, "v2": 30, "2026-07-28": 5, "draft": 1, "2025-11-25": 20})

        assert self._rows() == [
            ("draft", True, 1),
            ("2026-07-28", True, 5),
            ("2025-11-25", False, 20),
            ("2025-06-18", False, 50),
            ("v2", False, 30),
            ("Unknown", False, 40),
        ]

    def test_folds_only_legacy_long_tail_into_other(self) -> None:
        legacy: dict[str | None, int] = {
            f"2024-01-{day:02}": 10 + day for day in range(1, PROTOCOL_VERSION_SERIES_LIMIT + 2)
        }
        self._emit_calls({**legacy, "2026-07-28": 1})

        rows = self._rows()

        assert rows[0] == ("2026-07-28", True, 1)
        assert rows[-1] == ("Other", False, 11 + 12)
        assert len(rows) == PROTOCOL_VERSION_SERIES_LIMIT + 1

    def test_ignores_calls_outside_the_date_range(self) -> None:
        _create_event(
            team=self.team,
            event="$mcp_tool_call",
            distinct_id="out-of-range",
            timestamp=datetime(2000, 1, 1, tzinfo=UTC),
            properties={"$mcp_tool_name": "query_run", "$mcp_protocol_version": "2025-06-18"},
        )
        self._emit_calls({"2025-06-18": 1})

        assert self._rows() == [("2025-06-18", False, 1)]
