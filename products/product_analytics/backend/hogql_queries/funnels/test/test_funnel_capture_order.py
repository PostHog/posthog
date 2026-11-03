from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    cleanup_materialized_columns,
    flush_persons_and_events,
    materialized,
)
from unittest.mock import patch

from django.conf import settings

from parameterized import parameterized

from posthog.schema import EventsNode, FunnelsFilter, FunnelsQuery

from products.product_analytics.backend.hogql_queries.funnels.funnels_query_runner import FunnelsQueryRunner

BASE = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)


def _iso(at: datetime) -> str:
    return at.isoformat().replace("+00:00", "Z")


class CaptureOrderTestMixin(ClickhouseTestMixin, APIBaseTest):
    def _event(
        self,
        name: str,
        stored_at: datetime,
        captured_at: datetime | None,
        lib: str = "web",
        device_id: str = "dev-a",
        device_model: str = "",
        distinct_id: str = "u1",
    ) -> None:
        props: dict[str, Any] = {"$lib": lib}
        if device_id:
            props["$device_id"] = device_id
        if device_model:
            props["$device_model"] = device_model
        if captured_at is not None:
            props["$client_capture_time"] = _iso(captured_at)
        _create_event(team=self.team, event=name, distinct_id=distinct_id, timestamp=stored_at, properties=props)

    def _funnel(self, use_capture_order: bool, steps: list[str], viz_type: str = "steps") -> list:
        # The funnel context resolves modifiers from the team, which is how this ships. A modifier
        # set on the query object alone does not reach it.
        self.team.modifiers = {"funnelUseClientCaptureOrder": use_capture_order}
        self.team.save()
        query = FunnelsQuery(
            series=[EventsNode(event=step) for step in steps],
            dateRange={"date_from": "2026-01-15", "date_to": "2026-01-17"},
            interval="day",
            funnelsFilter=FunnelsFilter(funnelVizType=viz_type),
        )
        return FunnelsQueryRunner(query=query, team=self.team, just_summarize=viz_type == "trends").calculate().results


class TestFunnelCaptureOrder(CaptureOrderTestMixin):
    def _given_an_out_of_order_device(
        self,
        captured: bool = True,
        lib: str = "web",
        device_id: str = "dev-a",
        device_model: str = "",
    ) -> None:
        _create_person(distinct_ids=["u1"], team_id=self.team.pk)
        second = BASE + timedelta(seconds=5)
        common: dict[str, Any] = {"lib": lib, "device_id": device_id, "device_model": device_model}
        self._event("step one", second + timedelta(seconds=20), BASE if captured else None, **common)
        self._event("step two", second + timedelta(milliseconds=200), second if captured else None, **common)
        flush_persons_and_events()

    @parameterized.expand(
        [
            ("stored_order_drops_the_user", False, "web", "dev-a", "", 0),
            ("browser_device", True, "web", "dev-a", "", 1),
            ("browser_without_device_id", True, "web", "", "", 1),
            ("mobile_without_device_id", True, "posthog-ios", "", "iPhone15,2", 1),
            ("server_sdk_keeps_stored_order", True, "posthog-python", "dev-a", "", 0),
        ]
    )
    def test_out_of_order_delivery(
        self, _name: str, use_capture_order: bool, lib: str, device_id: str, device_model: str, expected_step_two: int
    ) -> None:
        self._given_an_out_of_order_device(lib=lib, device_id=device_id, device_model=device_model)

        results = self._funnel(use_capture_order, ["step one", "step two"])

        assert results[0]["count"] == 1
        assert results[1]["count"] == expected_step_two

    @parameterized.expand(
        [
            ("no_capture_instant_recorded", False, 10_000),
            ("anchor_group_over_the_cap", True, 1),
        ]
    )
    def test_falls_back_to_stored_order(self, _name: str, captured: bool, cap: int) -> None:
        self._given_an_out_of_order_device(captured=captured)

        with patch("products.product_analytics.backend.hogql_queries.funnels.base.MAX_EVENTS_PER_CAPTURE_ANCHOR", cap):
            results = self._funnel(True, ["step one", "step two"])

        assert results[0]["count"] == 1
        assert results[1]["count"] == 0

    def test_trends_use_the_capture_order(self) -> None:
        self._given_an_out_of_order_device()

        results = self._funnel(True, ["step one", "step two"], viz_type="trends")

        by_day = {row["timestamp"].date(): row for row in results}
        assert by_day[BASE.date()]["reached_from_step_count"] == 1
        assert by_day[BASE.date()]["reached_to_step_count"] == 1


class TestFunnelCaptureOrderAnchorGroups(CaptureOrderTestMixin):
    def test_two_devices_sharing_a_distinct_id_keep_separate_anchors(self) -> None:
        _create_person(distinct_ids=["u1"], team_id=self.team.pk)
        # Device A's clock is right. Device B's clock is 60 s slow, which capture's per-request
        # correction removes from the stored timestamp but not from the capture instant. One shared
        # anchor would apply A's offset to B and move step two a minute before step one.
        self._event(
            "step one", BASE + timedelta(milliseconds=200), BASE, lib="posthog-android", device_id="", device_model="A"
        )
        step_two_at = BASE + timedelta(seconds=5)
        self._event(
            "step two",
            step_two_at + timedelta(milliseconds=200),
            step_two_at - timedelta(seconds=60),
            lib="posthog-android",
            device_id="",
            device_model="B",
        )
        flush_persons_and_events()

        results = self._funnel(True, ["step one", "step two"])

        assert results[1]["count"] == 1

    def test_a_clock_corrected_overnight_anchors_each_day_separately(self) -> None:
        _create_person(distinct_ids=["u1"], team_id=self.team.pk)
        # The clock runs 2 h fast on day one and is corrected before day two. One anchor across both
        # days would take day one's offset and move step two two hours back, ahead of step one.
        step_one_at = datetime(2026, 1, 15, 23, 0, 0, tzinfo=UTC)
        step_two_at = datetime(2026, 1, 16, 0, 30, 0, tzinfo=UTC)
        self._event("step one", step_one_at + timedelta(milliseconds=200), step_one_at + timedelta(hours=2))
        self._event("step two", step_two_at + timedelta(milliseconds=200), step_two_at)
        flush_persons_and_events()

        results = self._funnel(True, ["step one", "step two"])

        assert results[1]["count"] == 1

    @parameterized.expand(
        [
            ("stored_order", False, 1),
            ("capture_order", True, 1),
        ]
    )
    def test_uncovered_row_between_two_covered_ones(
        self, _name: str, use_capture_order: bool, expected_step_three: int
    ) -> None:
        _create_person(distinct_ids=["u1"], team_id=self.team.pk)
        # a's 1 s latency is the smallest in the group, so correcting only the covered rows would
        # pull c back to 12:00:05, ahead of the uncorrected b at 12:00:06. The whole group therefore
        # keeps the stored timestamp.
        self._event("a", BASE + timedelta(seconds=1), BASE)
        self._event("b", BASE + timedelta(seconds=6), None)
        self._event("c", BASE + timedelta(seconds=20), BASE + timedelta(seconds=4))
        flush_persons_and_events()

        results = self._funnel(use_capture_order, ["a", "b", "c"])

        assert results[0]["count"] == 1
        assert results[1]["count"] == 1
        assert results[2]["count"] == expected_step_three


class TestFunnelCaptureOrderUsesMaterializedColumn(ClickhouseTestMixin, APIBaseTest):
    def _funnel_sql(self) -> str:
        self.team.modifiers = {"funnelUseClientCaptureOrder": True}
        self.team.save()
        query = FunnelsQuery(
            series=[EventsNode(event="step one"), EventsNode(event="step two")],
            dateRange={"date_from": "2026-01-15", "date_to": "2026-01-16"},
        )
        with self.capture_select_queries() as queries:
            FunnelsQueryRunner(query=query, team=self.team).calculate()
        return "\n".join(queries)

    @parameterized.expand([("not_nullable", False), ("nullable", True)])
    def test_reads_the_materialized_column_when_one_exists(self, _name: str, is_nullable: bool) -> None:
        # The Dagster job that creates these defaults to a nullable column, so the query has to
        # hold for both shapes.
        _create_person(distinct_ids=["u1"], team_id=self.team.pk)
        flush_persons_and_events()
        self.addCleanup(cleanup_materialized_columns)

        with materialized("events", "$client_capture_time", is_nullable=is_nullable) as column:
            sql = self._funnel_sql()

        if settings.CLICKHOUSE_HOGQL_USE_NEW_EVENTS_SCHEMA:
            # The JSON events table keeps each property path as its own subcolumn and takes no
            # materialized columns, so the read is already cheap there.
            assert "events_json" in sql
            return
        assert column.name in sql, f"expected {column.name} in the query"
        assert "$client_capture_time" not in sql.replace(column.name, ""), (
            "the property is still being extracted from the properties JSON"
        )

    def test_falls_back_to_the_json_read_without_one(self) -> None:
        _create_person(distinct_ids=["u1"], team_id=self.team.pk)
        flush_persons_and_events()

        sql = self._funnel_sql()

        # Records the cost the migration removes, so the two tests read as a pair.
        assert "$client_capture_time" in sql
