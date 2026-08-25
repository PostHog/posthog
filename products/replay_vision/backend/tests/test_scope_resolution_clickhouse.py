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
from products.replay_vision.backend.queries.top_visited_paths import fetch_top_visited_paths

_NOW = dt.datetime(2026, 5, 1, 12, 0, 0, tzinfo=dt.UTC)


def _visited_page(*values: str) -> dict:
    return {"type": "recording", "key": "visited_page", "value": list(values), "operator": "icontains"}


@freeze_time(_NOW.strftime("%Y-%m-%dT%H:%M:%SZ"))
class TestTopVisitedPaths(ClickhouseTestMixin):
    def setup_method(self, _method) -> None:
        sync_execute(TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL())

    @staticmethod
    def _produce(team_id: int, session_id: str, urls: list[str], ago: dt.timedelta = dt.timedelta(hours=1)) -> None:
        start = _NOW - ago
        produce_replay_summary(
            team_id=team_id,
            session_id=session_id,
            first_timestamp=start.isoformat(),
            last_timestamp=(start + dt.timedelta(minutes=1)).isoformat(),
            all_urls=urls,
        )

    @pytest.mark.django_db
    def test_paths_ranked_by_distinct_sessions(self, team) -> None:
        self._produce(team.id, "a", ["https://ex.test/billing"])
        self._produce(team.id, "b", ["https://ex.test/billing"])
        # Same session, a second raw row: one session, not two.
        self._produce(team.id, "b", ["https://ex.test/billing"], ago=dt.timedelta(minutes=30))
        self._produce(team.id, "c", ["https://ex.test/rare"])

        results = fetch_top_visited_paths(team=team)

        assert [(r.pathname, r.sessions) for r in results] == [("/billing", 2), ("/rare", 1)]

    @pytest.mark.django_db
    def test_urls_normalize_to_path(self, team) -> None:
        self._produce(team.id, "a", ["https://app.ex.test/billing?tab=1", "https://other.ex.test/billing"])

        results = fetch_top_visited_paths(team=team)

        assert [(r.pathname, r.sessions) for r in results] == [("/billing", 1)]

    @pytest.mark.django_db
    def test_paths_outside_the_window_are_excluded(self, team) -> None:
        self._produce(team.id, "recent", ["https://ex.test/billing"])
        self._produce(team.id, "stale", ["https://ex.test/ancient"], ago=dt.timedelta(days=8))

        results = fetch_top_visited_paths(team=team)

        assert [r.pathname for r in results] == ["/billing"]


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
