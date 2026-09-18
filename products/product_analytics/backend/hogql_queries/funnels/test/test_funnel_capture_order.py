from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person

from parameterized import parameterized

from posthog.schema import EventsNode, FunnelsQuery

from posthog.uuidt import uuid7

from products.product_analytics.backend.hogql_queries.funnels.funnels_query_runner import FunnelsQueryRunner


class TestFunnelCaptureOrder(ClickhouseTestMixin, APIBaseTest):
    """A device's two events delivered out of order.

    Step one is captured first but its request is slow, so it is stored later than step two,
    which was captured second and delivered fast. The funnel sorts on the stored timestamp, so
    it sees step two before step one and drops the user. Ordering on the capture instant the
    client put in each UUIDv7 restores the real sequence.
    """

    CAPTURED_FIRST = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
    CAPTURED_SECOND = CAPTURED_FIRST + timedelta(seconds=5)

    def _given_an_out_of_order_device(self, device_id: str = "dev-a") -> None:
        _create_person(distinct_ids=["u1"], team_id=self.team.pk)
        # Captured first, delivered slowly, so it is stored after the step that followed it.
        _create_event(
            team=self.team,
            event="step one",
            distinct_id="u1",
            timestamp=self.CAPTURED_SECOND + timedelta(seconds=20),
            event_uuid=str(uuid7(int(self.CAPTURED_FIRST.timestamp() * 1000))),
            properties={"$device_id": device_id} if device_id else {},
        )
        # Captured second, delivered immediately.
        _create_event(
            team=self.team,
            event="step two",
            distinct_id="u1",
            timestamp=self.CAPTURED_SECOND,
            event_uuid=str(uuid7(int(self.CAPTURED_SECOND.timestamp() * 1000))),
            properties={"$device_id": device_id} if device_id else {},
        )

    def _run(self, use_capture_order: bool) -> list:
        # The funnel context resolves modifiers from the team, which is how this ships. A
        # modifier set on the query object alone does not reach it.
        self.team.modifiers = {"funnelUseClientCaptureOrder": use_capture_order}
        self.team.save()
        query = FunnelsQuery(
            series=[EventsNode(event="step one"), EventsNode(event="step two")],
            dateRange={"date_from": "2026-01-15", "date_to": "2026-01-16"},
        )
        return FunnelsQueryRunner(query=query, team=self.team).calculate().results

    @parameterized.expand(
        [
            ("stored_timestamp_order_drops_the_user", False, 0),
            ("capture_order_counts_the_user", True, 1),
        ]
    )
    def test_out_of_order_delivery(self, _name: str, use_capture_order: bool, expected_step_two: int) -> None:
        self._given_an_out_of_order_device()

        results = self._run(use_capture_order)

        assert results[0]["count"] == 1
        assert results[1]["count"] == expected_step_two

    def test_missing_device_id_falls_back_to_stored_order(self) -> None:
        # Without a device id these rows would pool into one offset partition per person, so a
        # second device's floor latency could be applied to this one's clock. They fall back
        # instead, which is the behavior they already have.
        self._given_an_out_of_order_device(device_id="")

        results = self._run(use_capture_order=True)

        assert results[0]["count"] == 1
        assert results[1]["count"] == 0
