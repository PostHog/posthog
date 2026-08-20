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
    flatten_report_rows,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.apple_search_ads.settings import (
    APPLE_SEARCH_ADS_ENDPOINTS,
    DEFAULT_INITIAL_LOOKBACK_DAYS,
    ENDPOINTS,
    MAX_INITIAL_LOOKBACK_DAYS,
    PAGE_SIZE,
    REPORT_WINDOW_DAYS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager

SESSION_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.apple_search_ads."
    "apple_search_ads.make_tracked_session"
)
TODAY_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.apple_search_ads.apple_search_ads._today"
)

API_VERSION = "v5"
BASE_URL = f"{APPLE_SEARCH_ADS_HOST}/api/{API_VERSION}"

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
    org_id="555",
    client_id="SEARCHADS.client",
    team_id="SEARCHADS.team",
    key_id="key-1",
    private_key=PRIVATE_KEY_PEM,
)

LOGGER = cast(Any, structlog.get_logger(__name__))


def _with_key(private_key: str) -> AppleSearchAdsCredentials:
    return dataclasses.replace(CREDENTIALS, private_key=private_key)


class _FakeResponse:
    def __init__(self, status_code: int = 200, json_data: Optional[dict[str, Any]] = None, url: str = BASE_URL):
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


def _entity_page(rows: list[dict[str, Any]]) -> _FakeResponse:
    return _FakeResponse(200, {"data": rows, "pagination": {"totalResults": len(rows)}})


def _report_payload(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {"data": {"reportingDataResponse": {"row": rows}}}


def _report_page(rows: list[dict[str, Any]]) -> _FakeResponse:
    return _FakeResponse(200, _report_payload(rows))


def _report_row(metadata: dict[str, Any], dates: list[str]) -> dict[str, Any]:
    return {
        "metadata": metadata,
        "granularity": [{"date": day, "impressions": 10, "taps": 1} for day in dates],
    }


def _run(
    endpoint: str,
    session: _FakeSession,
    manager: _FakeResumableManager,
    **kwargs: Any,
) -> list[list[dict[str, Any]]]:
    with mock.patch(SESSION_PATCH, return_value=session):
        return list(
            get_rows(
                credentials=CREDENTIALS,
                endpoint=endpoint,
                api_version=API_VERSION,
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

    def test_requests_carry_the_bearer_token_and_org_context(self) -> None:
        session = _FakeSession([_entity_page([{"id": 1}])])
        manager = _FakeResumableManager()

        _run("campaigns", session, manager)

        assert len(session.token_calls) == 1
        token_body = session.token_calls[0]["data"]
        assert token_body["grant_type"] == "client_credentials"
        assert token_body["client_id"] == CREDENTIALS.client_id
        assert token_body["scope"] == "searchadsorg"

        headers = session.api_calls[0]["headers"]
        assert headers["Authorization"] == "Bearer access-token"
        assert headers["X-AP-Context"] == "orgId=555"

    def test_acls_is_a_single_page_without_org_context(self) -> None:
        session = _FakeSession([_entity_page([{"orgId": 555}])])
        manager = _FakeResumableManager()

        batches = _run("acls", session, manager)

        assert batches == [[{"orgId": 555}]]
        assert len(session.api_calls) == 1
        assert session.api_calls[0]["url"] == f"{BASE_URL}/acls"
        assert "X-AP-Context" not in session.api_calls[0]["headers"]

    def test_find_endpoints_page_in_the_request_body(self) -> None:
        session = _FakeSession([_entity_page([{"id": 7}])])
        manager = _FakeResumableManager()

        _run("ad_groups", session, manager)

        call = session.api_calls[0]
        assert call["method"] == "POST"
        assert call["url"] == f"{BASE_URL}/adgroups/find"
        assert call["json"]["pagination"] == {"offset": 0, "limit": PAGE_SIZE}

    def test_expired_access_token_is_reminted_once_and_the_request_replayed(self) -> None:
        session = _FakeSession(
            [_FakeResponse(401, url=BASE_URL), _entity_page([{"id": 1}])],
            token_responses=[_token_response("first"), _token_response("second")],
        )
        manager = _FakeResumableManager()

        batches = _run("campaigns", session, manager)

        assert batches == [[{"id": 1}]]
        assert len(session.token_calls) == 2
        assert session.api_calls[0]["headers"]["Authorization"] == "Bearer first"
        assert session.api_calls[1]["headers"]["Authorization"] == "Bearer second"

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("server_error", 500)])
    def test_a_persistent_error_status_raises(self, _name: str, status: int) -> None:
        # Two identical failures so the single 401 re-mint retry is exhausted too.
        session = _FakeSession([_FakeResponse(status, url=BASE_URL), _FakeResponse(status, url=BASE_URL)])
        manager = _FakeResumableManager()

        with pytest.raises(HTTPError):
            _run("campaigns", session, manager)

    def test_entity_pagination_advances_the_offset_and_checkpoints_between_pages(self) -> None:
        first_page = [{"id": index} for index in range(PAGE_SIZE)]
        session = _FakeSession([_entity_page(first_page), _entity_page([{"id": PAGE_SIZE}])])
        manager = _FakeResumableManager()

        batches = _run("campaigns", session, manager)

        assert [len(batch) for batch in batches] == [PAGE_SIZE, 1]
        assert [call["params"]["offset"] for call in session.api_calls] == [0, PAGE_SIZE]
        assert [state.offset for state in manager.saved_states] == [PAGE_SIZE]
        assert manager.cleared is True

    def test_entity_pagination_resumes_from_the_saved_offset(self) -> None:
        session = _FakeSession([_entity_page([{"id": 1}])])
        manager = _FakeResumableManager(AppleSearchAdsResumeConfig(offset=2000))

        _run("campaigns", session, manager)

        assert session.api_calls[0]["params"]["offset"] == 2000

    def test_empty_first_page_yields_nothing_and_terminates(self) -> None:
        session = _FakeSession([_entity_page([])])
        manager = _FakeResumableManager()

        assert _run("keywords", session, manager) == []
        assert len(session.api_calls) == 1


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
            ("watermark_wins", True, date(2026, 5, 1), "2020-01-01", date(2026, 5, 1)),
            ("iso_string_watermark", True, "2026-05-01", None, date(2026, 5, 1)),
            ("datetime_watermark", True, datetime(2026, 5, 1, 6, 30), None, date(2026, 5, 1)),
            ("configured_start_date", False, None, "2026-02-03", date(2026, 2, 3)),
            ("unparseable_start_date_falls_back", False, None, "not-a-date", None),
            ("no_watermark_no_start_date", False, None, None, None),
            ("incremental_without_watermark", True, None, None, None),
            # An implausibly old configured start is floored so it can't fan out over thousands
            # of empty windows.
            ("ancient_start_date_is_floored", False, None, "0001-01-01", None),
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
        resolved = _report_start_date(should_use_incremental_field, watermark, start_date, today)

        if _name == "ancient_start_date_is_floored":
            assert resolved == today - timedelta(days=MAX_INITIAL_LOOKBACK_DAYS)
        else:
            assert resolved == (expected or today - timedelta(days=DEFAULT_INITIAL_LOOKBACK_DAYS))

    def test_max_initial_lookback_stays_within_apples_daily_report_limit(self) -> None:
        # Apple's Reporting API rejects a DAILY-granularity report whose startTime is more than
        # 24 months in the past with a 400 — this guards against re-widening the floor past it.
        assert MAX_INITIAL_LOOKBACK_DAYS <= 24 * 30


class TestFlattenReportRows:
    def test_granularity_buckets_become_one_row_per_day(self) -> None:
        payload = _report_payload([_report_row({"campaignId": 1, "campaignName": "A"}, ["2026-01-01", "2026-01-02"])])

        rows = flatten_report_rows(payload, None)

        assert rows == [
            {"campaignId": 1, "campaignName": "A", "date": "2026-01-01", "impressions": 10, "taps": 1},
            {"campaignId": 1, "campaignName": "A", "date": "2026-01-02", "impressions": 10, "taps": 1},
        ]

    def test_fan_out_injects_the_campaign_id_the_primary_key_needs(self) -> None:
        payload = _report_payload([_report_row({"adGroupId": 9}, ["2026-01-01"])])

        rows = flatten_report_rows(payload, 42)

        assert rows[0]["campaignId"] == 42
        assert rows[0]["adGroupId"] == 9

    def test_fan_out_does_not_clobber_a_campaign_id_apple_supplied(self) -> None:
        payload = _report_payload([_report_row({"campaignId": 7, "adGroupId": 9}, ["2026-01-01"])])

        assert flatten_report_rows(payload, 42)[0]["campaignId"] == 7

    @parameterized.expand(
        [
            ("no_granularity", {"data": {"reportingDataResponse": {"row": [{"metadata": {"campaignId": 1}}]}}}),
            ("empty_row_list", {"data": {"reportingDataResponse": {"row": []}}}),
            ("null_reporting_data", {"data": None}),
            ("missing_data_key", {}),
        ]
    )
    def test_pages_without_daily_metrics_flatten_to_nothing(self, _name: str, payload: dict[str, Any]) -> None:
        assert flatten_report_rows(payload, None) == []


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
        assert bodies[0]["granularity"] == "DAILY"
        assert bodies[0]["selector"]["pagination"] == {"offset": 0, "limit": PAGE_SIZE}
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
            f"{BASE_URL}/reports/campaigns/10/adgroups",
            f"{BASE_URL}/reports/campaigns/20/adgroups",
        ]
        assert [row["campaignId"] for batch in batches for row in batch] == [10, 20]
        assert manager.saved_states[0] == AppleSearchAdsResumeConfig(
            offset=0, window_start="2026-01-01", campaign_id=20
        )

    def test_fan_out_reports_resume_at_the_checkpointed_campaign(self) -> None:
        session = _FakeSession(
            [
                _entity_page([{"id": 10}, {"id": 20}]),
                _report_page([_report_row({"adGroupId": 2}, ["2026-01-01"])]),
            ]
        )
        manager = _FakeResumableManager(AppleSearchAdsResumeConfig(offset=0, window_start="2026-01-01", campaign_id=20))

        with mock.patch(TODAY_PATCH, return_value=date(2026, 1, 3)):
            _run(
                "ad_group_report",
                session,
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=date(2026, 1, 1),
            )

        report_calls = [call for call in session.api_calls if "/reports/" in call["url"]]
        assert [call["url"] for call in report_calls] == [f"{BASE_URL}/reports/campaigns/20/adgroups"]

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

    def test_report_pagination_continues_while_a_page_is_full(self) -> None:
        full_page = _report_page([_report_row({"campaignId": index}, ["2026-01-01"]) for index in range(PAGE_SIZE)])
        session = _FakeSession([full_page, _report_page([_report_row({"campaignId": 9999}, ["2026-01-01"])])])
        manager = _FakeResumableManager()

        with mock.patch(TODAY_PATCH, return_value=date(2026, 1, 2)):
            _run(
                "campaign_report",
                session,
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=date(2026, 1, 1),
            )

        offsets = [call["json"]["selector"]["pagination"]["offset"] for call in session.api_calls]
        assert offsets == [0, PAGE_SIZE]
        assert manager.saved_states[0] == AppleSearchAdsResumeConfig(
            offset=PAGE_SIZE, window_start="2026-01-01", campaign_id=None
        )


class TestSourceResponse:
    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_response_matches_the_endpoint_catalog(self, endpoint: str) -> None:
        config = APPLE_SEARCH_ADS_ENDPOINTS[endpoint]

        response = apple_search_ads_source(
            credentials=CREDENTIALS,
            endpoint=endpoint,
            api_version=API_VERSION,
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

    def test_items_are_lazy(self) -> None:
        response = apple_search_ads_source(
            credentials=CREDENTIALS,
            endpoint="campaigns",
            api_version=API_VERSION,
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
        session = _FakeSession([_FakeResponse(status, url=BASE_URL), _FakeResponse(status, url=BASE_URL)])

        with mock.patch(SESSION_PATCH, return_value=session):
            is_valid, message = validate_credentials(CREDENTIALS, API_VERSION, schema_name)

        assert is_valid is expected
        assert (message is None) is expected

    def test_probe_targets_an_org_scoped_endpoint(self) -> None:
        session = _FakeSession([_FakeResponse(200, {"data": []}, url=BASE_URL)])

        with mock.patch(SESSION_PATCH, return_value=session):
            assert validate_credentials(CREDENTIALS, API_VERSION) == (True, None)

        assert session.api_calls[0]["url"] == f"{BASE_URL}/campaigns"
        assert session.api_calls[0]["headers"]["X-AP-Context"] == "orgId=555"

    def test_an_unusable_private_key_fails_before_any_request(self) -> None:
        session = _FakeSession([])

        with mock.patch(SESSION_PATCH, return_value=session):
            is_valid, message = validate_credentials(_with_key("nope"), API_VERSION)

        assert is_valid is False
        assert message is not None and "private key" in message
        assert session.calls == []

    def test_a_token_endpoint_rejection_is_reported(self) -> None:
        session = _FakeSession([], token_responses=[_FakeResponse(400, url=APPLE_OAUTH_TOKEN_URL)])

        with mock.patch(SESSION_PATCH, return_value=session):
            is_valid, message = validate_credentials(CREDENTIALS, API_VERSION)

        assert is_valid is False
        assert message is not None

    def test_a_token_response_without_an_access_token_is_reported(self) -> None:
        session = _FakeSession([], token_responses=[_FakeResponse(200, {}, url=APPLE_OAUTH_TOKEN_URL)])

        with mock.patch(SESSION_PATCH, return_value=session):
            is_valid, message = validate_credentials(CREDENTIALS, API_VERSION)

        assert is_valid is False
        assert message == "Apple's token response did not contain an access token"


class TestClientBaseUrl:
    @parameterized.expand([("v5", "v5"), ("pinned_older", "v4")])
    def test_base_url_follows_the_resolved_api_version(self, _name: str, api_version: str) -> None:
        with mock.patch(SESSION_PATCH, return_value=_FakeSession([])):
            client = AppleSearchAdsClient(CREDENTIALS, api_version)

        assert client.base_url == f"{APPLE_SEARCH_ADS_HOST}/api/{api_version}"
