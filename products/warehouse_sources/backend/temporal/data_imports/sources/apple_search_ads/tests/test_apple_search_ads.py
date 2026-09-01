import dataclasses
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from typing import Any, Optional, cast

import pytest
from unittest import mock

import jwt
import structlog
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from parameterized import parameterized
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.apple_search_ads.apple_search_ads import (
    APPLE_ADS_HOST,
    APPLE_OAUTH_AUDIENCE,
    APPLE_OAUTH_TOKEN_URL,
    APPLE_SEARCH_ADS_HOST,
    AppleSearchAdsAuthError,
    AppleSearchAdsClient,
    AppleSearchAdsCredentials,
    AppleSearchAdsResumeConfig,
    ReportWindow,
    _report_start_date,
    _report_windows,
    apple_search_ads_source,
    build_client_secret,
    flatten_acl_rows,
    flatten_report_rows,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.apple_search_ads.settings import (
    APPLE_ADS_API_VERSION_V1,
    APPLE_SEARCH_ADS_API_VERSION_V5,
    DEFAULT_INITIAL_LOOKBACK_DAYS,
    ENDPOINTS,
    PAGE_SIZE,
    REPORT_WINDOW_DAYS,
    ReportingLimits,
    endpoints_for_version,
    reporting_limits_for_version,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.apple_search_ads."
    "apple_search_ads.make_tracked_session"
)
TODAY_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.apple_search_ads.apple_search_ads._today"
)

V5 = APPLE_SEARCH_ADS_API_VERSION_V5
V1 = APPLE_ADS_API_VERSION_V1
BASE_URL = {V5: f"{APPLE_SEARCH_ADS_HOST}/api/{V5}", V1: f"{APPLE_ADS_HOST}/{V1}"}

_private_key = ec.generate_private_key(ec.SECP256R1())
PRIVATE_KEY_PEM = _private_key.private_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PrivateFormat.PKCS8,
    encryption_algorithm=serialization.NoEncryption(),
).decode()
PUBLIC_KEY_PEM = (
    _private_key.public_key()
    .public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    .decode()
)

CREDENTIALS = AppleSearchAdsCredentials(
    client_id="SEARCHADS.client",
    team_id="SEARCHADS.team",
    key_id="key-1",
    private_key=PRIVATE_KEY_PEM,
    org_id="555",
    ad_account_id="123456789",
)

LOGGER = cast(Any, structlog.get_logger(__name__))

# What each version calls the per-day metric buckets on a report row.
METRICS_KEY = {V5: "granularity", V1: "granularMetrics"}


def _with_key(private_key: str) -> AppleSearchAdsCredentials:
    return dataclasses.replace(CREDENTIALS, private_key=private_key)


class _FakeResponse:
    def __init__(self, status_code: int = 200, json_data: Optional[dict[str, Any]] = None, url: str = BASE_URL[V5]):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.url = url
        self.text = str(self._json_data)

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    def json(self) -> dict[str, Any]:
        return self._json_data

    def raise_for_status(self) -> None:
        if not self.ok:
            kind = "Client Error" if self.status_code < 500 else "Server Error"
            raise HTTPError(f"{self.status_code} {kind}: for url: {self.url}", response=cast(Any, None))


def _token_response(token: str = "access-token") -> _FakeResponse:
    return _FakeResponse(200, {"access_token": token, "expires_in": 3600}, url=APPLE_OAUTH_TOKEN_URL)


class _FakeSession:
    """Replays queued API responses and records every request the client made."""

    def __init__(self, api_responses: list[_FakeResponse], token_responses: Optional[list[_FakeResponse]] = None):
        self._api_responses = list(api_responses)
        self._token_responses = list(token_responses) if token_responses is not None else None
        self.calls: list[dict[str, Any]] = []

    @property
    def api_calls(self) -> list[dict[str, Any]]:
        return [call for call in self.calls if call["url"] != APPLE_OAUTH_TOKEN_URL]

    @property
    def token_calls(self) -> list[dict[str, Any]]:
        return [call for call in self.calls if call["url"] == APPLE_OAUTH_TOKEN_URL]

    def _next(self, url: str) -> _FakeResponse:
        if url == APPLE_OAUTH_TOKEN_URL:
            if self._token_responses is not None:
                return self._token_responses.pop(0)
            return _token_response()
        if not self._api_responses:
            raise AssertionError(f"unexpected extra request to {url}")
        return self._api_responses.pop(0)

    def get(
        self,
        url: str,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> _FakeResponse:
        self.calls.append({"method": "GET", "url": url, "params": params, "headers": headers or {}})
        return self._next(url)

    def post(
        self,
        url: str,
        json: Optional[dict[str, Any]] = None,
        data: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        timeout: Optional[float] = None,
    ) -> _FakeResponse:
        self.calls.append({"method": "POST", "url": url, "json": json, "data": data, "headers": headers or {}})
        return self._next(url)


class _FakeResumableManager(ResumableSourceManager[AppleSearchAdsResumeConfig]):
    """In-memory stand-in for the Redis-backed manager (no `super().__init__`)."""

    def __init__(self, resume_state: Optional[AppleSearchAdsResumeConfig] = None):
        self._resume_state = resume_state
        self.saved_states: list[AppleSearchAdsResumeConfig] = []
        self.cleared = False

    def can_resume(self) -> bool:
        return self._resume_state is not None

    def load_state(self) -> AppleSearchAdsResumeConfig | None:
        return self._resume_state

    def save_state(self, data: AppleSearchAdsResumeConfig) -> None:
        self.saved_states.append(data)

    def clear_state(self) -> None:
        self.cleared = True


def _entity_page(rows: list[dict[str, Any]], api_version: str = V5) -> _FakeResponse:
    if api_version == V1:
        return _FakeResponse(200, {"result": rows, "pagination": {"offset": 0, "pageSize": PAGE_SIZE}})
    return _FakeResponse(200, {"data": rows, "pagination": {"totalResults": len(rows)}})


def _acls_page(accounts: list[dict[str, Any]]) -> _FakeResponse:
    return _FakeResponse(200, {"result": {"acls": accounts}})


def _report_payload(rows: list[dict[str, Any]], api_version: str = V5) -> dict[str, Any]:
    if api_version == V1:
        return {"result": {"rows": rows}, "pagination": {"offset": 0, "pageSize": PAGE_SIZE}}
    return {"data": {"reportingDataResponse": {"row": rows}}}


def _report_page(rows: list[dict[str, Any]], api_version: str = V5) -> _FakeResponse:
    return _FakeResponse(200, _report_payload(rows, api_version))


def _report_row(metadata: dict[str, Any], dates: list[str], api_version: str = V5) -> dict[str, Any]:
    return {
        "metadata": metadata,
        METRICS_KEY[api_version]: [{"date": day, "impressions": 10, "taps": 1} for day in dates],
    }


def _run(
    endpoint: str,
    session: _FakeSession,
    manager: _FakeResumableManager,
    api_version: str = V5,
    **kwargs: Any,
) -> list[list[dict[str, Any]]]:
    with mock.patch(SESSION_PATCH, return_value=session):
        return list(
            get_rows(
                credentials=CREDENTIALS,
                endpoint=endpoint,
                api_version=api_version,
                request_logger=LOGGER,
                resumable_source_manager=manager,
                **kwargs,
            )
        )


class TestAppleSearchAdsTransport:
    def test_client_secret_is_a_signed_es256_assertion(self) -> None:
        token = build_client_secret(CREDENTIALS, issued_at=1_700_000_000)

        header = jwt.get_unverified_header(token)
        assert header["alg"] == "ES256"
        assert header["kid"] == "key-1"

        claims = jwt.decode(
            token,
            PUBLIC_KEY_PEM,
            algorithms=["ES256"],
            audience=APPLE_OAUTH_AUDIENCE,
            options={"verify_exp": False},
        )
        assert claims["sub"] == CREDENTIALS.client_id
        assert claims["iss"] == CREDENTIALS.team_id
        assert claims["iat"] == 1_700_000_000
        assert claims["exp"] > claims["iat"]

    def test_client_secret_accepts_a_pem_with_escaped_newlines(self) -> None:
        escaped = CREDENTIALS.private_key.replace("\n", "\\n")
        token = build_client_secret(_with_key(escaped))

        assert jwt.decode(token, PUBLIC_KEY_PEM, algorithms=["ES256"], audience=APPLE_OAUTH_AUDIENCE)

    @parameterized.expand(
        [
            ("garbage", "not-a-key"),
            ("empty", ""),
            ("truncated_pem", "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----"),
        ]
    )
    def test_client_secret_rejects_an_unusable_private_key(self, _name: str, private_key: str) -> None:
        with pytest.raises(AppleSearchAdsAuthError):
            build_client_secret(_with_key(private_key))

    @parameterized.expand([(V5, "orgId=555"), (V1, "adAccountId=123456789")])
    def test_requests_carry_the_bearer_token_and_the_versions_context_id(
        self, api_version: str, expected_context: str
    ) -> None:
        session = _FakeSession([_entity_page([{"id": 1}], api_version)])
        manager = _FakeResumableManager()

        _run("campaigns", session, manager, api_version=api_version)

        assert len(session.token_calls) == 1
        token_body = session.token_calls[0]["data"]
        assert token_body["grant_type"] == "client_credentials"
        assert token_body["client_id"] == CREDENTIALS.client_id
        assert token_body["scope"] == "searchadsorg"

        headers = session.api_calls[0]["headers"]
        assert headers["Authorization"] == "Bearer access-token"
        # v5 scopes to an organization, the Platform API to an ad account, and the two ids are
        # different values.
        assert headers["X-AP-Context"] == expected_context

    @parameterized.expand([(V5,), (V1,)])
    def test_acls_is_a_single_page_without_the_context_header(self, api_version: str) -> None:
        response = (
            _acls_page([{"adAccount": {"id": 9, "orgId": 555}, "roles": ["Admin"]}])
            if api_version == V1
            else _entity_page([{"orgId": 555}])
        )
        session = _FakeSession([response])
        manager = _FakeResumableManager()

        batches = _run("acls", session, manager, api_version=api_version)

        assert len(session.api_calls) == 1
        assert session.api_calls[0]["url"] == f"{BASE_URL[api_version]}/acls"
        assert "X-AP-Context" not in session.api_calls[0]["headers"]
        assert batches[0][0]["orgId"] == 555

    @parameterized.expand([(V5,), (V1,)])
    def test_expired_access_token_is_reminted_once_and_the_request_replayed(self, api_version: str) -> None:
        session = _FakeSession(
            [_FakeResponse(401, url=BASE_URL[api_version]), _entity_page([{"id": 1}], api_version)],
            token_responses=[_token_response("first"), _token_response("second")],
        )
        manager = _FakeResumableManager()

        batches = _run("campaigns", session, manager, api_version=api_version)

        assert batches == [[{"id": 1}]]
        assert len(session.token_calls) == 2
        assert session.api_calls[0]["headers"]["Authorization"] == "Bearer first"
        assert session.api_calls[1]["headers"]["Authorization"] == "Bearer second"

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("server_error", 500)])
    def test_a_persistent_error_status_raises(self, _name: str, status: int) -> None:
        # Two identical failures so the single 401 re-mint retry is exhausted too.
        session = _FakeSession([_FakeResponse(status, url=BASE_URL[V5]), _FakeResponse(status, url=BASE_URL[V5])])
        manager = _FakeResumableManager()

        with pytest.raises(HTTPError):
            _run("campaigns", session, manager)

    @parameterized.expand([(V5,), (V1,)])
    def test_entity_pagination_advances_the_offset_and_checkpoints_between_pages(self, api_version: str) -> None:
        first_page = [{"id": index} for index in range(PAGE_SIZE)]
        session = _FakeSession(
            [_entity_page(first_page, api_version), _entity_page([{"id": PAGE_SIZE}], api_version)],
        )
        manager = _FakeResumableManager()

        batches = _run("campaigns", session, manager, api_version=api_version)

        assert [len(batch) for batch in batches] == [PAGE_SIZE, 1]
        assert [_offset_of(call, api_version) for call in session.api_calls] == [0, PAGE_SIZE]
        assert [state.offset for state in manager.saved_states] == [PAGE_SIZE]
        assert manager.cleared is True

    @parameterized.expand([(V5,), (V1,)])
    def test_entity_pagination_resumes_from_the_saved_offset(self, api_version: str) -> None:
        session = _FakeSession([_entity_page([{"id": 1}], api_version)])
        manager = _FakeResumableManager(AppleSearchAdsResumeConfig(offset=2000))

        _run("campaigns", session, manager, api_version=api_version)

        assert _offset_of(session.api_calls[0], api_version) == 2000

    @parameterized.expand([(V5,), (V1,)])
    def test_empty_first_page_yields_nothing_and_terminates(self, api_version: str) -> None:
        # The Platform API scopes keywords per campaign, so it needs the campaign list first.
        responses = [_entity_page([{"id": 10}], V1), _entity_page([], V1)] if api_version == V1 else [_entity_page([])]
        session = _FakeSession(responses)
        manager = _FakeResumableManager()

        assert _run("keywords", session, manager, api_version=api_version) == []


def _offset_of(call: dict[str, Any], api_version: str) -> int:
    """Requested offset, wherever this version puts it."""
    if api_version == V1:
        return call["json"]["pagination"]["offset"]
    return call["params"]["offset"]


class TestVersionFivePaths:
    def test_find_endpoints_page_in_the_request_body(self) -> None:
        session = _FakeSession([_entity_page([{"id": 7}])])

        _run("ad_groups", session, _FakeResumableManager())

        call = session.api_calls[0]
        assert call["method"] == "POST"
        assert call["url"] == f"{BASE_URL[V5]}/adgroups/find"
        assert call["json"]["pagination"] == {"offset": 0, "limit": PAGE_SIZE}

    def test_reports_page_inside_a_selector(self) -> None:
        session = _FakeSession([_report_page([_report_row({"campaignId": 1}, ["2026-01-01"])])])

        with mock.patch(TODAY_PATCH, return_value=date(2026, 1, 2)):
            _run(
                "campaign_report",
                session,
                _FakeResumableManager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=date(2026, 1, 1),
            )

        body = session.api_calls[0]["json"]
        assert body["granularity"] == "DAILY"
        assert body["timeZone"] == "ORTZ"
        assert (body["startTime"], body["endTime"]) == ("2026-01-01", "2026-01-02")
        assert body["selector"]["pagination"] == {"offset": 0, "limit": PAGE_SIZE}

    def test_the_campaign_report_reads_the_whole_organization_in_one_request(self) -> None:
        session = _FakeSession([_report_page([_report_row({"campaignId": 1}, ["2026-01-01"])])])

        with mock.patch(TODAY_PATCH, return_value=date(2026, 1, 2)):
            _run(
                "campaign_report",
                session,
                _FakeResumableManager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=date(2026, 1, 1),
            )

        # No campaign list is fetched: v5 serves this report org-wide.
        assert [call["url"] for call in session.api_calls] == [f"{BASE_URL[V5]}/reports/campaigns"]


class TestPlatformApiPaths:
    def test_entity_collections_are_read_through_a_query_body(self) -> None:
        session = _FakeSession([_entity_page([{"id": 7}], V1)])

        _run("ad_groups", session, _FakeResumableManager(), api_version=V1)

        call = session.api_calls[0]
        assert call["method"] == "POST"
        assert call["url"] == f"{BASE_URL[V1]}/adgroups/query"
        assert call["json"] == {"pagination": {"offset": 0, "pageSize": PAGE_SIZE}}

    def test_keywords_are_scoped_per_campaign(self) -> None:
        session = _FakeSession(
            [
                _entity_page([{"id": 20}, {"id": 10}], V1),
                _entity_page([{"id": 1}], V1),
                _entity_page([{"id": 2}], V1),
            ]
        )

        _run("keywords", session, _FakeResumableManager(), api_version=V1)

        keyword_calls = [call for call in session.api_calls if call["url"].endswith("/keywords/query")]
        # Apple rejects a keyword query that scopes neither a campaign nor an ad group, and the
        # ids are visited in a stable ascending order rather than response order.
        assert [call["json"]["filters"] for call in keyword_calls] == [
            [{"field": "campaignId", "operator": "EQUALS", "value": 10}],
            [{"field": "campaignId", "operator": "EQUALS", "value": 20}],
        ]

    def test_reports_carry_a_time_range_and_a_required_campaign_filter(self) -> None:
        session = _FakeSession(
            [
                _entity_page([{"id": 10}], V1),
                _report_page([_report_row({"id": 10}, ["2026-06-01"], V1)], V1),
            ]
        )

        with mock.patch(TODAY_PATCH, return_value=date(2026, 6, 2)):
            _run(
                "campaign_report",
                session,
                _FakeResumableManager(),
                api_version=V1,
                should_use_incremental_field=True,
                db_incremental_field_last_value=date(2026, 6, 1),
            )

        report_call = next(call for call in session.api_calls if "/reports/" in call["url"])
        assert report_call["url"] == f"{BASE_URL[V1]}/reports/apps/campaigns/query"
        body = report_call["json"]
        assert body["timeRange"] == {
            "start": "2026-06-01",
            "end": "2026-06-02",
            "timeZone": "ORTZ",
            "granularity": "DAILY",
        }
        assert body["pagination"] == {"offset": 0, "pageSize": PAGE_SIZE}
        # Apple requires a campaignId filter on every apps report, including the campaign level,
        # and documents the value as an array of strings.
        assert body["filters"] == [{"field": "campaignId", "operator": "EQUALS", "value": ["10"]}]
        # Unsegmented daily rows, so no groupBy is sent.
        assert "groupBy" not in body

    def test_the_campaign_report_fans_out_over_every_campaign(self) -> None:
        session = _FakeSession(
            [
                _entity_page([{"id": 20}, {"id": 10}], V1),
                _report_page([_report_row({"id": 10}, ["2026-06-01"], V1)], V1),
                _report_page([_report_row({"id": 20}, ["2026-06-01"], V1)], V1),
            ]
        )

        with mock.patch(TODAY_PATCH, return_value=date(2026, 6, 2)):
            batches = _run(
                "campaign_report",
                session,
                _FakeResumableManager(),
                api_version=V1,
                should_use_incremental_field=True,
                db_incremental_field_last_value=date(2026, 6, 1),
            )

        assert [row["campaignId"] for batch in batches for row in batch] == [10, 20]

    def test_acl_rows_become_one_row_per_ad_account(self) -> None:
        session = _FakeSession(
            [
                _acls_page(
                    [
                        {"adAccount": {"id": 123456789, "name": "Account A", "orgId": 555}, "roles": ["Admin"]},
                        {"adAccount": {"id": 987654321, "name": "Account B", "orgId": 555}, "roles": ["Read Only"]},
                    ]
                )
            ]
        )

        batches = _run("acls", session, _FakeResumableManager(), api_version=V1)

        # `orgId` repeats across ad accounts under one token, so `id` is what identifies a row.
        assert batches[0] == [
            {"id": 123456789, "name": "Account A", "orgId": 555, "roles": ["Admin"]},
            {"id": 987654321, "name": "Account B", "orgId": 555, "roles": ["Read Only"]},
        ]


class TestReportWindows:
    @parameterized.expand(
        [
            (
                "single_day",
                date(2026, 1, 1),
                date(2026, 1, 1),
                [ReportWindow(start=date(2026, 1, 1), end=date(2026, 1, 1))],
            ),
            (
                "exactly_one_window",
                date(2026, 1, 1),
                date(2026, 1, 7),
                [ReportWindow(start=date(2026, 1, 1), end=date(2026, 1, 7))],
            ),
            (
                "spills_into_a_second_window",
                date(2026, 1, 1),
                date(2026, 1, 9),
                [
                    ReportWindow(start=date(2026, 1, 1), end=date(2026, 1, 7)),
                    ReportWindow(start=date(2026, 1, 8), end=date(2026, 1, 9)),
                ],
            ),
            ("end_before_start", date(2026, 1, 9), date(2026, 1, 1), []),
        ]
    )
    def test_windows_are_ascending_and_inclusive(
        self, _name: str, start: date, end: date, expected: list[ReportWindow]
    ) -> None:
        assert _report_windows(start, end) == expected

    def test_windows_never_exceed_the_configured_length(self) -> None:
        windows = _report_windows(date(2026, 1, 1), date(2026, 3, 1))

        assert all((window.end - window.start).days + 1 <= REPORT_WINDOW_DAYS for window in windows)
        # Contiguous with no gaps or overlaps.
        assert all(later.start == earlier.end + timedelta(days=1) for earlier, later in zip(windows, windows[1:]))

    @parameterized.expand(
        [
            ("whole_range_is_one_day", date(2026, 1, 8), date(2026, 1, 8), date(2026, 1, 7)),
            ("trailing_window_is_one_day", date(2026, 1, 1), date(2026, 1, 8), date(2026, 1, 7)),
        ]
    )
    def test_a_one_day_window_reaches_back_far_enough_for_the_platform_api(
        self, _name: str, start: date, end: date, expected_last_start: date
    ) -> None:
        # The Platform API rejects a DAILY range covering a single day, so the window widens
        # rather than sending a request Apple would refuse.
        windows = _report_windows(start, end, min_window_days=2)

        assert windows[-1] == ReportWindow(start=expected_last_start, end=end)
        assert all((window.end - window.start).days + 1 >= 2 for window in windows)

    @parameterized.expand(
        [
            ("watermark_wins", True, date(2026, 5, 1), "2020-01-01", date(2026, 5, 1)),
            ("iso_string_watermark", True, "2026-05-01", None, date(2026, 5, 1)),
            ("datetime_watermark", True, datetime(2026, 5, 1, 6, 30), None, date(2026, 5, 1)),
            ("configured_start_date", False, None, "2026-02-03", date(2026, 2, 3)),
            ("unparseable_start_date_falls_back", False, None, "not-a-date", None),
            ("no_watermark_no_start_date", False, None, None, None),
            ("incremental_without_watermark", True, None, None, None),
        ]
    )
    def test_report_start_date(
        self,
        _name: str,
        should_use_incremental_field: bool,
        watermark: Any,
        start_date: Optional[str],
        expected: Optional[date],
    ) -> None:
        today = date(2026, 6, 1)
        limits = ReportingLimits(max_lookback_days=24 * 30, min_window_days=1)
        resolved = _report_start_date(should_use_incremental_field, watermark, start_date, today, limits)

        assert resolved == (expected or today - timedelta(days=DEFAULT_INITIAL_LOOKBACK_DAYS))

    @parameterized.expand(
        [
            ("ancient_configured_start", False, None, "0001-01-01"),
            # A source that fell further behind than Apple serves would otherwise ask for a day
            # Apple refuses, and fail every run instead of resuming at the oldest readable day.
            ("watermark_older_than_the_window", True, date(2020, 1, 1), None),
            ("default_lookback_exceeds_the_window", False, None, None),
        ]
    )
    def test_every_start_date_is_floored_at_the_versions_oldest_readable_day(
        self, _name: str, should_use_incremental_field: bool, watermark: Any, start_date: Optional[str]
    ) -> None:
        today = date(2026, 6, 1)
        limits = reporting_limits_for_version(V1)

        resolved = _report_start_date(should_use_incremental_field, watermark, start_date, today, limits)

        assert resolved == today - timedelta(days=limits.max_lookback_days)

    def test_platform_api_reporting_limits_stay_inside_apples_daily_rules(self) -> None:
        limits = reporting_limits_for_version(V1)

        # Apple serves DAILY reporting for ranges starting within the last 90 days, and rejects
        # a range covering a single day.
        assert limits.max_lookback_days < 90
        assert limits.min_window_days == 2


class TestFlattenReportRows:
    @parameterized.expand([(V5,), (V1,)])
    def test_daily_buckets_become_one_row_per_day(self, api_version: str) -> None:
        rows = [_report_row({"campaignId": 1, "campaignName": "A"}, ["2026-01-01", "2026-01-02"], api_version)]

        flattened = flatten_report_rows(rows, metrics_key=METRICS_KEY[api_version])

        assert flattened == [
            {"campaignId": 1, "campaignName": "A", "date": "2026-01-01", "impressions": 10, "taps": 1},
            {"campaignId": 1, "campaignName": "A", "date": "2026-01-02", "impressions": 10, "taps": 1},
        ]

    def test_fan_out_injects_the_campaign_id_the_primary_key_needs(self) -> None:
        rows = [_report_row({"adGroupId": 9}, ["2026-01-01"])]

        flattened = flatten_report_rows(rows, metrics_key=METRICS_KEY[V5], campaign_id=42)

        assert flattened[0]["campaignId"] == 42
        assert flattened[0]["adGroupId"] == 9

    def test_fan_out_does_not_clobber_a_campaign_id_apple_supplied(self) -> None:
        rows = [_report_row({"campaignId": 7, "adGroupId": 9}, ["2026-01-01"])]

        assert flatten_report_rows(rows, metrics_key=METRICS_KEY[V5], campaign_id=42)[0]["campaignId"] == 7

    @parameterized.expand(
        [
            ("campaign_report", "campaignId", {"id": 10, "name": "A"}),
            ("ad_group_report", "adGroupId", {"id": 55, "campaignId": 10}),
            ("keyword_report", "keywordId", {"id": 88, "campaignId": 10, "adGroupId": 55}),
        ]
    )
    def test_the_platform_apis_entity_id_is_projected_onto_the_primary_key_column(
        self, endpoint: str, entity_id_field: str, metadata: dict[str, Any]
    ) -> None:
        # The Platform API names every report level's own entity `id`, where v5 named it after
        # the level. Without this projection the table's primary key column would be missing.
        rows = [_report_row(metadata, ["2026-06-01"], V1)]

        flattened = flatten_report_rows(rows, metrics_key=METRICS_KEY[V1], entity_id_field=entity_id_field)

        assert flattened[0][entity_id_field] == metadata["id"]
        # Projected, not duplicated, so the value does not arrive under two column names.
        assert "id" not in flattened[0]
        assert set(endpoints_for_version(V1)[endpoint].primary_keys) <= set(flattened[0])

    @parameterized.expand(
        [
            ("no_daily_buckets", [{"metadata": {"campaignId": 1}}]),
            ("empty_row_list", []),
        ]
    )
    def test_rows_without_daily_metrics_flatten_to_nothing(self, _name: str, rows: list[dict[str, Any]]) -> None:
        assert flatten_report_rows(rows, metrics_key=METRICS_KEY[V5]) == []

    def test_acl_entries_without_an_ad_account_are_skipped(self) -> None:
        assert flatten_acl_rows([{"roles": ["Admin"]}, {"adAccount": None}]) == []


class TestReportSync:
    def test_campaign_report_requests_one_windowed_page_per_window(self) -> None:
        session = _FakeSession(
            [
                _report_page([_report_row({"campaignId": 1}, ["2026-01-01"])]),
                _report_page([_report_row({"campaignId": 1}, ["2026-01-08"])]),
            ]
        )
        manager = _FakeResumableManager()

        with mock.patch(TODAY_PATCH, return_value=date(2026, 1, 9)):
            batches = _run(
                "campaign_report",
                session,
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=date(2026, 1, 1),
            )

        assert [row["date"] for batch in batches for row in batch] == ["2026-01-01", "2026-01-08"]
        bodies = [call["json"] for call in session.api_calls]
        assert [(body["startTime"], body["endTime"]) for body in bodies] == [
            ("2026-01-01", "2026-01-07"),
            ("2026-01-08", "2026-01-09"),
        ]
        # After the first window completes, the checkpoint points at the next window.
        assert manager.saved_states[0] == AppleSearchAdsResumeConfig(
            offset=0, window_start="2026-01-08", campaign_id=None
        )

    def test_fan_out_reports_walk_every_campaign_in_every_window(self) -> None:
        session = _FakeSession(
            [
                _entity_page([{"id": 20}, {"id": 10}]),
                _report_page([_report_row({"adGroupId": 1}, ["2026-01-01"])]),
                _report_page([_report_row({"adGroupId": 2}, ["2026-01-01"])]),
            ]
        )
        manager = _FakeResumableManager()

        with mock.patch(TODAY_PATCH, return_value=date(2026, 1, 3)):
            batches = _run(
                "ad_group_report",
                session,
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=date(2026, 1, 1),
            )

        report_calls = [call for call in session.api_calls if "/reports/" in call["url"]]
        # Campaign ids are visited in a stable ascending order, not response order.
        assert [call["url"] for call in report_calls] == [
            f"{BASE_URL[V5]}/reports/campaigns/10/adgroups",
            f"{BASE_URL[V5]}/reports/campaigns/20/adgroups",
        ]
        assert [row["campaignId"] for batch in batches for row in batch] == [10, 20]
        assert manager.saved_states[0] == AppleSearchAdsResumeConfig(
            offset=0, window_start="2026-01-01", campaign_id=20
        )

    @parameterized.expand([(V5,), (V1,)])
    def test_fan_out_reports_resume_at_the_checkpointed_campaign(self, api_version: str) -> None:
        session = _FakeSession(
            [
                _entity_page([{"id": 10}, {"id": 20}], api_version),
                _report_page([_report_row({"adGroupId": 2}, ["2026-06-01"], api_version)], api_version),
            ]
        )
        manager = _FakeResumableManager(AppleSearchAdsResumeConfig(offset=0, window_start="2026-06-01", campaign_id=20))

        with mock.patch(TODAY_PATCH, return_value=date(2026, 6, 3)):
            _run(
                "ad_group_report",
                session,
                manager,
                api_version=api_version,
                should_use_incremental_field=True,
                db_incremental_field_last_value=date(2026, 6, 1),
            )

        report_calls = [call for call in session.api_calls if "/reports/" in call["url"]]
        assert len(report_calls) == 1
        if api_version == V1:
            assert report_calls[0]["json"]["filters"][0]["value"] == ["20"]
        else:
            assert report_calls[0]["url"].endswith("/reports/campaigns/20/adgroups")

    def test_a_checkpoint_outside_this_runs_windows_restarts_the_range(self) -> None:
        session = _FakeSession([_report_page([_report_row({"campaignId": 1}, ["2026-01-01"])])])
        manager = _FakeResumableManager(
            AppleSearchAdsResumeConfig(offset=500, window_start="2019-01-01", campaign_id=None)
        )

        with mock.patch(TODAY_PATCH, return_value=date(2026, 1, 3)):
            _run(
                "campaign_report",
                session,
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=date(2026, 1, 1),
            )

        body = session.api_calls[0]["json"]
        assert body["startTime"] == "2026-01-01"
        assert body["selector"]["pagination"]["offset"] == 0

    @parameterized.expand([(V5,), (V1,)])
    def test_report_pagination_continues_while_a_page_is_full(self, api_version: str) -> None:
        full_page = [_report_row({"campaignId": index}, ["2026-06-01"], api_version) for index in range(PAGE_SIZE)]
        responses = [
            _report_page(full_page, api_version),
            _report_page([_report_row({"campaignId": 9999}, ["2026-06-01"], api_version)], api_version),
        ]
        if api_version == V1:
            # The Platform API needs a campaign filter on this report, so the list comes first.
            responses.insert(0, _entity_page([{"id": 1}], V1))
        session = _FakeSession(responses)
        manager = _FakeResumableManager()

        with mock.patch(TODAY_PATCH, return_value=date(2026, 6, 2)):
            _run(
                "campaign_report",
                session,
                manager,
                api_version=api_version,
                should_use_incremental_field=True,
                db_incremental_field_last_value=date(2026, 6, 1),
            )

        report_calls = [call for call in session.api_calls if "/reports/" in call["url"]]
        if api_version == V1:
            offsets = [call["json"]["pagination"]["offset"] for call in report_calls]
        else:
            offsets = [call["json"]["selector"]["pagination"]["offset"] for call in report_calls]
        assert offsets == [0, PAGE_SIZE]
        assert manager.saved_states[0].offset == PAGE_SIZE


class TestSourceResponse:
    @parameterized.expand([(endpoint, version) for endpoint in ENDPOINTS for version in (V5, V1)])
    def test_response_matches_the_endpoint_catalog(self, endpoint: str, api_version: str) -> None:
        config = endpoints_for_version(api_version)[endpoint]

        response = apple_search_ads_source(
            credentials=CREDENTIALS,
            endpoint=endpoint,
            api_version=api_version,
            request_logger=LOGGER,
            resumable_source_manager=_FakeResumableManager(),
        )

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        # Windows are walked oldest-first, so the watermark only ever moves forward.
        assert response.sort_mode == "asc"
        if config.partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]

    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_report_tables_keep_their_primary_keys_across_versions(self, endpoint: str) -> None:
        # A repinned source must not change what identifies a row, or the merge would either
        # duplicate history or collapse it.
        v5_config = endpoints_for_version(V5)[endpoint]
        v1_config = endpoints_for_version(V1)[endpoint]

        assert v5_config.partition_key == v1_config.partition_key
        assert v5_config.incremental_fields == v1_config.incremental_fields
        if endpoint == "acls":
            # The one exception: v5 returned a row per organization, the Platform API a row per
            # ad account, and every such row repeats the same `orgId`.
            assert (v5_config.primary_keys, v1_config.primary_keys) == (["orgId"], ["id"])
        else:
            assert v5_config.primary_keys == v1_config.primary_keys

    def test_items_are_lazy(self) -> None:
        response = apple_search_ads_source(
            credentials=CREDENTIALS,
            endpoint="campaigns",
            api_version=V1,
            request_logger=LOGGER,
            resumable_source_manager=_FakeResumableManager(),
        )

        # No HTTP happens until the pipeline iterates, so nothing needed mocking above.
        assert callable(response.items)
        assert isinstance(cast("Iterable[Any]", response.items()), Iterable)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, None, True),
            ("unauthorized", 401, None, False),
            ("forbidden_at_source_create", 403, None, True),
            ("forbidden_for_a_schema", 403, "campaigns", False),
            ("unexpected_status", 500, None, False),
        ]
    )
    def test_probe_status_is_mapped(self, _name: str, status: int, schema_name: Optional[str], expected: bool) -> None:
        session = _FakeSession([_FakeResponse(status, url=BASE_URL[V5]), _FakeResponse(status, url=BASE_URL[V5])])

        with mock.patch(SESSION_PATCH, return_value=session):
            is_valid, message = validate_credentials(CREDENTIALS, V5, schema_name)

        assert is_valid is expected
        assert (message is None) is expected

    @parameterized.expand(
        [
            (V5, f"{BASE_URL[V5]}/campaigns", "orgId=555"),
            (V1, f"{BASE_URL[V1]}/campaigns/query", "adAccountId=123456789"),
        ]
    )
    def test_the_probe_targets_a_context_scoped_endpoint(
        self, api_version: str, expected_url: str, expected_context: str
    ) -> None:
        session = _FakeSession([_entity_page([], api_version)])

        with mock.patch(SESSION_PATCH, return_value=session):
            assert validate_credentials(CREDENTIALS, api_version) == (True, None)

        assert session.api_calls[0]["url"] == expected_url
        assert session.api_calls[0]["headers"]["X-AP-Context"] == expected_context

    def test_a_missing_ad_account_id_names_the_accounts_the_client_can_read(self) -> None:
        credentials = dataclasses.replace(CREDENTIALS, ad_account_id=None)
        session = _FakeSession([_acls_page([{"adAccount": {"id": 123456789, "name": "Account A"}, "roles": []}])])

        with mock.patch(SESSION_PATCH, return_value=session):
            is_valid, message = validate_credentials(credentials, V1)

        assert is_valid is False
        assert message is not None
        assert "ad account ID" in message
        # The ACL lookup carries no context id, so it can answer before one is entered.
        assert "123456789 (Account A)" in message

    def test_a_missing_ad_account_id_is_still_reported_when_the_acl_lookup_fails(self) -> None:
        credentials = dataclasses.replace(CREDENTIALS, ad_account_id=None)
        session = _FakeSession([_FakeResponse(500, url=BASE_URL[V1]), _FakeResponse(500, url=BASE_URL[V1])])

        with mock.patch(SESSION_PATCH, return_value=session):
            is_valid, message = validate_credentials(credentials, V1)

        assert is_valid is False
        assert message is not None and "ad account ID" in message

    def test_a_missing_org_id_is_reported_for_the_older_api(self) -> None:
        credentials = dataclasses.replace(CREDENTIALS, org_id=None)
        session = _FakeSession([])

        with mock.patch(SESSION_PATCH, return_value=session):
            is_valid, message = validate_credentials(credentials, V5)

        assert is_valid is False
        assert message is not None and "organization ID" in message
        # No ad-account hint for a version that does not use one.
        assert session.api_calls == []

    def test_an_unusable_private_key_fails_before_any_request(self) -> None:
        session = _FakeSession([])

        with mock.patch(SESSION_PATCH, return_value=session):
            is_valid, message = validate_credentials(_with_key("nope"), V5)

        assert is_valid is False
        assert message is not None and "private key" in message
        assert session.calls == []

    def test_a_token_endpoint_rejection_is_reported(self) -> None:
        session = _FakeSession([], token_responses=[_FakeResponse(400, url=APPLE_OAUTH_TOKEN_URL)])

        with mock.patch(SESSION_PATCH, return_value=session):
            is_valid, message = validate_credentials(CREDENTIALS, V5)

        assert is_valid is False
        assert message is not None

    def test_a_token_response_without_an_access_token_is_reported(self) -> None:
        session = _FakeSession([], token_responses=[_FakeResponse(200, {}, url=APPLE_OAUTH_TOKEN_URL)])

        with mock.patch(SESSION_PATCH, return_value=session):
            is_valid, message = validate_credentials(CREDENTIALS, V5)

        assert is_valid is False
        assert message == "Apple's token response did not contain an access token"


class TestClientBaseUrl:
    @parameterized.expand(
        [
            (V5, f"{APPLE_SEARCH_ADS_HOST}/api/{V5}"),
            (V1, f"{APPLE_ADS_HOST}/{V1}"),
            # A pin the source no longer declares is honored verbatim rather than silently
            # moved, so it keeps reaching the host that served it.
            ("v4", f"{APPLE_SEARCH_ADS_HOST}/api/v4"),
        ]
    )
    def test_base_url_follows_the_resolved_api_version(self, api_version: str, expected: str) -> None:
        with mock.patch(SESSION_PATCH, return_value=_FakeSession([])):
            client = AppleSearchAdsClient(CREDENTIALS, api_version)

        assert client.base_url == expected
