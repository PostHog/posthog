import re
from datetime import UTC, date, datetime
from typing import Any, Optional

import pytest
from freezegun import freeze_time
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.wikipedia_pageviews.settings import (
    ARTICLE_PAGEVIEWS_ENDPOINT,
    DATA_START_DATE,
    MAX_ARTICLES,
    PAGEVIEWS_ENDPOINT,
    TOP_ARTICLES_ENDPOINT,
    WIKIPEDIA_PAGEVIEWS_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.wikipedia_pageviews.wikipedia_pageviews import (
    NO_ARTICLES_ERROR,
    WikipediaPageviewsResumeConfig,
    _coerce_date,
    _get_rows,
    _normalize_project,
    _parse_articles,
    validate_project,
    wikipedia_pageviews_source,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.wikipedia_pageviews.wikipedia_pageviews"


def _response(status: int = 200, json_body: Any = None, text: str = "") -> mock.MagicMock:
    response = mock.MagicMock(spec=requests.Response)
    response.status_code = status
    response.ok = 200 <= status < 300
    response.text = text
    response.json.return_value = json_body if json_body is not None else {}
    return response


def _aggregate_item(timestamp: str, views: int = 100) -> dict[str, Any]:
    return {
        "project": "en.wikipedia",
        "access": "all-access",
        "agent": "user",
        "granularity": "daily",
        "timestamp": timestamp,
        "views": views,
    }


def _manager(resume_state: Optional[WikipediaPageviewsResumeConfig] = None) -> mock.MagicMock:
    manager = mock.MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _run(
    endpoint: str,
    session: mock.MagicMock,
    manager: Optional[mock.MagicMock] = None,
    article_names: Optional[str] = None,
    start_date: Optional[str] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> list[list[dict[str, Any]]]:
    with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
        return list(
            _get_rows(
                project="en.wikipedia.org",
                access="all-access",
                agent="user",
                article_names=article_names,
                start_date=start_date,
                endpoint=endpoint,
                logger=mock.MagicMock(),
                resumable_source_manager=manager if manager is not None else _manager(),
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=db_incremental_field_last_value,
            )
        )


def _requested_ranges(session: mock.MagicMock) -> list[tuple[str, str]]:
    ranges = []
    for call in session.get.call_args_list:
        match = re.search(r"/daily/(\d+)/(\d+)$", call.args[0])
        assert match is not None
        ranges.append((match.group(1), match.group(2)))
    return ranges


class TestHelpers:
    @parameterized.expand(
        [
            ("plain", "en.wikipedia.org", "en.wikipedia.org"),
            ("scheme_and_slash", "https://en.wikipedia.org/", "en.wikipedia.org"),
            ("mixed_case_padded", " EN.Wikipedia.org ", "en.wikipedia.org"),
        ]
    )
    def test_normalize_project(self, _name, value, expected):
        assert _normalize_project(value) == expected

    @parameterized.expand(
        [
            ("none", None, []),
            ("empty", "", []),
            ("commas_and_spaces", "Albert Einstein, Ada Lovelace", ["Albert_Einstein", "Ada_Lovelace"]),
            ("newlines_and_blanks", "Albert Einstein\n\nMarie Curie,", ["Albert_Einstein", "Marie_Curie"]),
            ("dedupes_repeats", "Cat, Cat, Dog, Cat", ["Cat", "Dog"]),
        ]
    )
    def test_parse_articles(self, _name, value, expected):
        assert _parse_articles(value) == expected

    @parameterized.expand(
        [
            ("datetime", datetime(2026, 7, 1, 5, tzinfo=UTC), date(2026, 7, 1)),
            ("date", date(2026, 7, 1), date(2026, 7, 1)),
            ("iso", "2026-07-01", date(2026, 7, 1)),
            ("iso_datetime", "2026-07-01T00:00:00+00:00", date(2026, 7, 1)),
            ("api_hourly", "2026070100", date(2026, 7, 1)),
            ("api_daily", "20260701", date(2026, 7, 1)),
            ("garbage", "not-a-date", None),
            ("none", None, None),
        ]
    )
    def test_coerce_date(self, _name, value, expected):
        assert _coerce_date(value) == expected


class TestPageviews:
    @freeze_time("2026-07-21")
    def test_single_window_rows_get_typed_date_and_state_saved_after_yield(self):
        session = mock.MagicMock(spec=requests.Session)
        session.get.return_value = _response(json_body={"items": [_aggregate_item("2026071800", views=42)]})
        manager = _manager()

        batches = _run(PAGEVIEWS_ENDPOINT, session, manager, start_date="2026-07-18")

        url = session.get.call_args.args[0]
        assert url == (
            "https://wikimedia.org/api/rest_v1/metrics/pageviews/aggregate/en.wikipedia.org"
            "/all-access/user/daily/2026071800/2026072100"
        )
        assert len(batches) == 1
        row = batches[0][0]
        assert row["views"] == 42
        assert row["date"] == datetime(2026, 7, 18, tzinfo=UTC)

        saved = [call.args[0].next_start for call in manager.save_state.call_args_list]
        assert saved == ["2026-07-22"]

    @freeze_time("2026-07-21")
    def test_long_ranges_are_chunked_into_contiguous_windows(self):
        session = mock.MagicMock(spec=requests.Session)
        session.get.return_value = _response(json_body={"items": [_aggregate_item("2024070100")]})
        manager = _manager()

        _run(PAGEVIEWS_ENDPOINT, session, manager, start_date="2024-07-01")

        assert _requested_ranges(session) == [
            ("2024070100", "2025070100"),
            ("2025070200", "2026070200"),
            ("2026070300", "2026072100"),
        ]
        saved = [call.args[0].next_start for call in manager.save_state.call_args_list]
        assert saved == ["2025-07-02", "2026-07-03", "2026-07-22"]

    @freeze_time("2026-07-21")
    def test_start_date_before_data_start_is_clamped(self):
        session = mock.MagicMock(spec=requests.Session)
        session.get.return_value = _response(json_body={"items": []})

        _run(PAGEVIEWS_ENDPOINT, session, start_date="0001-01-01")

        # A pathological early start must not fan out before pageview data exists; the first
        # requested window begins at DATA_START_DATE.
        first_start, _ = _requested_ranges(session)[0]
        assert first_start == f"{DATA_START_DATE:%Y%m%d}00"

    @freeze_time("2026-07-21")
    def test_404_window_is_skipped_and_iteration_continues(self):
        session = mock.MagicMock(spec=requests.Session)
        session.get.side_effect = [
            _response(status=404),
            _response(json_body={"items": [_aggregate_item("2025070200")]}),
            _response(status=404),
        ]

        batches = _run(PAGEVIEWS_ENDPOINT, session, start_date="2024-07-01")

        assert session.get.call_count == 3
        assert len(batches) == 1
        assert batches[0][0]["timestamp"] == "2025070200"

    @freeze_time("2026-07-21")
    def test_incremental_starts_at_watermark_day(self):
        session = mock.MagicMock(spec=requests.Session)
        session.get.return_value = _response(json_body={"items": []})

        _run(
            PAGEVIEWS_ENDPOINT,
            session,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 7, 15, tzinfo=UTC),
        )

        # The watermark day itself is re-fetched (merge dedupes) to pick up late revisions.
        assert _requested_ranges(session) == [("2026071500", "2026072100")]

    @freeze_time("2026-07-21")
    def test_resume_state_takes_precedence_over_incremental_value(self):
        session = mock.MagicMock(spec=requests.Session)
        session.get.return_value = _response(json_body={"items": []})
        manager = _manager(resume_state=WikipediaPageviewsResumeConfig(next_start="2026-07-19"))

        _run(
            PAGEVIEWS_ENDPOINT,
            session,
            manager,
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 7, 1, tzinfo=UTC),
        )

        assert _requested_ranges(session) == [("2026071900", "2026072100")]

    @freeze_time("2026-07-21")
    def test_non_ok_status_raises(self):
        response = _response(status=500, text="server error")
        response.raise_for_status.side_effect = requests.HTTPError
        session = mock.MagicMock(spec=requests.Session)
        session.get.return_value = response

        with pytest.raises(requests.HTTPError):
            _run(PAGEVIEWS_ENDPOINT, session, start_date="2026-07-18")


class TestArticlePageviews:
    @freeze_time("2026-07-21")
    def test_fans_out_per_article_with_encoded_titles(self):
        session = mock.MagicMock(spec=requests.Session)
        session.get.side_effect = [
            _response(
                json_body={
                    "items": [
                        {"project": "en.wikipedia", "article": "Albert_Einstein", "timestamp": "2026071800", "views": 5}
                    ]
                }
            ),
            _response(
                json_body={
                    "items": [{"project": "en.wikipedia", "article": "AC%2FDC", "timestamp": "2026071800", "views": 7}]
                }
            ),
        ]

        batches = _run(
            ARTICLE_PAGEVIEWS_ENDPOINT,
            session,
            article_names="Albert Einstein, AC/DC",
            start_date="2026-07-18",
        )

        urls = [call.args[0] for call in session.get.call_args_list]
        assert urls == [
            "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia.org"
            "/all-access/user/Albert_Einstein/daily/20260718/20260721",
            "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia.org"
            "/all-access/user/AC%2FDC/daily/20260718/20260721",
        ]
        # Both articles' rows land in the same window batch, so the per-batch watermark
        # never advances past a window an article hasn't been fetched for.
        assert len(batches) == 1
        assert [row["views"] for row in batches[0]] == [5, 7]
        assert batches[0][0]["date"] == datetime(2026, 7, 18, tzinfo=UTC)

    def test_raises_without_configured_articles(self):
        with pytest.raises(ValueError, match=NO_ARTICLES_ERROR):
            _run(ARTICLE_PAGEVIEWS_ENDPOINT, mock.MagicMock(spec=requests.Session), article_names="  ,  ")

    @freeze_time("2026-07-21")
    def test_article_titles_capped_at_max_at_runtime(self):
        session = mock.MagicMock(spec=requests.Session)
        session.get.return_value = _response(json_body={"items": []})
        # Single window (start within a year of now), so one request per article — a config
        # stored past the cap must still not fan out beyond MAX_ARTICLES.
        names = ",".join(f"Article_{i}" for i in range(MAX_ARTICLES + 5))

        _run(ARTICLE_PAGEVIEWS_ENDPOINT, session, article_names=names, start_date="2026-07-20")

        assert session.get.call_count == MAX_ARTICLES


class TestTopArticles:
    @freeze_time("2026-07-21")
    def test_flattens_daily_rankings_into_rows(self):
        def day_response(url: str, timeout: int = 0) -> mock.MagicMock:
            match = re.search(r"/top/en\.wikipedia\.org/all-access/(\d{4})/(\d{2})/(\d{2})$", url)
            assert match is not None
            year, month, day = match.groups()
            return _response(
                json_body={
                    "items": [
                        {
                            "project": "en.wikipedia",
                            "access": "all-access",
                            "year": year,
                            "month": month,
                            "day": day,
                            "articles": [
                                {"article": "Main_Page", "views": 1000, "rank": 1},
                                {"article": "Albert_Einstein", "views": 500, "rank": 2},
                            ],
                        }
                    ]
                }
            )

        session = mock.MagicMock(spec=requests.Session)
        session.get.side_effect = day_response
        manager = _manager()

        batches = _run(TOP_ARTICLES_ENDPOINT, session, manager, start_date="2026-07-19")

        # One request per day, all days of the window batched into a single yield.
        assert session.get.call_count == 3
        assert len(batches) == 1
        assert len(batches[0]) == 6

        first = batches[0][0]
        assert first == {
            "project": "en.wikipedia",
            "access": "all-access",
            "year": "2026",
            "month": "07",
            "day": "19",
            "date": datetime(2026, 7, 19, tzinfo=UTC),
            "article": "Main_Page",
            "views": 1000,
            "rank": 1,
        }
        saved = [call.args[0].next_start for call in manager.save_state.call_args_list]
        assert saved == ["2026-07-22"]


class TestValidateProject:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("not_found", 404, False),
            ("server_error", 500, False),
        ]
    )
    def test_status_mapping(self, _name, status, expected_valid):
        with mock.patch(f"{MODULE}.make_tracked_session") as make_session:
            make_session.return_value.get.return_value = _response(status=status)
            is_valid, message = validate_project("en.wikipedia.org", "all-access", "user")

        assert is_valid is expected_valid
        if expected_valid:
            assert message is None
        else:
            assert message is not None

    def test_empty_project_is_invalid_without_network(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as make_session:
            is_valid, message = validate_project("  ", "all-access", "user")

        assert is_valid is False
        assert message is not None
        make_session.return_value.get.assert_not_called()

    def test_network_error_is_not_valid(self):
        with mock.patch(f"{MODULE}.make_tracked_session") as make_session:
            make_session.return_value.get.side_effect = requests.ConnectionError("boom")
            is_valid, message = validate_project("en.wikipedia.org", "all-access", "user")

        assert is_valid is False
        assert message is not None


class TestSourceResponseMetadata:
    @parameterized.expand([(name,) for name in WIKIPEDIA_PAGEVIEWS_ENDPOINTS])
    def test_primary_keys_and_partitioning_per_endpoint(self, endpoint):
        response = wikipedia_pageviews_source(
            project="en.wikipedia.org",
            access="all-access",
            agent="user",
            article_names=None,
            start_date=None,
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=mock.MagicMock(spec=ResumableSourceManager),
        )

        assert response.name == endpoint
        assert response.primary_keys == WIKIPEDIA_PAGEVIEWS_ENDPOINTS[endpoint].primary_keys
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["date"]
        assert response.sort_mode == "asc"
