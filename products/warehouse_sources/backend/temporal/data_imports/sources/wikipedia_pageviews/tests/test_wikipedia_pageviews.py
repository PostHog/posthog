import re
from datetime import UTC, date, datetime
from typing import Any, Literal, Optional

import time_machine

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    RecordedRequest,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.wikipediapageviews import (
    WikipediaPageviewsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.wikipedia_pageviews.settings import (
    ARTICLE_PAGEVIEWS_ENDPOINT,
    COUNTRY_PAGEVIEWS_ENDPOINT,
    COUNTRY_TOP_ARTICLES_ENDPOINT,
    MAX_ARTICLES,
    MAX_COUNTRIES,
    MEDIA_REQUESTS_ENDPOINT,
    PAGEVIEWS_ENDPOINT,
    TOP_ARTICLES_ENDPOINT,
    UNIQUE_DEVICES_ENDPOINT,
    WIKIPEDIA_PAGEVIEWS_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.wikipedia_pageviews.source import (
    WikipediaPageviewsSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.wikipedia_pageviews.wikipedia_pageviews import (
    NO_ARTICLES_ERROR,
    NO_COUNTRIES_ERROR,
    WikipediaPageviewsResumeConfig,
    _coerce_date,
    _normalize_project,
    _parse_articles,
    _parse_countries,
    validate_project,
)


def _response(status: int = 200, json_body: Any = None) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=json_body if json_body is not None else {})


def _aggregate_item(timestamp: str, views: int = 100) -> dict[str, Any]:
    return {
        "project": "en.wikipedia",
        "access": "all-access",
        "agent": "user",
        "granularity": "daily",
        "timestamp": timestamp,
        "views": views,
    }


def _run(
    endpoint: str,
    script: Script,
    resume_state: Optional[WikipediaPageviewsResumeConfig] = None,
    article_names: Optional[str] = None,
    start_date: Optional[str] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    countries: Optional[str] = None,
    agent: Literal["user", "all-agents", "spider", "automated"] = "user",
) -> DriveResult:
    config = WikipediaPageviewsSourceConfig(
        project="en.wikipedia.org",
        article_names=article_names,
        start_date=start_date,
        countries=countries,
        agent=agent,
    )
    return SourceDriver(WikipediaPageviewsSource(), config).run(
        endpoint,
        script,
        resume_state=resume_state,
        incremental_field="date" if should_use_incremental_field else None,
        db_incremental_field_last_value=db_incremental_field_last_value,
    )


def _requested_ranges(result: DriveResult) -> list[tuple[str, str]]:
    ranges = []
    for path in result.paths:
        match = re.search(r"/daily/(\d+)/(\d+)$", path)
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
            ("none", None, []),
            ("empty", " , ", []),
            ("uppercases_and_dedupes", "us, fr,US", ["US", "FR"]),
            ("spaces_and_newlines", "DE GB\nJP", ["DE", "GB", "JP"]),
        ]
    )
    def test_parse_countries(self, _name, value, expected):
        assert _parse_countries(value) == expected

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
    @time_machine.travel("2026-07-21", tick=False)
    def test_404_window_is_skipped_and_iteration_continues(self):
        result = _run(
            PAGEVIEWS_ENDPOINT,
            [
                _response(status=404),
                _response(json_body={"items": [_aggregate_item("2025070200")]}),
                _response(status=404),
            ],
            start_date="2024-07-01",
        )

        assert len(result.requests) == 3
        assert len(result.items) == 1
        assert result.items[0][0]["timestamp"] == "2025070200"

    @time_machine.travel("2026-07-21", tick=False)
    def test_resume_state_takes_precedence_over_incremental_value(self):
        result = _run(
            PAGEVIEWS_ENDPOINT,
            always(_response(json_body={"items": []})),
            resume_state=WikipediaPageviewsResumeConfig(next_start="2026-07-19"),
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 7, 1, tzinfo=UTC),
        )

        assert _requested_ranges(result) == [("2026071900", "2026072100")]

    @time_machine.travel("2026-07-21", tick=False)
    def test_non_ok_status_raises(self):
        result = _run(
            PAGEVIEWS_ENDPOINT,
            always(_response(status=500, json_body={"error": "server error"})),
            start_date="2026-07-18",
        )

        assert isinstance(result.raised, requests.HTTPError)


class TestArticlePageviews:
    @time_machine.travel("2026-07-21", tick=False)
    def test_fans_out_per_article_with_encoded_titles(self):
        result = _run(
            ARTICLE_PAGEVIEWS_ENDPOINT,
            [
                _response(
                    json_body={
                        "items": [
                            {
                                "project": "en.wikipedia",
                                "article": "Albert_Einstein",
                                "timestamp": "2026071800",
                                "views": 5,
                            }
                        ]
                    }
                ),
                _response(
                    json_body={
                        "items": [
                            {"project": "en.wikipedia", "article": "AC%2FDC", "timestamp": "2026071800", "views": 7}
                        ]
                    }
                ),
            ],
            article_names="Albert Einstein, AC/DC",
            start_date="2026-07-18",
        )

        assert result.urls == [
            "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia.org"
            "/all-access/user/Albert_Einstein/daily/20260718/20260721",
            "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia.org"
            "/all-access/user/AC%2FDC/daily/20260718/20260721",
        ]
        # Both articles' rows land in the same window batch, so the per-batch watermark
        # never advances past a window an article hasn't been fetched for.
        assert len(result.items) == 1
        assert [row["views"] for row in result.items[0]] == [5, 7]
        assert result.items[0][0]["date"] == datetime(2026, 7, 18, tzinfo=UTC)

    def test_raises_without_configured_articles(self):
        result = _run(ARTICLE_PAGEVIEWS_ENDPOINT, [], article_names="  ,  ")

        assert isinstance(result.raised, ValueError)
        assert NO_ARTICLES_ERROR in str(result.raised)

    @time_machine.travel("2026-07-21", tick=False)
    def test_article_titles_capped_at_max_at_runtime(self):
        # Single window (start within a year of now), so one request per article — a config
        # stored past the cap must still not fan out beyond MAX_ARTICLES.
        names = ",".join(f"Article_{i}" for i in range(MAX_ARTICLES + 5))

        result = _run(
            ARTICLE_PAGEVIEWS_ENDPOINT,
            always(_response(json_body={"items": []})),
            article_names=names,
            start_date="2026-07-20",
        )

        assert len(result.requests) == MAX_ARTICLES


class TestTopArticles:
    @time_machine.travel("2026-07-21", tick=False)
    def test_flattens_daily_rankings_into_rows(self):
        def day_response(request: RecordedRequest) -> ScriptedResponse:
            match = re.search(r"/top/en\.wikipedia\.org/all-access/(\d{4})/(\d{2})/(\d{2})$", request.path)
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

        result = _run(TOP_ARTICLES_ENDPOINT, day_response, start_date="2026-07-19")

        # One request per day, all days of the window batched into a single yield.
        assert len(result.requests) == 3
        assert len(result.items) == 1
        assert len(result.items[0]) == 6

        first = result.items[0][0]
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
        assert [state.next_start for state in result.saved_states] == ["2026-07-22"]


class TestCountryPageviews:
    @parameterized.expand(
        [
            ("start_mid_month_includes_that_month", "2026-05-15", None, ["2026/05", "2026/06", "2026/07"]),
            (
                "incremental_refetches_watermark_month",
                "2026-01-01",
                datetime(2026, 6, 1, tzinfo=UTC),
                ["2026/06", "2026/07"],
            ),
            # The first window ends on 2026-06-01, so the second window must not request June again.
            (
                "months_split_across_windows",
                "2025-06-15",
                None,
                [f"2025/{m:02d}" for m in range(6, 13)] + [f"2026/{m:02d}" for m in range(1, 8)],
            ),
        ]
    )
    @time_machine.travel("2026-07-21", tick=False)
    def test_requests_each_month_once(self, _name, start_date, last_value, expected_months):
        result = _run(
            COUNTRY_PAGEVIEWS_ENDPOINT,
            always(_response(status=404)),
            start_date=start_date,
            should_use_incremental_field=last_value is not None,
            db_incremental_field_last_value=last_value,
        )

        months = []
        for path in result.paths:
            match = re.search(r"/top-by-country/en\.wikipedia\.org/all-access/(\d{4}/\d{2})$", path)
            assert match is not None
            months.append(match.group(1))
        assert months == expected_months

    @time_machine.travel("2026-07-21", tick=False)
    def test_flattens_countries_into_rows(self):
        result = _run(
            COUNTRY_PAGEVIEWS_ENDPOINT,
            [
                _response(
                    json_body={
                        "items": [
                            {
                                "project": "en.wikipedia",
                                "access": "all-access",
                                "year": "2026",
                                "month": "06",
                                "countries": [
                                    {"country": "US", "views": "1000000-9999999", "rank": 1, "views_ceil": 4200000},
                                    {"country": "GB", "views": "100000-999999", "rank": 2, "views_ceil": 870000},
                                ],
                            }
                        ]
                    }
                ),
                _response(status=404),
            ],
            start_date="2026-06-01",
        )

        assert result.items == [
            [
                {
                    "project": "en.wikipedia",
                    "access": "all-access",
                    "year": "2026",
                    "month": "06",
                    "date": datetime(2026, 6, 1, tzinfo=UTC),
                    "country": "US",
                    "views": "1000000-9999999",
                    "views_ceil": 4200000,
                    "rank": 1,
                },
                {
                    "project": "en.wikipedia",
                    "access": "all-access",
                    "year": "2026",
                    "month": "06",
                    "date": datetime(2026, 6, 1, tzinfo=UTC),
                    "country": "GB",
                    "views": "100000-999999",
                    "views_ceil": 870000,
                    "rank": 2,
                },
            ]
        ]


class TestCountryTopArticles:
    @time_machine.travel("2026-07-21", tick=False)
    def test_fans_out_per_country_per_day(self):
        def day_response(request: RecordedRequest) -> ScriptedResponse:
            match = re.search(r"/top-per-country/([A-Z]{2})/all-access/(\d{4})/(\d{2})/(\d{2})$", request.path)
            assert match is not None
            country, year, month, day = match.groups()
            return _response(
                json_body={
                    "items": [
                        {
                            "country": country,
                            "access": "all-access",
                            "year": year,
                            "month": month,
                            "day": day,
                            "articles": [
                                {"article": "Main_Page", "project": "en.wikipedia", "views_ceil": 9000, "rank": 1},
                                {"article": "Main_Page", "project": "fr.wikipedia", "views_ceil": 9000, "rank": 1},
                            ],
                        }
                    ]
                }
            )

        result = _run(COUNTRY_TOP_ARTICLES_ENDPOINT, day_response, countries="us, fr", start_date="2026-07-20")

        assert [path.split("/top-per-country/")[1] for path in result.paths] == [
            "US/all-access/2026/07/20",
            "FR/all-access/2026/07/20",
            "US/all-access/2026/07/21",
            "FR/all-access/2026/07/21",
        ]
        assert len(result.items) == 1
        assert len(result.items[0]) == 8
        assert result.items[0][1] == {
            "country": "US",
            "access": "all-access",
            "year": "2026",
            "month": "07",
            "day": "20",
            "date": datetime(2026, 7, 20, tzinfo=UTC),
            "project": "fr.wikipedia",
            "article": "Main_Page",
            "views_ceil": 9000,
            "rank": 1,
        }

    @time_machine.travel("2021-01-02", tick=False)
    def test_start_is_clamped_to_first_day_with_data(self):
        result = _run(COUNTRY_TOP_ARTICLES_ENDPOINT, always(_response(status=404)), countries="US")

        assert [path.rsplit("/", 3)[1:] for path in result.paths] == [["2021", "01", "01"], ["2021", "01", "02"]]

    def test_raises_without_configured_countries(self):
        result = _run(COUNTRY_TOP_ARTICLES_ENDPOINT, [], countries=" , ")

        assert isinstance(result.raised, ValueError)
        assert NO_COUNTRIES_ERROR in str(result.raised)

    @time_machine.travel("2026-07-21", tick=False)
    def test_countries_capped_at_max_at_runtime(self):
        countries = ",".join(f"{chr(65 + i)}{chr(65 + i)}" for i in range(MAX_COUNTRIES + 3))

        result = _run(
            COUNTRY_TOP_ARTICLES_ENDPOINT,
            always(_response(status=404)),
            countries=countries,
            start_date="2026-07-21",
        )

        assert len(result.requests) == MAX_COUNTRIES


class TestUniqueDevices:
    @time_machine.travel("2026-07-21", tick=False)
    def test_syncs_every_site_split_with_normalized_key(self):
        def site_response(request: RecordedRequest) -> ScriptedResponse:
            match = re.search(r"/unique-devices/en\.wikipedia\.org/([a-z-]+)/daily/20260720/20260721$", request.path)
            assert match is not None
            return _response(
                json_body={
                    "items": [
                        {
                            "project": "en.wikipedia",
                            "access-site": match.group(1),
                            "granularity": "daily",
                            "timestamp": "20260720",
                            "devices": 300,
                            "offset": 100,
                            "underestimate": 200,
                        }
                    ]
                }
            )

        result = _run(UNIQUE_DEVICES_ENDPOINT, site_response, start_date="2026-07-20")

        assert len(result.items) == 1
        assert [row["access_site"] for row in result.items[0]] == ["all-sites", "desktop-site", "mobile-site"]
        assert result.items[0][0] == {
            "project": "en.wikipedia",
            "access_site": "all-sites",
            "granularity": "daily",
            "timestamp": "20260720",
            "date": datetime(2026, 7, 20, tzinfo=UTC),
            "devices": 300,
            "offset": 100,
            "underestimate": 200,
        }


class TestMediaRequests:
    @parameterized.expand(
        [
            ("user", "user", "user"),
            ("spider", "spider", "spider"),
            ("all_agents", "all-agents", "all-agents"),
            ("automated_falls_back", "automated", "all-agents"),
        ]
    )
    @time_machine.travel("2026-07-21", tick=False)
    def test_requests_each_media_type_with_supported_agent(self, _name, agent, expected_agent):
        result = _run(
            MEDIA_REQUESTS_ENDPOINT,
            always(
                _response(
                    json_body={
                        "items": [
                            {
                                "referer": "en.wikipedia",
                                "media_type": "image",
                                "agent": expected_agent,
                                "granularity": "daily",
                                "timestamp": "2026072000",
                                "requests": 42,
                            }
                        ]
                    }
                )
            ),
            start_date="2026-07-20",
            agent=agent,
        )

        assert result.urls == [
            f"https://wikimedia.org/api/rest_v1/metrics/mediarequests/aggregate/en.wikipedia.org/{media_type}"
            f"/{expected_agent}/daily/20260720/20260721"
            for media_type in ("image", "video", "audio", "document", "other")
        ]
        assert result.items[0][0]["date"] == datetime(2026, 7, 20, tzinfo=UTC)


class TestValidateProject:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("not_found", 404, False),
            ("server_error", 500, False),
        ]
    )
    def test_status_mapping(self, _name, status, expected_valid):
        with scripted_network(always(_response(status=status))):
            is_valid, message = validate_project("en.wikipedia.org", "all-access", "user")

        assert is_valid is expected_valid
        if expected_valid:
            assert message is None
        else:
            assert message is not None

    def test_empty_project_is_invalid_without_network(self):
        with scripted_network([]) as network:
            is_valid, message = validate_project("  ", "all-access", "user")

        assert is_valid is False
        assert message is not None
        assert network.requests_log == []

    def test_network_error_is_not_valid(self):
        with scripted_network(always(requests.ConnectionError("boom"))):
            is_valid, message = validate_project("en.wikipedia.org", "all-access", "user")

        assert is_valid is False
        assert message is not None


class TestSourceResponseMetadata:
    @parameterized.expand([(name,) for name in WIKIPEDIA_PAGEVIEWS_ENDPOINTS])
    @time_machine.travel("2026-07-21", tick=False)
    def test_primary_keys_and_partitioning_per_endpoint(self, endpoint):
        result = _run(
            endpoint, always(_response(status=404)), article_names="Cat", countries="US", start_date="2026-07-20"
        )

        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == WIKIPEDIA_PAGEVIEWS_ENDPOINTS[endpoint].primary_keys
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["date"]
        assert response.sort_mode == "asc"
