from datetime import UTC, date, datetime
from typing import Any, Literal, Optional

import time_machine

import requests
from parameterized import parameterized

from products.warehouse_sources.sources.sdk.testing import DriveResult, ScriptedResponse, SourceDriver, always
from products.warehouse_sources.sources.similarweb._config import SimilarwebSourceConfig
from products.warehouse_sources.sources.similarweb.settings import (
    API_VERSION_LEGACY,
    API_VERSION_V5,
    BASE_URL,
    CONVERSION_ANALYSIS,
    CONVERSION_COUNTRY_ERROR,
    CONVERSION_SEGMENTS_PATH,
    DEDUPLICATED_AUDIENCE,
    GLOBAL_RANK,
    PAGE_LIMIT,
    PAGE_VIEWS,
    TRAFFIC_BY_COUNTRY,
    TRAFFIC_SOURCES,
    V5_ENGAGEMENT_PATH,
    V5_WORLDWIDE_COUNTRY,
    VISITS,
    VISITS_SPLIT,
    WEBSITE_KEYWORDS,
)
from products.warehouse_sources.sources.similarweb.similarweb import (
    NO_DOMAINS_ERROR,
    SimilarwebResumeConfig,
    coerce_month,
    is_valid_country,
    normalize_country,
    parse_domains,
)
from products.warehouse_sources.sources.similarweb.source import SimilarwebSource


def _response(status: int = 200, json_body: Any = None) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=json_body if json_body is not None else {})


def _series_body(key: str, points: list[dict[str, Any]]) -> dict[str, Any]:
    return {"meta": {"status": "Success"}, key: points}


def _run(
    endpoint: str,
    script: Any,
    resume_state: Optional[SimilarwebResumeConfig] = None,
    domains: str = "a.com, b.com",
    country: Optional[str] = None,
    granularity: Literal["monthly", "weekly", "daily"] = "monthly",
    start_date: Optional[str] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    api_version: str = API_VERSION_LEGACY,
) -> DriveResult:
    config = SimilarwebSourceConfig(
        api_key="key-123", domains=domains, country=country, granularity=granularity, start_date=start_date
    )
    return SourceDriver(SimilarwebSource(), config).run(
        endpoint,
        script,
        resume_state=resume_state,
        api_version=api_version,
        should_use_incremental_field=should_use_incremental_field,
        db_incremental_field_last_value=db_incremental_field_last_value,
    )


def _v5_series_body(metric: str, points: list[dict[str, Any]]) -> dict[str, Any]:
    # V5 wraps every metric's series under a standardized `data` key; each row carries the metric.
    return {"meta": {"status": "Success"}, "data": points}


class TestSimilarwebTransport:
    @parameterized.expand(
        [
            ("none", None, []),
            ("empty", "  ", []),
            ("strips_scheme_www_and_path", "https://www.Example.com/pricing", ["example.com"]),
            ("splits_on_commas_and_newlines", "a.com,\nb.com", ["a.com", "b.com"]),
            ("dedupes", "a.com, www.a.com, b.com", ["a.com", "b.com"]),
        ]
    )
    def test_parse_domains(self, _name: str, raw: Optional[str], expected: list[str]) -> None:
        assert parse_domains(raw) == expected

    @parameterized.expand(
        [
            ("month_string", "2024-03", "2024-03"),
            ("iso_timestamp", "2024-03-15T10:11:12+00:00", "2024-03"),
            ("date_object", date(2024, 3, 15), "2024-03"),
            ("datetime_object", datetime(2024, 3, 15, tzinfo=UTC), "2024-03"),
            ("garbage", "last month", None),
            ("none", None, None),
        ]
    )
    def test_coerce_month(self, _name: str, value: Any, expected: Optional[str]) -> None:
        assert coerce_month(value) == expected

    @parameterized.expand(
        [
            ("blank_defaults_to_world", None, "world", True),
            ("empty_defaults_to_world", "  ", "world", True),
            ("two_letter_lowered", "US", "us", True),
            ("three_letter_rejected", "usa", "usa", False),
        ]
    )
    def test_country_normalization(self, _name: str, value: Optional[str], normalized: str, valid: bool) -> None:
        assert normalize_country(value) == normalized
        assert is_valid_country(value) is valid

    def test_no_domains_raises_named_error(self) -> None:
        result = _run(VISITS, [], domains="")

        assert isinstance(result.raised, ValueError)
        assert NO_DOMAINS_ERROR in str(result.raised)
        assert result.requests == []

    @parameterized.expand([("visits", VISITS, "visits"), ("page_views", PAGE_VIEWS, "page_views")])
    def test_v5_engagement_hits_the_multimetric_endpoint_with_header_auth(
        self, _name: str, endpoint: str, metric: str
    ) -> None:
        result = _run(
            endpoint,
            [_response(json_body=_v5_series_body(metric, [{"date": "2024-01-01", metric: 9}]))],
            domains="a.com",
            api_version=API_VERSION_V5,
        )

        # One `/v5/website-analysis` endpoint serves every metric; the table selects its own via
        # `metrics`, the key moves to the `api-key` header, and rows come from the `data` envelope.
        assert [f"{request.origin}{request.path}" for request in result.requests] == [f"{BASE_URL}{V5_ENGAGEMENT_PATH}"]
        assert result.params("metrics") == [metric]
        assert result.params("domain") == ["a.com"]
        assert result.params("api_key") == [None]
        assert result.requests[0].headers["api-key"] == "key-123"
        assert result.items[0] == [
            {
                "domain": "a.com",
                "country": "world",
                "granularity": "monthly",
                "date": datetime(2024, 1, 1, tzinfo=UTC),
                metric: 9,
            }
        ]

    @parameterized.expand(
        [
            # V5 rejects the legacy `world` sentinel and documents `ww`; legacy keeps sending `world`.
            ("legacy_worldwide_stays_world", API_VERSION_LEGACY, None, "world"),
            ("v5_worldwide_becomes_ww", API_VERSION_V5, None, V5_WORLDWIDE_COUNTRY),
            ("v5_explicit_country_passes_through", API_VERSION_V5, "gb", "gb"),
        ]
    )
    def test_worldwide_country_is_translated_only_for_v5(
        self, _name: str, api_version: str, country: Optional[str], expected_param: str
    ) -> None:
        result = _run(
            VISITS,
            [_response(json_body={"visits": [], "data": []})],
            domains="a.com",
            country=country,
            api_version=api_version,
        )

        assert result.params("country") == [expected_param]

    def test_global_rank_takes_no_filters_and_parses_month_dates(self) -> None:
        result = _run(
            GLOBAL_RANK,
            [_response(json_body=_series_body("global_rank", [{"date": "2024-01", "global_rank": 86}]))],
            domains="a.com",
            country="gb",
        )

        assert result.items[0] == [{"domain": "a.com", "date": datetime(2024, 1, 1, tzinfo=UTC), "global_rank": 86}]
        assert result.params("country") == [None]
        assert result.params("granularity") == [None]

    @parameterized.expand([("legacy", API_VERSION_LEGACY), ("v5", API_VERSION_V5)])
    def test_deduplicated_audience_uses_monthly_data_and_flattens_metrics(self, _name: str, api_version: str) -> None:
        with time_machine.travel("2024-06-15", tick=False):
            result = _run(
                DEDUPLICATED_AUDIENCE,
                [
                    _response(
                        json_body={
                            "data": [
                                {
                                    "date": "2024-06-01",
                                    "dedup_data": {
                                        "total_deduplicated_audience": 120,
                                        "desktop_only_audience_share": 0.25,
                                    },
                                }
                            ]
                        }
                    )
                ],
                domains="example.com",
                granularity="daily",
                api_version=api_version,
            )

        assert result.raised is None
        assert result.paths == ["/v1/website/example.com/dedup/deduplicated-audiences"]
        assert result.params("api_key") == ["key-123"]
        assert result.params("start_date") == result.params("end_date") == ["2024-06"]
        assert result.params("granularity") == [None]
        assert result.rows == [
            {
                "domain": "example.com",
                "country": "world",
                "date": datetime(2024, 6, 1, tzinfo=UTC),
                "total_deduplicated_audience": 120,
                "desktop_only_audience_share": 0.25,
            }
        ]

    @parameterized.expand([("default_window", None, "2024-06"), ("configured_window", "2024-01", "2024-01")])
    def test_visits_split_preserves_the_aggregate_window(
        self, _name: str, start_date: str | None, expected_start: str
    ) -> None:
        with time_machine.travel("2024-06-15", tick=False):
            result = _run(
                VISITS_SPLIT,
                [
                    _response(json_body={"meta": {}, "desktop_visit_share": 0.0, "mobile_web_visit_share": 1.0}),
                    _response(status=404),
                ],
                domains="example.com, missing.example.com",
                start_date=start_date,
                granularity="weekly",
            )

        assert result.raised is None
        assert result.paths == [
            f"/v1/website/{domain}/total-traffic-and-engagement/visits-split"
            for domain in ("example.com", "missing.example.com")
        ]
        assert result.params("start_date") == [expected_start, expected_start]
        assert result.params("end_date") == ["2024-06", "2024-06"]
        assert result.params("granularity") == [None, None]
        assert result.rows == [
            {
                "domain": "example.com",
                "country": "world",
                "start_date": expected_start,
                "end_date": "2024-06",
                "desktop_visit_share": 0.0,
                "mobile_web_visit_share": 1.0,
            }
        ]

    @parameterized.expand([("full_refresh", False, "2023-12"), ("incremental", True, "2024-01")])
    def test_keywords_page_within_months_before_advancing_the_watermark(
        self, _name: str, incremental: bool, expected_start: str
    ) -> None:
        full_page = [{"keyword": f"term-{index}", "clicks": index} for index in range(PAGE_LIMIT)]
        script = [
            _response(json_body={"keywords": full_page}),
            _response(json_body={"keywords": [{"keyword": "last term", "clicks": 2}]}),
        ]
        if not incremental:
            script.extend([_response(json_body={"keywords": []}), _response(json_body={"keywords": []})])
        script.extend([_response(json_body={"keywords": [{"keyword": "other domain"}]})])
        with time_machine.travel("2024-01-15", tick=False):
            result = _run(
                WEBSITE_KEYWORDS,
                script,
                domains="example.com, other.example.com",
                start_date="2023-12",
                should_use_incremental_field=incremental,
                db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
                api_version=API_VERSION_V5,
            )

        assert result.raised is None
        months = (
            [expected_start, expected_start, "2024-01"]
            if incremental
            else ["2023-12", "2023-12", "2023-12", "2024-01", "2024-01"]
        )
        assert result.params("start_date") == result.params("end_date") == months
        assert result.params("offset") == ["0", str(PAGE_LIMIT)] + ["0"] * (len(months) - 2)
        assert result.paths == ["/v4/website-analysis/keywords"] * len(months)
        assert result.params("URL") == ["example.com", "example.com"] + (
            ["other.example.com"] if incremental else ["other.example.com", "example.com", "other.example.com"]
        )
        assert result.params("traffic_source") == ["All"] * len(months)
        assert result.params("web_source") == ["Total"] * len(months)
        assert result.params("granularity") == [None] * len(months)
        assert result.rows[0] == {
            "domain": "example.com",
            "country": "world",
            "date": datetime.fromisoformat(expected_start + "-01").replace(tzinfo=UTC),
            "keyword": "term-0",
            "clicks": 0,
        }
        assert [row["date"] for row in result.rows] == sorted(row["date"] for row in result.rows)
        assert result.saved_states[0] == SimilarwebResumeConfig(
            next_domain_index=0, next_offset=PAGE_LIMIT, next_month=expected_start
        )
        assert result.committed_states[0] == result.saved_states[0]
        assert result.final_state is None

    def test_keywords_resume_keeps_the_month_domain_and_page(self) -> None:
        with time_machine.travel("2024-02-15", tick=False):
            result = _run(
                WEBSITE_KEYWORDS,
                [_response(json_body={"keywords": [{"keyword": "resumed term"}]})],
                domains="example.com, other.example.com",
                start_date="2023-12",
                resume_state=SimilarwebResumeConfig(next_domain_index=1, next_offset=100, next_month="2024-02"),
            )

        assert result.raised is None
        assert result.params("URL") == ["other.example.com"]
        assert result.params("offset") == ["100"]
        assert result.params("start_date") == result.params("end_date") == ["2024-02"]
        assert result.rows == [
            {
                "domain": "other.example.com",
                "country": "world",
                "keyword": "resumed term",
                "date": datetime(2024, 2, 1, tzinfo=UTC),
            }
        ]
        assert result.final_state is None

    def test_conversion_discovers_matching_segments_and_orders_their_periods(self) -> None:
        segment_id = "example.com%23Checkout / completed"
        segment = {"site": "www.example.com", "segment_id": segment_id, "available_countries": ["US"]}
        with time_machine.travel("2024-06-15", tick=False):
            result = _run(
                CONVERSION_ANALYSIS,
                [
                    _response(
                        json_body={
                            "response": {
                                "segments": [
                                    segment,
                                    segment,
                                    {**segment, "segment_id": "wrong-country", "available_countries": ["GB"]},
                                    {**segment, "site": "other.example.com", "segment_id": "unconfigured"},
                                    {**segment, "segment_id": ""},
                                    {**segment, "segment_id": "second"},
                                ]
                            }
                        }
                    ),
                    _response(json_body={"segments": [{"date": "2024-06-01", "converted_visits": 5}]}),
                    _response(json_body={"segments": [{"date": "2024-04-01", "converted_visits": 3}]}),
                ],
                domains="example.com",
                country="US",
                granularity="daily",
                start_date="2024-01",
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 4, 1, tzinfo=UTC),
                api_version=API_VERSION_V5,
            )

        assert result.raised is None
        assert result.paths == [
            CONVERSION_SEGMENTS_PATH,
            "/v1/segment/example.com%23Checkout%20%2F%20completed/conversion-analysis/query",
            "/v1/segment/second/conversion-analysis/query",
        ]
        assert result.params("start_date") == [None, "2024-04", "2024-04"]
        assert result.params("end_date") == [None, "2024-06", "2024-06"]
        assert result.params("country") == [None, "us", "us"]
        assert result.params("granularity") == [None, "monthly", "monthly"]
        assert result.params("metrics") == [None] + ["visits,converted-visits,conversion-rate,stickiness"] * 2
        assert result.rows == [
            {
                "domain": "example.com",
                "country": "us",
                "date": datetime(2024, 4, 1, tzinfo=UTC),
                "converted_visits": 3,
                "conversion_segment_id": "second",
            },
            {
                "domain": "example.com",
                "country": "us",
                "date": datetime(2024, 6, 1, tzinfo=UTC),
                "converted_visits": 5,
                "conversion_segment_id": segment_id,
            },
        ]

    def test_conversion_rejects_worldwide_before_spending_credits(self) -> None:
        result = _run(CONVERSION_ANALYSIS, [], domains="example.com")

        assert isinstance(result.raised, ValueError)
        assert str(result.raised) == CONVERSION_COUNTRY_ERROR
        assert result.requests == []

    def test_traffic_sources_flattens_channels(self) -> None:
        script = [
            _response(
                json_body={
                    "meta": {"status": "Success"},
                    "visits": {
                        "a.com": [
                            {
                                "source_type": "Search",
                                "visits": [{"date": "2024-01-01", "organic": 10.0, "paid": 1.0}],
                            },
                            {
                                "source_type": "Direct",
                                "visits": [{"date": "2024-01-01", "organic": 5.0, "paid": 0}],
                            },
                        ]
                    },
                }
            )
        ]

        rows = _run(TRAFFIC_SOURCES, script, domains="a.com").items[0]

        assert sorted(row["source_type"] for row in rows) == ["Direct", "Search"]
        assert rows[0] == {
            "domain": "a.com",
            "country": "world",
            "granularity": "monthly",
            "source_type": "Search",
            "date": datetime(2024, 1, 1, tzinfo=UTC),
            "organic": 10.0,
            "paid": 1.0,
        }

    @parameterized.expand([("unauthorized", 401), ("not_found", 404)])
    def test_a_domain_without_data_does_not_abort_the_other_domains(self, _name: str, status: int) -> None:
        result = _run(
            VISITS,
            [
                _response(status=status),
                _response(json_body=_series_body("visits", [{"date": "2024-01-01", "visits": 7}])),
            ],
        )

        assert result.raised is None
        assert [row["domain"] for row in result.rows] == ["b.com"]

    def test_unexpected_status_fails_the_sync(self) -> None:
        result = _run(VISITS, always(_response(status=500)), domains="a.com")

        assert isinstance(result.raised, requests.HTTPError)

    def test_connection_error_is_reraised_without_the_api_key(self) -> None:
        error = requests.ConnectionError(
            "Max retries exceeded with url: /v1/website/a.com/...?api_key=key-123&format=json"
        )

        result = _run(VISITS, always(error), domains="a.com")

        assert isinstance(result.raised, requests.ConnectionError)
        assert "key-123" not in str(result.raised)
        assert "Similarweb request failed" in str(result.raised)

    def test_rows_with_an_unparsable_period_are_dropped(self) -> None:
        script = [
            _response(
                json_body=_series_body(
                    "visits", [{"date": "not-a-date", "visits": 1}, {"date": "2024-01-01", "visits": 2}]
                )
            )
        ]

        rows = _run(VISITS, script, domains="a.com").items[0]

        assert [row["visits"] for row in rows] == [2]

    @parameterized.expand(
        [
            # Monthly has no valid no-date mode, so an unconfigured window falls back to the current
            # month; daily and weekly keep the API's dateless "last 28 days" default.
            ("monthly_no_window_defaults_to_current_month", "monthly", None, False, None, "2024-06", "2024-06"),
            ("daily_no_window_uses_api_default", "daily", None, False, None, None, None),
            ("weekly_no_window_uses_api_default", "weekly", None, False, None, None, None),
            ("configured_start_only", "monthly", "2024-01", False, None, "2024-01", "2024-06"),
            (
                "watermark_wins_when_later",
                "monthly",
                "2024-01",
                True,
                datetime(2024, 4, 20, tzinfo=UTC),
                "2024-04",
                "2024-06",
            ),
            (
                "configured_start_wins_when_later",
                "monthly",
                "2024-05",
                True,
                datetime(2024, 4, 20, tzinfo=UTC),
                "2024-05",
                "2024-06",
            ),
            (
                "watermark_without_configured_start",
                "monthly",
                None,
                True,
                datetime(2024, 4, 20, tzinfo=UTC),
                "2024-04",
                "2024-06",
            ),
        ]
    )
    def test_window_params(
        self,
        _name: str,
        granularity: Literal["monthly", "weekly", "daily"],
        start_date: Optional[str],
        should_use_incremental_field: bool,
        last_value: Any,
        expected_start: Optional[str],
        expected_end: Optional[str],
    ) -> None:
        with time_machine.travel("2024-06-15", tick=False):
            result = _run(
                VISITS,
                [_response(json_body=_series_body("visits", []))],
                domains="a.com",
                granularity=granularity,
                start_date=start_date,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=last_value,
            )

        assert result.params("start_date") == [expected_start]
        assert result.params("end_date") == [expected_end]

    def test_api_key_is_sent_as_a_query_param_and_registered_for_redaction(self) -> None:
        result = _run(
            VISITS, [_response(json_body=_series_body("visits", []))], domains="a.com", api_version=API_VERSION_LEGACY
        )

        assert result.session_options[0]["redact_values"] == ("key-123",)
        assert result.params("api_key") == ["key-123"]

    def test_paginated_endpoint_walks_offsets_and_checkpoints_each_page(self) -> None:
        full_page = [{"country": index, "visits": 1} for index in range(PAGE_LIMIT)]
        script = [
            _response(json_body={"records": full_page}),
            _response(json_body={"records": [{"country": 999, "visits": 2}]}),
            _response(json_body={"records": []}),
        ]

        result = _run(TRAFFIC_BY_COUNTRY, script)

        assert result.raised is None
        assert result.params("offset") == ["0", str(PAGE_LIMIT), "0"]
        assert result.items[0][0] == {"domain": "a.com", "country": 0, "visits": 1}
        assert [(state.next_domain_index, state.next_offset) for state in result.saved_states] == [
            (0, PAGE_LIMIT),
            (1, 0),
            (2, 0),
        ]
        assert result.final_state is None
