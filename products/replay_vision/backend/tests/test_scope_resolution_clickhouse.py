import datetime as dt

import pytest
from freezegun import freeze_time
from posthog.test.base import ClickhouseTestMixin

from posthog.schema import RecordingsQuery

from posthog.clickhouse.client import sync_execute
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.session_recordings.sql.session_replay_event_sql import TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL

from products.replay_vision.backend.queries.scanner_volume_estimate import (
    PREVIEW_ESTIMATE_BUDGET,
    estimate_scanner_session_volume,
)
from products.replay_vision.backend.queries.visited_paths import fetch_matching_paths

_NOW = dt.datetime(2026, 5, 1, 12, 0, 0, tzinfo=dt.UTC)


def _visited_page(*values: str) -> dict:
    return {"type": "recording", "key": "visited_page", "value": list(values), "operator": "icontains"}


@freeze_time(_NOW.strftime("%Y-%m-%dT%H:%M:%SZ"))
class TestTopVisitedPaths(ClickhouseTestMixin):
    def setup_method(self, _method) -> None:
        sync_execute(TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL())

    @staticmethod
    def _produce(
        team_id: int,
        session_id: str,
        urls: list[str],
        ago: dt.timedelta = dt.timedelta(hours=1),
        active_milliseconds: int = 30_000,
        length: dt.timedelta = dt.timedelta(minutes=1),
    ) -> None:
        start = _NOW - ago
        produce_replay_summary(
            team_id=team_id,
            session_id=session_id,
            first_timestamp=start.isoformat(),
            last_timestamp=(start + length).isoformat(),
            all_urls=urls,
            # Clears the eligibility floor by default, so tests about ranking are not silently
            # emptied by the eligibility filter.
            active_milliseconds=active_milliseconds,
        )

    @pytest.mark.django_db
    def test_paths_ranked_by_distinct_sessions(self, team) -> None:
        self._produce(team.id, "a", ["https://ex.test/billing"])
        self._produce(team.id, "b", ["https://ex.test/billing"])
        # Same session, a second raw row: one session, not two.
        self._produce(team.id, "b", ["https://ex.test/billing"], ago=dt.timedelta(minutes=30))
        self._produce(team.id, "c", ["https://ex.test/rare"])

        results = fetch_matching_paths(team=team, terms=["billing", "rare", "deep", "land", "anci"])

        assert [(r.pathname, r.sessions) for r in results] == [("/billing", 2), ("/rare", 1)]

    @pytest.mark.django_db
    def test_urls_normalize_to_path(self, team) -> None:
        self._produce(team.id, "a", ["https://app.ex.test/billing?tab=1", "https://other.ex.test/billing"])

        results = fetch_matching_paths(team=team, terms=["billing", "rare", "deep", "land", "anci"])

        assert [(r.pathname, r.sessions) for r in results] == [("/billing", 1)]

    @pytest.mark.django_db
    def test_paths_outside_the_window_are_excluded(self, team) -> None:
        self._produce(team.id, "recent", ["https://ex.test/billing"])
        self._produce(team.id, "stale", ["https://ex.test/ancient"], ago=dt.timedelta(days=8))

        results = fetch_matching_paths(team=team, terms=["billing", "rare", "deep", "land", "anci"])

        assert [r.pathname for r in results] == ["/billing"]

    @pytest.mark.django_db
    def test_a_quiet_page_is_found_among_far_busier_ones(self, team) -> None:
        # A page that launched yesterday has almost no traffic. Selecting candidates by volume would
        # hide it behind every popular page, so a team could never scan their newest flow.
        self._produce(team.id, "new", ["https://ex.test/billing-v2"])
        for i in range(50):
            self._produce(team.id, f"busy-{i}", ["https://ex.test/home"])

        results = fetch_matching_paths(team=team, terms=["bill"], limit=5)

        assert [(r.pathname, r.sessions) for r in results] == [("/billing-v2", 1)]

    @pytest.mark.django_db
    def test_volume_orders_the_matches(self, team) -> None:
        # Volume still decides which matching page the caller most likely meant.
        self._produce(team.id, "quiet", ["https://ex.test/billing-legacy"])
        for i in range(3):
            self._produce(team.id, f"main-{i}", ["https://ex.test/billing"])

        results = fetch_matching_paths(team=team, terms=["bill"])

        assert [r.pathname for r in results] == ["/billing", "/billing-legacy"]

    @pytest.mark.django_db
    def test_sessions_a_scanner_cannot_observe_are_not_counted(self, team) -> None:
        # A landing page collects many short bounces. Counting them overstates the volume and
        # outranks pages whose sessions a scanner would actually watch.
        self._produce(team.id, "watchable", ["https://ex.test/deep"])
        for i in range(5):
            self._produce(
                team.id,
                f"bounce-{i}",
                ["https://ex.test/landing"],
                active_milliseconds=1_000,
                length=dt.timedelta(seconds=3),
            )

        results = fetch_matching_paths(team=team, terms=["billing", "rare", "deep", "land", "anci"])

        assert [(r.pathname, r.sessions) for r in results] == [("/deep", 1)]


@freeze_time(_NOW.strftime("%Y-%m-%dT%H:%M:%SZ"))
class TestVisitedPageFilterSemantics(ClickhouseTestMixin):
    """The invariant the resolver's filter shape rests on: one multi-value property ORs, several AND.

    Asserted against real ClickHouse rather than by reading `posthog/hogql/property.py`, because the
    compilation lives upstream of this product. If a change there ever made a multi-value
    `visited_page` AND its values, every filter the resolver builds would quietly match almost
    nothing, and no amount of testing the resolver's own output would show it.
    """

    def setup_method(self, _method) -> None:
        sync_execute(TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL())

    @staticmethod
    def _produce(team_id: int, session_id: str, url: str) -> None:
        start = _NOW - dt.timedelta(hours=1)
        produce_replay_summary(
            team_id=team_id,
            session_id=session_id,
            first_timestamp=start.isoformat(),
            last_timestamp=(start + dt.timedelta(minutes=1)).isoformat(),
            all_urls=[url],
            # Clear the eligibility floor the estimate applies, so the counts reflect the filter alone.
            active_milliseconds=30_000,
        )

    @staticmethod
    def _count(team, properties: list[dict]) -> int:
        query = RecordingsQuery.model_validate({"kind": "RecordingsQuery", "properties": properties})
        return estimate_scanner_session_volume(team=team, query=query, budget=PREVIEW_ESTIMATE_BUDGET).matched_sessions

    @pytest.mark.django_db
    def test_one_multi_value_property_ors_where_separate_properties_and(self, team) -> None:
        # Each session touches exactly one of the three pages, so nothing can satisfy all three.
        self._produce(team.id, "cart", "https://ex.test/cart")
        self._produce(team.id, "checkout", "https://ex.test/checkout")
        self._produce(team.id, "payment", "https://ex.test/payment")

        one_property = self._count(team, [_visited_page("/cart", "/checkout", "/payment")])
        separate_properties = self._count(team, [_visited_page(p) for p in ("/cart", "/checkout", "/payment")])
        single_page = self._count(team, [_visited_page("/cart")])

        assert one_property == 3
        assert separate_properties == 0
        assert single_page == 1
