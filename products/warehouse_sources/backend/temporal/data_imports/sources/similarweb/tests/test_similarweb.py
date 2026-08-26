from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any, Optional, cast

import pytest
from freezegun import freeze_time
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.similarweb.settings import (
    API_VERSION_LEGACY,
    API_VERSION_V5,
    BASE_URL,
    GLOBAL_RANK,
    PAGE_LIMIT,
    PAGE_VIEWS,
    TRAFFIC_BY_COUNTRY,
    TRAFFIC_SOURCES,
    V5_ENGAGEMENT_PATH,
    V5_WORLDWIDE_COUNTRY,
    VISITS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.similarweb.similarweb import (
    NO_DOMAINS_ERROR,
    SimilarwebResumeConfig,
    coerce_month,
    is_valid_country,
    normalize_country,
    parse_domains,
    similarweb_source,
    validate_credentials,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.similarweb.similarweb"


class FakeResumeManager(ResumableSourceManager[SimilarwebResumeConfig]):
    def __init__(self, state: Optional[SimilarwebResumeConfig] = None) -> None:
        self.state = state
        self.saved: list[SimilarwebResumeConfig] = []
        self.cleared = False

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> Optional[SimilarwebResumeConfig]:
        return self.state

    def save_state(self, data: SimilarwebResumeConfig) -> None:
        self.saved.append(data)

    def clear_state(self) -> None:
        self.cleared = True


def _response(status: int = 200, json_body: Any = None) -> mock.MagicMock:
    response = mock.MagicMock(spec=requests.Response)
    response.status_code = status
    response.ok = 200 <= status < 300
    response.text = ""
    response.json.return_value = json_body if json_body is not None else {}
    if not response.ok:
        errored = requests.Response()
        errored.status_code = status
        response.raise_for_status.side_effect = requests.HTTPError(f"{status} Client Error: for url", response=errored)
    return response


def _series_body(key: str, points: list[dict[str, Any]]) -> dict[str, Any]:
    return {"meta": {"status": "Success"}, key: points}


def _session(*responses: mock.MagicMock) -> mock.MagicMock:
    session = mock.MagicMock(spec=requests.Session)
    session.get.side_effect = list(responses)
    return session


def _run(
    endpoint: str,
    session: mock.MagicMock,
    manager: Optional[FakeResumeManager] = None,
    domains: Optional[str] = "a.com, b.com",
    country: Optional[str] = None,
    granularity: str = "monthly",
    start_date: Optional[str] = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
    api_version: str = API_VERSION_LEGACY,
) -> list[list[dict[str, Any]]]:
    with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
        response = similarweb_source(
            api_key="key-123",
            domains=domains,
            country=country,
            granularity=granularity,
            start_date=start_date,
            endpoint=endpoint,
            logger=mock.MagicMock(),
            resumable_source_manager=manager if manager is not None else FakeResumeManager(),
            api_version=api_version,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        )
        return list(cast(Iterable[Any], response.items()))


def _v5_series_body(metric: str, points: list[dict[str, Any]]) -> dict[str, Any]:
    # V5 wraps every metric's series under a standardized `data` key; each row carries the metric.
    return {"meta": {"status": "Success"}, "data": points}


def _headers(session: mock.MagicMock, index: int = 0) -> Optional[dict[str, str]]:
    return session.get.call_args_list[index].kwargs["headers"]


def _params(session: mock.MagicMock, index: int = 0) -> dict[str, Any]:
    return session.get.call_args_list[index].kwargs["params"]


def _urls(session: mock.MagicMock) -> list[str]:
    return [call.args[0] for call in session.get.call_args_list]


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
        with pytest.raises(ValueError, match=NO_DOMAINS_ERROR):
            _run(VISITS, _session(), domains="")

    def test_rows_are_ordered_by_period_across_domains(self) -> None:
        # Each domain's request returns its whole window, so the per-domain series overlap in
        # time. The pipeline checkpoints the incremental watermark per batch, so emitting one
        # domain's full history before the next domain's would strand the later domain's older
        # periods behind an already-advanced watermark.
        session = _session(
            _response(
                json_body=_series_body(
                    "visits", [{"date": "2024-01-01", "visits": 1}, {"date": "2024-02-01", "visits": 2}]
                )
            ),
            _response(
                json_body=_series_body(
                    "visits", [{"date": "2024-01-01", "visits": 3}, {"date": "2024-02-01", "visits": 4}]
                )
            ),
        )

        rows = [row for batch in _run(VISITS, session) for row in batch]

        assert [(row["date"], row["domain"]) for row in rows] == [
            (datetime(2024, 1, 1, tzinfo=UTC), "a.com"),
            (datetime(2024, 1, 1, tzinfo=UTC), "b.com"),
            (datetime(2024, 2, 1, tzinfo=UTC), "a.com"),
            (datetime(2024, 2, 1, tzinfo=UTC), "b.com"),
        ]

    def test_series_rows_carry_the_requested_filters(self) -> None:
        session = _session(_response(json_body=_series_body("visits", [{"date": "2024-01-01", "visits": 9}])))

        rows = _run(VISITS, session, domains="a.com", country="GB", granularity="weekly")[0]

        assert rows == [
            {
                "domain": "a.com",
                "country": "gb",
                "granularity": "weekly",
                "date": datetime(2024, 1, 1, tzinfo=UTC),
                "visits": 9,
            }
        ]
        assert _params(session)["country"] == "gb"
        assert _params(session)["granularity"] == "weekly"

    @parameterized.expand([("visits", VISITS, "visits"), ("page_views", PAGE_VIEWS, "page_views")])
    def test_v5_engagement_hits_the_multimetric_endpoint_with_header_auth(
        self, _name: str, endpoint: str, metric: str
    ) -> None:
        session = _session(_response(json_body=_v5_series_body(metric, [{"date": "2024-01-01", metric: 9}])))

        rows = _run(endpoint, session, domains="a.com", api_version=API_VERSION_V5)[0]

        # One `/v5/website-analysis` endpoint serves every metric; the table selects its own via
        # `metrics`, the key moves to the `api-key` header, and rows come from the `data` envelope.
        assert _urls(session) == [f"{BASE_URL}{V5_ENGAGEMENT_PATH}"]
        assert _params(session)["metrics"] == metric
        assert _params(session)["domain"] == "a.com"
        assert "api_key" not in _params(session)
        assert _headers(session) == {"api-key": "key-123"}
        assert rows == [
            {
                "domain": "a.com",
                "country": "world",
                "granularity": "monthly",
                "date": datetime(2024, 1, 1, tzinfo=UTC),
                metric: 9,
            }
        ]

    def test_v5_pin_leaves_non_engagement_tables_on_the_legacy_wire(self) -> None:
        # Only the engagement family has a documented V5 wire; rank keeps its legacy path and
        # query-param key even under the V5 pin, so a new V5 source still syncs it.
        session = _session(_response(json_body=_series_body("global_rank", [{"date": "2024-01", "global_rank": 86}])))

        _run(GLOBAL_RANK, session, domains="a.com", api_version=API_VERSION_V5)

        assert _urls(session) == [f"{BASE_URL}/v1/website/a.com/global-rank/global-rank"]
        assert _params(session)["api_key"] == "key-123"
        assert _headers(session) is None

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
        session = _session(_response(json_body={"visits": [], "data": []}))

        _run(VISITS, session, domains="a.com", country=country, api_version=api_version)

        assert _params(session)["country"] == expected_param

    def test_global_rank_takes_no_filters_and_parses_month_dates(self) -> None:
        session = _session(_response(json_body=_series_body("global_rank", [{"date": "2024-01", "global_rank": 86}])))

        rows = _run(GLOBAL_RANK, session, domains="a.com", country="gb")[0]

        assert rows == [{"domain": "a.com", "date": datetime(2024, 1, 1, tzinfo=UTC), "global_rank": 86}]
        assert "country" not in _params(session)
        assert "granularity" not in _params(session)

    def test_traffic_sources_flattens_channels(self) -> None:
        session = _session(
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
        )

        rows = _run(TRAFFIC_SOURCES, session, domains="a.com")[0]

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
        session = _session(
            _response(status=status),
            _response(json_body=_series_body("visits", [{"date": "2024-01-01", "visits": 7}])),
        )

        rows = [row for batch in _run(VISITS, session) for row in batch]

        assert [row["domain"] for row in rows] == ["b.com"]

    def test_unexpected_status_fails_the_sync(self) -> None:
        session = _session(_response(status=500))

        with pytest.raises(requests.HTTPError):
            _run(VISITS, session, domains="a.com")

    def test_connection_error_is_reraised_without_the_api_key(self) -> None:
        session = mock.MagicMock(spec=requests.Session)
        session.get.side_effect = requests.ConnectionError(
            "Max retries exceeded with url: /v1/website/a.com/...?api_key=key-123&format=json"
        )

        with pytest.raises(requests.ConnectionError) as excinfo:
            _run(VISITS, session, domains="a.com")

        assert "key-123" not in str(excinfo.value)
        assert "Similarweb request failed" in str(excinfo.value)

    def test_rows_with_an_unparsable_period_are_dropped(self) -> None:
        session = _session(
            _response(
                json_body=_series_body(
                    "visits", [{"date": "not-a-date", "visits": 1}, {"date": "2024-01-01", "visits": 2}]
                )
            )
        )

        rows = _run(VISITS, session, domains="a.com")[0]

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
        granularity: str,
        start_date: Optional[str],
        should_use_incremental_field: bool,
        last_value: Any,
        expected_start: Optional[str],
        expected_end: Optional[str],
    ) -> None:
        session = _session(_response(json_body=_series_body("visits", [])))

        with freeze_time("2024-06-15"):
            _run(
                VISITS,
                session,
                domains="a.com",
                granularity=granularity,
                start_date=start_date,
                should_use_incremental_field=should_use_incremental_field,
                db_incremental_field_last_value=last_value,
            )

        assert _params(session).get("start_date") == expected_start
        assert _params(session).get("end_date") == expected_end

    def test_api_key_is_sent_as_a_query_param_and_registered_for_redaction(self) -> None:
        session = _session(_response(json_body=_series_body("visits", [])))

        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session) as make_session:
            list(
                cast(
                    Iterable[Any],
                    similarweb_source(
                        api_key="key-123",
                        domains="a.com",
                        country=None,
                        granularity="monthly",
                        start_date=None,
                        endpoint=VISITS,
                        logger=mock.MagicMock(),
                        resumable_source_manager=FakeResumeManager(),
                        api_version=API_VERSION_LEGACY,
                    ).items(),
                )
            )

        assert make_session.call_args.kwargs["redact_values"] == ("key-123",)
        assert _params(session)["api_key"] == "key-123"

    def test_paginated_endpoint_walks_offsets_and_checkpoints_each_page(self) -> None:
        full_page = [{"country": index, "visits": 1} for index in range(PAGE_LIMIT)]
        manager = FakeResumeManager()
        session = _session(
            _response(json_body={"records": full_page}),
            _response(json_body={"records": [{"country": 999, "visits": 2}]}),
            _response(json_body={"records": []}),
        )

        batches = _run(TRAFFIC_BY_COUNTRY, session, manager=manager)

        assert [_params(session, index)["offset"] for index in range(3)] == [0, PAGE_LIMIT, 0]
        assert batches[0][0] == {"domain": "a.com", "country": 0, "visits": 1}
        assert [(state.next_domain_index, state.next_offset) for state in manager.saved] == [
            (0, PAGE_LIMIT),
            (1, 0),
            (2, 0),
        ]
        assert manager.cleared is True

    def test_paginated_endpoint_resumes_from_saved_state(self) -> None:
        manager = FakeResumeManager(SimilarwebResumeConfig(next_domain_index=1, next_offset=PAGE_LIMIT))
        session = _session(_response(json_body={"records": [{"country": 840}]}))

        batches = _run(TRAFFIC_BY_COUNTRY, session, manager=manager)

        assert [url.split("/website/")[1].split("/")[0] for url in _urls(session)] == ["b.com"]
        assert _params(session)["offset"] == PAGE_LIMIT
        assert batches[0][0]["domain"] == "b.com"

    @parameterized.expand(
        [
            ("ok", 200, True, None),
            ("forbidden", 403, False, "Similarweb rejected the API key"),
            ("server_error", 500, False, "Unexpected response"),
        ]
    )
    def test_validate_credentials_status_mapping(
        self, _name: str, status: int, expected_ok: bool, expected_message: Optional[str]
    ) -> None:
        # A failing status must be reported back to source creation, not raised.
        session = _session(_response(status=status))

        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            is_valid, message = validate_credentials("key-123")

        assert is_valid is expected_ok
        if expected_message is None:
            assert message is None
        else:
            assert message is not None and expected_message in message

    def test_validate_credentials_reports_unreachable_api(self) -> None:
        session = mock.MagicMock(spec=requests.Session)
        session.get.side_effect = requests.ConnectionError("boom")

        with mock.patch(f"{MODULE}.make_tracked_session", return_value=session):
            is_valid, message = validate_credentials("key-123")

        assert is_valid is False
        assert message is not None and "Could not reach the Similarweb API" in message
