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
from products.replay_vision.backend.queries.visited_paths import fetch_visited_paths

_NOW = dt.datetime(2026, 5, 1, 12, 0, 0, tzinfo=dt.UTC)


def _visited_page(*values: str) -> dict:
    return {"type": "recording", "key": "visited_page", "value": list(values), "operator": "icontains"}


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
        # Clears the eligibility floor by default, so a test about ranking is not quietly emptied by
        # the eligibility filter.
        active_milliseconds=active_milliseconds,
    )


@freeze_time(_NOW.strftime("%Y-%m-%dT%H:%M:%SZ"))
class TestVisitedPaths(ClickhouseTestMixin):
    def setup_method(self, _method) -> None:
        sync_execute(TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL())

    @pytest.mark.django_db
    def test_identifier_segments_collapse_into_one_surface(self, team) -> None:
        # The reason the list fits in a prompt at all. On a real project this is the difference
        # between 991,985 paths and about 117,000: without it, invoice pages crowd out everything else.
        for i in range(6):
            _produce(team.id, f"invoice-{i}", [f"https://ex.test/invoice/{i}"])
        _produce(team.id, "uuid-visit", ["https://ex.test/org/0198f4a1-8c2b-7d3e-9f10-2a3b4c5d6e7f/settings"])
        for i in range(5):
            _produce(team.id, f"settings-{i}", ["https://ex.test/settings"])

        results = fetch_visited_paths(team=team, min_sessions=1)
        by_path = {r.pathname: r.sessions for r in results}

        assert by_path["/invoice/:id"] == 6
        assert by_path["/org/:id/settings"] == 1
        assert by_path["/settings"] == 5

    @pytest.mark.parametrize(
        "path,expected",
        [
            # An ID is a WHOLE segment. A partial match ate the digits off real page names and fed
            # the model paths that exist nowhere: "/2fa" became "/:idfa", "/404" vanished into "/:id".
            ("/2fa", "/2fa"),
            ("/404", "/404"),
            ("/123abc", "/123abc"),
            ("/step1", "/step1"),
            ("/v2/api", "/v2/api"),
            ("/invoice/123/edit", "/invoice/:id/edit"),
            # The shapes the collapse exists for: each would otherwise be one surface per ID.
            ("/project/5f3a9c2e1b4d/settings", "/project/:id/settings"),
            ("/user/01J8ZQ8G3R2Y4W5X6V7T8S9A0B", "/user/:id"),
            ("/replay/0198f4a1-8c2b-7d3e-9f10-2a3b4c5d6e7f", "/replay/:id"),
            # Known limit: short mixed identifiers stay. A rule loose enough to catch 8 characters
            # would also collapse real page names.
            ("/insights/AbC123xY", "/insights/AbC123xY"),
            # A long real word is not a token: every token rule demands a digit.
            ("/internationalization-settings", "/internationalization-settings"),
        ],
    )
    @pytest.mark.django_db
    def test_a_segment_collapses_only_when_it_is_entirely_an_identifier(self, team, path, expected) -> None:
        _produce(team.id, "s", [f"https://ex.test{path}"])

        results = fetch_visited_paths(team=team, min_sessions=1)

        assert [r.pathname for r in results] == [expected]

    @pytest.mark.django_db
    def test_a_fabricated_path_cannot_blow_up_the_prompt(self, team) -> None:
        # Visitors control their own URLs, so one crafted path must not inflate what reaches the model.
        _produce(team.id, "s", ["https://ex.test/" + "a" * 2000])

        results = fetch_visited_paths(team=team, min_sessions=1)

        assert len(results) == 1
        assert len(results[0].pathname) == 256

    @pytest.mark.django_db
    def test_the_list_keeps_the_busiest_paths_up_to_the_limit(self, team) -> None:
        for i in range(4):
            _produce(team.id, f"busy-{i}", ["https://ex.test/busy"])
        for name in ("alpha", "beta", "gamma"):
            _produce(team.id, f"one-{name}", [f"https://ex.test/{name}"])

        results = fetch_visited_paths(team=team, min_sessions=1, limit=2)

        assert [(r.pathname, r.sessions) for r in results] == [("/busy", 4), ("/alpha", 1)]

    @pytest.mark.django_db
    def test_one_person_visit_is_not_a_product_surface(self, team) -> None:
        # Without a floor the list fills with pages one person opened once, and the real surfaces
        # fall off the end of the prompt.
        for i in range(5):
            _produce(team.id, f"real-{i}", ["https://ex.test/billing"])
        _produce(team.id, "one-off", ["https://ex.test/rare-corner"])

        results = fetch_visited_paths(team=team, min_sessions=5)

        assert [r.pathname for r in results] == ["/billing"]

    @pytest.mark.django_db
    def test_busiest_first_and_urls_normalize_to_path(self, team) -> None:
        _produce(team.id, "a", ["https://app.ex.test/billing?tab=1", "https://other.ex.test/billing"])
        _produce(team.id, "b", ["https://ex.test/billing"])
        _produce(team.id, "c", ["https://ex.test/quiet"])

        results = fetch_visited_paths(team=team, min_sessions=1)

        assert [(r.pathname, r.sessions) for r in results] == [("/billing", 2), ("/quiet", 1)]

    @pytest.mark.django_db
    def test_sessions_a_scanner_cannot_observe_are_not_counted(self, team) -> None:
        # A landing page collects many short visits. Counting them overstates the page and puts it
        # above pages whose sessions a scanner would really watch.
        _produce(team.id, "watchable", ["https://ex.test/deep"])
        for i in range(5):
            _produce(
                team.id,
                f"bounce-{i}",
                ["https://ex.test/landing"],
                active_milliseconds=1_000,
                length=dt.timedelta(seconds=3),
            )

        results = fetch_visited_paths(team=team, min_sessions=1)

        assert [(r.pathname, r.sessions) for r in results] == [("/deep", 1)]

    @pytest.mark.django_db
    def test_paths_outside_the_window_are_excluded(self, team) -> None:
        _produce(team.id, "recent", ["https://ex.test/billing"])
        _produce(team.id, "stale", ["https://ex.test/ancient"], ago=dt.timedelta(days=8))

        results = fetch_visited_paths(team=team, min_sessions=1)

        assert [r.pathname for r in results] == ["/billing"]


@freeze_time(_NOW.strftime("%Y-%m-%dT%H:%M:%SZ"))
class TestVisitedPageFilterSemantics(ClickhouseTestMixin):
    """One `visited_page` property holding several values ORs them; several properties AND.

    Whatever writes the scanner's filter — a model, or a person editing it — has to emit the first
    shape. Asserted against real ClickHouse rather than by reading `posthog/hogql/property.py`,
    because that compilation lives upstream of this product: if it ever changed, every filter would
    quietly match almost nothing and no test of our own output would show it.
    """

    def setup_method(self, _method) -> None:
        sync_execute(TRUNCATE_SESSION_REPLAY_EVENTS_TABLE_SQL())

    @staticmethod
    def _count(team, properties: list[dict]) -> int:
        query = RecordingsQuery.model_validate({"kind": "RecordingsQuery", "properties": properties})
        return estimate_scanner_session_volume(team=team, query=query, budget=PREVIEW_ESTIMATE_BUDGET).matched_sessions

    @pytest.mark.django_db
    def test_one_multi_value_property_ors_where_separate_properties_and(self, team) -> None:
        # Each session opens exactly one of the three pages, so nothing can satisfy all three.
        _produce(team.id, "cart", ["https://ex.test/cart"])
        _produce(team.id, "checkout", ["https://ex.test/checkout"])
        _produce(team.id, "payment", ["https://ex.test/payment"])

        one_property = self._count(team, [_visited_page("/cart", "/checkout", "/payment")])
        separate_properties = self._count(team, [_visited_page(p) for p in ("/cart", "/checkout", "/payment")])
        single_page = self._count(team, [_visited_page("/cart")])

        assert one_property == 3
        assert separate_properties == 0
        assert single_page == 1
