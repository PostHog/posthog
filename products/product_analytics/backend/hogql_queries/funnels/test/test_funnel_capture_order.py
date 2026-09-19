from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest, ClickhouseTestMixin, _create_event, _create_person, flush_persons_and_events

from parameterized import parameterized

from posthog.schema import EventsNode, FunnelsQuery

from products.product_analytics.backend.hogql_queries.funnels.funnels_query_runner import FunnelsQueryRunner


class TestFunnelCaptureOrder(ClickhouseTestMixin, APIBaseTest):
    """A device's two events delivered out of order.

    Step one is captured first but its request is slow, so it is stored later than step two,
    which was captured second and delivered fast. The funnel sorts on the stored timestamp, so
    it sees step two first and drops the user. Ordering on the capture instant capture recorded
    in `$client_capture_time` restores the real sequence.
    """

    CAPTURED_FIRST = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
    CAPTURED_SECOND = CAPTURED_FIRST + timedelta(seconds=5)

    def _given_an_out_of_order_device(self, device_id: str = "dev-a", with_capture_time: bool = True) -> None:
        _create_person(distinct_ids=["u1"], team_id=self.team.pk)

        def props(captured_at: datetime) -> dict:
            out: dict = {}
            if device_id:
                out["$device_id"] = device_id
            if with_capture_time:
                out["$client_capture_time"] = captured_at.isoformat().replace("+00:00", "Z")
            return out

        # Captured first, delivered slowly, so it is stored after the step that followed it.
        _create_event(
            team=self.team,
            event="step one",
            distinct_id="u1",
            timestamp=self.CAPTURED_SECOND + timedelta(seconds=20),
            properties=props(self.CAPTURED_FIRST),
        )
        # Captured second, delivered promptly.
        _create_event(
            team=self.team,
            event="step two",
            distinct_id="u1",
            timestamp=self.CAPTURED_SECOND + timedelta(milliseconds=200),
            properties=props(self.CAPTURED_SECOND),
        )
        flush_persons_and_events()

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

    @parameterized.expand(
        [
            # Without a device id these rows would pool into one offset partition per person, so
            # another device's floor latency could be applied to this one's clock.
            ("no_device_to_anchor_to", "", True),
            # Capture writes no capture instant when the client sent nothing to derive it from.
            ("no_capture_instant_recorded", "dev-a", False),
        ]
    )
    def test_falls_back_to_stored_order(self, _name: str, device_id: str, with_capture_time: bool) -> None:
        self._given_an_out_of_order_device(device_id=device_id, with_capture_time=with_capture_time)

        results = self._run(use_capture_order=True)

        assert results[0]["count"] == 1
        assert results[1]["count"] == 0


class TestFunnelCaptureOrderPartialCoverage(ClickhouseTestMixin, APIBaseTest):
    """One device whose events do not all carry a capture instant.

    Capture derives `$client_capture_time` from what the client sent, so a device can produce
    some events with it and some without. Correcting only the covered rows moves them earlier
    while the uncovered rows keep their delivery latency, which can reorder a pair that the
    stored timestamp happened to get right.
    """

    BASE = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)

    def _event(self, name: str, captured_offset: float, stored_offset: float, with_capture: bool) -> None:
        props: dict = {"$device_id": "dev-a"}
        if with_capture:
            captured_at = self.BASE + timedelta(seconds=captured_offset)
            props["$client_capture_time"] = captured_at.isoformat().replace("+00:00", "Z")
        _create_event(
            team=self.team,
            event=name,
            distinct_id="u1",
            timestamp=self.BASE + timedelta(seconds=stored_offset),
            properties=props,
        )

    def _run(self, use_capture_order: bool) -> list:
        self.team.modifiers = {"funnelUseClientCaptureOrder": use_capture_order}
        self.team.save()
        query = FunnelsQuery(
            series=[EventsNode(event="a"), EventsNode(event="b"), EventsNode(event="c")],
            dateRange={"date_from": "2026-01-15", "date_to": "2026-01-16"},
        )
        return FunnelsQueryRunner(query=query, team=self.team).calculate().results

    @parameterized.expand(
        [
            # The stored timestamp happens to order these three correctly.
            ("stored_order", False, 1),
            # Correcting only a and c moves c ahead of b, which loses the user at step three.
            ("capture_order", True, 0),
        ]
    )
    def test_uncovered_row_between_two_covered_ones(
        self, _name: str, use_capture_order: bool, expected_step_three: int
    ) -> None:
        _create_person(distinct_ids=["u1"], team_id=self.team.pk)
        # a: captured first, delivered fast. Its 1s latency becomes the device's anchor.
        self._event("a", captured_offset=0, stored_offset=1, with_capture=True)
        # b: captured second, moderate latency, and no capture instant to correct it with.
        self._event("b", captured_offset=2, stored_offset=6, with_capture=False)
        # c: captured third, very slow, corrected back to 12:00:05 by the anchor.
        self._event("c", captured_offset=4, stored_offset=20, with_capture=True)
        flush_persons_and_events()

        results = self._run(use_capture_order)

        # The real order is a, b, c, so a correct funnel counts the user through all three.
        assert results[0]["count"] == 1
        assert results[1]["count"] == 1
        assert results[2]["count"] == expected_step_three
