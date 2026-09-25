import datetime as dt

import pytest
from unittest import mock

import requests
from google.auth.exceptions import RefreshError, TransportError

from posthog.models.integration import Integration

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googleadsense import (
    GoogleAdSenseSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_adsense import google_adsense as ads
from products.warehouse_sources.backend.temporal.data_imports.sources.google_adsense.google_adsense import (
    DEFAULT_HISTORY_DAYS,
    FRESHNESS_LAG_DAYS,
    QUOTA_MAX_RETRIES,
    GoogleAdSenseQuotaExceededError,
    GoogleAdSenseResumeConfig,
    _credentials,
    _entity_rows,
    _fetch_reports_window,
    _get_paginated,
    _initial_start_date,
    _is_daily_quota_error,
    _is_quota_error,
    _is_server_error,
    _is_transient_refresh_error,
    _query_reports,
    _query_reports_params,
    _quota_backoff_seconds,
    _report_row_to_dict,
    _resolve_window,
    _throttle as _throttle_impl,
    get_account,
    google_adsense_session,
    google_adsense_source,
    list_accounts,
    list_alerts,
    list_sites,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_adsense.settings import REPORTS_SCHEMAS

TODAY = dt.date(2026, 4, 30)


@pytest.fixture(autouse=True)
def _no_throttle(monkeypatch):
    # The project-wide throttle spaces real HTTP calls; unit tests must never sleep on it.
    # The limiter test below calls `_throttle_impl` (a direct reference), which this patch
    # of the module attribute does not shadow.
    monkeypatch.setattr(ads, "_throttle", lambda: None)


def _config(**overrides) -> GoogleAdSenseSourceConfig:
    defaults = {
        "google_adsense_integration_id": 1,
        "account": "accounts/pub-1234567890",
        "start_date": None,
    }
    defaults.update(overrides)
    return GoogleAdSenseSourceConfig(**defaults)


def _resume_manager(*, state: GoogleAdSenseResumeConfig | None = None, can_resume: bool = False) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = state
    return manager


@pytest.fixture(autouse=True)
def _clear_django_cache():
    """The tz lookup is cached in Django's cache, which outlives a single test in the same
    process. Clear it around every test so a value cached by one test can't be served to
    another, and so the cache-miss path is always the one under test.
    """
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


def _fake_response(status_code: int, json_body: dict | None = None, headers: dict | None = None):
    resp = mock.MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.headers = headers or {}
    resp.text = "" if json_body is None else str(json_body)
    resp.json.return_value = json_body if json_body is not None else {}

    def raise_for_status():
        if not resp.ok:
            raise requests.HTTPError(f"{status_code} Client Error: Forbidden for url: https://example", response=resp)

    resp.raise_for_status.side_effect = raise_for_status
    return resp


def _capture_query(monkeypatch, captured: dict) -> None:
    """Stub `_query_reports`, recording the kwargs it was called with."""

    def fake_query_reports(**kwargs):
        captured.update(kwargs)
        return {"headers": [], "rows": []}

    monkeypatch.setattr(ads, "_query_reports", fake_query_reports)


# ---------------------------------------------------------------------------
# Sync window resolution
# ---------------------------------------------------------------------------


def test_initial_start_date_defaults_to_two_years():
    start = _initial_start_date(TODAY, start_date=None)
    assert (TODAY - start).days == DEFAULT_HISTORY_DAYS


def test_initial_start_date_honors_config_override():
    override = dt.date(2025, 1, 1)
    assert _initial_start_date(TODAY, start_date=override) == override


@pytest.mark.parametrize(
    "last_value,expected_start",
    [
        # No watermark -> full 2-year history window.
        (None, _initial_start_date(TODAY, None)),
        # A watermark older than the history floor is still clamped to the floor.
        (TODAY - dt.timedelta(days=10_000), _initial_start_date(TODAY, None)),
        # A recent watermark is the start itself: the pipeline already shifted it back by
        # the schema's incremental lookback, so _resolve_window must use it as-is.
        (TODAY - dt.timedelta(days=10), TODAY - dt.timedelta(days=10)),
        # ISO string is accepted and parsed.
        ("2026-04-15", dt.date(2026, 4, 15)),
        # Datetime is accepted and truncated to its date.
        (dt.datetime(2026, 4, 15, 12, 0, 0), dt.date(2026, 4, 15)),
    ],
)
def test_resolve_window_start(last_value, expected_start):
    start, end = _resolve_window(TODAY, last_value)
    assert start == expected_start
    assert end == TODAY - dt.timedelta(days=FRESHNESS_LAG_DAYS)


def test_resolve_window_end_is_yesterday_by_default():
    # ESTIMATED_EARNINGS is final "through yesterday"; today's row is still an estimate.
    _, end = _resolve_window(TODAY, None)
    assert end == TODAY - dt.timedelta(days=1)


def test_resolve_window_does_not_apply_a_lookback():
    # The pipeline hands us db_incremental_field_last_value already shifted back by the
    # schema's incremental lookback, so subtracting one here would double the trailing
    # window. The cursor must come back untouched.
    cursor = dt.date(2026, 4, 20)
    start, _ = _resolve_window(TODAY, cursor)
    assert start == cursor


def test_resolve_window_never_starts_before_configured_start_date():
    configured_start = dt.date(2026, 4, 20)
    # A cursor earlier than the configured start must not pull the window before it.
    start, _ = _resolve_window(TODAY, dt.date(2026, 4, 10), start_date=configured_start)
    assert start == configured_start


def test_resolve_window_accepts_string_config_values():
    # The generated config delivers start_date as a string, not a date.
    start, end = _resolve_window(TODAY, None, start_date="2026-04-29")
    assert start == dt.date(2026, 4, 29)
    assert end == TODAY - dt.timedelta(days=FRESHNESS_LAG_DAYS)
    assert isinstance(start, dt.date)


def test_reports_source_handles_string_config_values(monkeypatch):
    # End-to-end: exactly what the generated config produces in production.
    monkeypatch.setattr(ads, "_today", lambda *_a, **_kw: TODAY)
    monkeypatch.setattr(ads, "google_adsense_session", lambda *a, **kw: mock.MagicMock())

    captured: dict = {}
    _capture_query(monkeypatch, captured)

    response = google_adsense_source(
        config=_config(start_date="2026-04-01"),
        resource_name="daily_stats",
        team_id=1,
        resumable_source_manager=_resume_manager(),
        should_use_incremental_field=True,
        db_incremental_field_last_value=dt.date(2026, 4, 20),
    )
    list(response.items())

    assert captured["start_date"] == dt.date(2026, 4, 20)


# ---------------------------------------------------------------------------
# Request params
# ---------------------------------------------------------------------------


def test_query_reports_params_decomposes_structured_dates():
    params = _query_reports_params(
        start_date=dt.date(2026, 4, 1),
        end_date=dt.date(2026, 4, 30),
        dimensions=["DATE", "AD_UNIT_ID"],
        metrics=["CLICKS", "IMPRESSIONS"],
    )
    assert ("startDate.year", "2026") in params
    assert ("startDate.month", "4") in params
    assert ("startDate.day", "1") in params
    assert ("endDate.year", "2026") in params
    assert ("endDate.month", "4") in params
    assert ("endDate.day", "30") in params
    assert ("dimensions", "DATE") in params
    assert ("dimensions", "AD_UNIT_ID") in params
    assert ("metrics", "CLICKS") in params
    assert ("metrics", "IMPRESSIONS") in params
    assert ("orderBy", "+DATE") in params


def test_query_reports_params_omits_reporting_time_zone_when_unset():
    params = _query_reports_params(
        start_date=dt.date(2026, 4, 1),
        end_date=dt.date(2026, 4, 1),
        dimensions=["DATE"],
        metrics=["CLICKS"],
    )
    assert all(key != "reportingTimeZone" for key, _ in params)


def test_query_reports_params_includes_reporting_time_zone_when_set():
    params = _query_reports_params(
        start_date=dt.date(2026, 4, 1),
        end_date=dt.date(2026, 4, 1),
        dimensions=["DATE"],
        metrics=["WEBSEARCH_RESULT_PAGES"],
        reporting_time_zone="GOOGLE_TIME_ZONE",
    )
    assert ("reportingTimeZone", "GOOGLE_TIME_ZONE") in params


# ---------------------------------------------------------------------------
# Row casting (header normalization)
# ---------------------------------------------------------------------------


_HEADERS = [
    {"name": "DATE", "type": "DIMENSION"},
    {"name": "CLICKS", "type": "METRIC_TALLY"},
    {"name": "IMPRESSIONS_CTR", "type": "METRIC_RATIO"},
    {"name": "ACTIVE_VIEW_TIME", "type": "METRIC_MILLISECONDS"},
    {"name": "ESTIMATED_EARNINGS", "type": "METRIC_CURRENCY", "currencyCode": "USD"},
]


def test_report_row_to_dict_casts_by_header_type():
    row = {
        "cells": [
            {"value": "2026-04-15"},
            {"value": "12"},
            {"value": "0.034"},
            {"value": "2500"},
            {"value": "45.20"},
        ]
    }
    out = _report_row_to_dict(row, _HEADERS, account_name="accounts/pub-1234567890")

    assert out["date"] == "2026-04-15"
    assert out["clicks"] == 12 and isinstance(out["clicks"], int)
    assert out["impressions_ctr"] == pytest.approx(0.034) and isinstance(out["impressions_ctr"], float)
    assert out["active_view_time"] == 2500 and isinstance(out["active_view_time"], int)
    assert out["estimated_earnings"] == pytest.approx(45.20) and isinstance(out["estimated_earnings"], float)


def test_report_row_to_dict_adds_shared_currency_code_column():
    row = {"cells": [{"value": "2026-04-15"}, {"value": "1"}, {"value": "0.1"}, {"value": "0"}, {"value": "5.00"}]}
    out = _report_row_to_dict(row, _HEADERS, account_name="accounts/pub-1234567890")

    assert out["currency_code"] == "USD"
    # One shared column, not per-metric siblings (estimated_earnings_currency_code, ...).
    assert not any(key.endswith("_currency_code") for key in out)


def test_report_row_to_dict_keeps_two_currency_metrics_to_one_column():
    headers = [
        {"name": "ESTIMATED_EARNINGS", "type": "METRIC_CURRENCY", "currencyCode": "EUR"},
        {"name": "COST_PER_CLICK", "type": "METRIC_CURRENCY", "currencyCode": "EUR"},
    ]
    out = _report_row_to_dict({"cells": [{"value": "1.5"}, {"value": "0.4"}]}, headers, account_name="accounts/pub-1")

    assert out["currency_code"] == "EUR"
    assert "estimated_earnings_currency_code" not in out
    assert "cost_per_click_currency_code" not in out


def test_report_row_to_dict_omits_currency_code_without_currency_metrics():
    headers = [{"name": "DATE", "type": "DIMENSION"}]
    out = _report_row_to_dict({"cells": [{"value": "2026-04-15"}]}, headers, account_name="accounts/pub-1")
    assert "currency_code" not in out


def test_report_row_to_dict_adds_account_column():
    row = {"cells": [{"value": "2026-04-15"}, {"value": "1"}, {"value": "0.1"}, {"value": "0"}, {"value": "5.00"}]}
    out = _report_row_to_dict(row, _HEADERS, account_name="accounts/pub-1234567890")
    assert out["account"] == "accounts/pub-1234567890"


def test_report_row_to_dict_handles_null_cell_value():
    headers = [{"name": "CLICKS", "type": "METRIC_TALLY"}]
    row = {"cells": [{"value": None}]}
    out = _report_row_to_dict(row, headers, account_name="accounts/pub-1")
    assert out["clicks"] is None


def test_report_row_to_dict_pads_short_row_with_none():
    # The API can omit trailing cells; a shorter cells[] must not drop the later columns.
    headers = [
        {"name": "DATE", "type": "DIMENSION"},
        {"name": "CLICKS", "type": "METRIC_TALLY"},
        {"name": "IMPRESSIONS", "type": "METRIC_TALLY"},
    ]
    row = {"cells": [{"value": "2026-04-15"}, {"value": "3"}]}
    out = _report_row_to_dict(row, headers, account_name="accounts/pub-1")
    assert out["date"] == "2026-04-15"
    assert out["clicks"] == 3
    assert out["impressions"] is None


# ---------------------------------------------------------------------------
# Quota / error classification
# ---------------------------------------------------------------------------


def _error_info(reason: str) -> dict:
    """gRPC-transcoded shape: error.details[] holding a google.rpc.ErrorInfo entry."""
    return {
        "error": {
            "code": 403,
            "details": [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": reason}],
        }
    }


def _legacy_error(reason: str) -> dict:
    """Legacy shape: error.errors[] carrying a lowerCamelCase reason."""
    return {"error": {"code": 403, "errors": [{"reason": reason}]}}


_QUOTA_BODY = _error_info("quotaExceeded")
_RATE_LIMIT_BODY = _error_info("rateLimitExceeded")
_RATE_LIMIT_UPPER_BODY = _error_info("RATE_LIMIT_EXCEEDED")
_LEGACY_RATE_LIMIT_BODY = _legacy_error("rateLimitExceeded")
_PERMISSION_BODY = _error_info("forbidden")
_SERVICE_DISABLED_BODY = _error_info("SERVICE_DISABLED")
_DAILY_QUOTA_BODY = _error_info("dailyLimitExceeded")
_DAILY_QUOTA_UPPER_BODY = _error_info("DAILY_LIMIT_EXCEEDED")
_ROW_QUOTA_429_BODY = {"error": {"code": 429, "message": "Report row quota exceeded"}}


@pytest.mark.parametrize(
    "response,expected",
    [
        (_fake_response(200, {"rows": []}), False),
        # 429 is the report-row quota / request-rate signal.
        (_fake_response(429), True),
        # ErrorInfo shape, both casings.
        (_fake_response(403, _QUOTA_BODY), True),
        (_fake_response(403, _RATE_LIMIT_BODY), True),
        (_fake_response(403, _RATE_LIMIT_UPPER_BODY), True),
        # Legacy error.errors[] shape.
        (_fake_response(403, _LEGACY_RATE_LIMIT_BODY), True),
        # Non-quota 403s.
        (_fake_response(403, _PERMISSION_BODY), False),
        (_fake_response(403, _SERVICE_DISABLED_BODY), False),
        (_fake_response(403, {}), False),
        (_fake_response(403, {"error": None}), False),
        (_fake_response(401), False),
    ],
)
def test_is_quota_error(response, expected):
    assert _is_quota_error(response) is expected


@pytest.mark.parametrize(
    "response,expected",
    [
        (_fake_response(403, _DAILY_QUOTA_BODY), True),
        (_fake_response(403, _DAILY_QUOTA_UPPER_BODY), True),
        (_fake_response(403, _QUOTA_BODY), False),
        (_fake_response(403, {"error": None}), False),
        (_fake_response(200, {"rows": []}), False),
        # The separate report-row quota is a genuine 429; it resets on its own, so it is
        # classified as a daily/retry-later error rather than burning the inline retry budget.
        (_fake_response(429, _ROW_QUOTA_429_BODY), True),
        (_fake_response(429), True),
    ],
)
def test_is_daily_quota_error(response, expected):
    assert _is_daily_quota_error(response) is expected


@pytest.mark.parametrize(
    "response,expected",
    [
        (_fake_response(500), True),
        (_fake_response(502), True),
        (_fake_response(503), True),
        (_fake_response(504), True),
        (_fake_response(429), False),
        (_fake_response(403, _QUOTA_BODY), False),
        (_fake_response(200, {"rows": []}), False),
    ],
)
def test_is_server_error(response, expected):
    assert _is_server_error(response) is expected


_HTML_502_BODY = (
    "<!DOCTYPE html>\n<html lang=en>\n  <title>Error 502 (Server Error)!!1</title>\n"
    "  <p><b>502.</b> That's an error.\n  <p>The server encountered a temporary error "
    "and could not complete your request."
)


@pytest.mark.parametrize(
    "error,expected",
    [
        (RefreshError(_HTML_502_BODY), True),
        (RefreshError("temporarily_unavailable: try again later", retryable=True), True),
        (RefreshError("invalid_grant: Token has been expired or revoked."), False),
        (RefreshError("invalid_scope: Bad Request"), False),
    ],
)
def test_is_transient_refresh_error(error, expected):
    assert _is_transient_refresh_error(error) is expected


def test_quota_backoff_prefers_retry_after_header():
    resp = _fake_response(403, _QUOTA_BODY, headers={"Retry-After": "30"})
    assert _quota_backoff_seconds(resp, attempt=0) == 30.0


def test_quota_backoff_falls_back_to_exponential():
    resp = _fake_response(403, _QUOTA_BODY)
    assert _quota_backoff_seconds(resp, attempt=0) == 2.0
    assert _quota_backoff_seconds(resp, attempt=2) == 8.0


# ---------------------------------------------------------------------------
# Pagination (entity list endpoints)
# ---------------------------------------------------------------------------


def test_list_accounts_follows_next_page_token():
    session = mock.MagicMock()
    session.get.side_effect = [
        _fake_response(200, {"accounts": [{"name": "accounts/pub-1"}], "nextPageToken": "page-2"}),
        _fake_response(200, {"accounts": [{"name": "accounts/pub-2"}]}),
    ]

    accounts = list_accounts(session)

    assert accounts == [{"name": "accounts/pub-1"}, {"name": "accounts/pub-2"}]
    assert session.get.call_count == 2
    assert "pageToken" not in session.get.call_args_list[0].kwargs["params"]
    assert session.get.call_args_list[1].kwargs["params"]["pageToken"] == "page-2"


def test_list_accounts_single_page_when_no_token():
    session = mock.MagicMock()
    session.get.return_value = _fake_response(200, {"accounts": [{"name": "accounts/pub-1"}]})

    assert list_accounts(session) == [{"name": "accounts/pub-1"}]
    assert session.get.call_count == 1


def test_get_paginated_accumulates_all_pages():
    session = mock.MagicMock()
    session.get.side_effect = [
        _fake_response(200, {"sites": [{"name": "s1"}], "nextPageToken": "t1"}),
        _fake_response(200, {"sites": [{"name": "s2"}], "nextPageToken": "t2"}),
        _fake_response(200, {"sites": [{"name": "s3"}]}),
    ]

    assert _get_paginated(session, "https://example/sites", "sites") == [
        {"name": "s1"},
        {"name": "s2"},
        {"name": "s3"},
    ]
    assert session.get.call_count == 3


def test_list_sites_paginates_across_pages():
    session = mock.MagicMock()
    session.get.side_effect = [
        _fake_response(200, {"sites": [{"name": "sites/1"}], "nextPageToken": "t1"}),
        _fake_response(200, {"sites": [{"name": "sites/2"}]}),
    ]

    assert list_sites(session, "accounts/pub-1") == [{"name": "sites/1"}, {"name": "sites/2"}]
    assert session.get.call_count == 2


def test_list_alerts_does_not_paginate():
    # accounts.alerts is the one list endpoint with no pageToken per the API docs;
    # a stray token must be ignored rather than triggering a second request.
    session = mock.MagicMock()
    session.get.return_value = _fake_response(200, {"alerts": [{"name": "a1"}], "nextPageToken": "ignored"})

    assert list_alerts(session, "accounts/pub-1") == [{"name": "a1"}]
    assert session.get.call_count == 1


def test_entity_list_quota_error_is_retryable_not_an_auth_failure():
    # Entity endpoints share the project quota with reports: a rate-limit 403 must surface as
    # a retryable quota error, not a raw HTTPError that get_non_retryable_errors reads as
    # "not authorized to read this AdSense account".
    session = mock.MagicMock()
    session.get.return_value = _fake_response(403, _RATE_LIMIT_BODY)

    with pytest.raises(GoogleAdSenseQuotaExceededError, match="retryable"):
        list_sites(session, "accounts/pub-1")


def test_get_account_quota_error_is_retryable():
    session = mock.MagicMock()
    session.get.return_value = _fake_response(429)

    with pytest.raises(GoogleAdSenseQuotaExceededError, match="retryable"):
        get_account(session, "accounts/pub-1")


# ---------------------------------------------------------------------------
# Credentials & session (credential messages)
# ---------------------------------------------------------------------------


def test_credentials_builds_refresh_token_grant_without_scopes(monkeypatch):
    integration = mock.MagicMock()
    integration.refresh_token = "refresh-abc"
    monkeypatch.setattr(ads, "_get_integration", lambda integration_id, team_id: integration)
    monkeypatch.setattr(
        ads.integration_secrets,
        "get_secrets",
        lambda keys: {
            "GOOGLE_ADSENSE_APP_CLIENT_ID": "client-id",
            "GOOGLE_ADSENSE_APP_CLIENT_SECRET": "client-secret",
        },
    )

    creds = _credentials(integration_id=1, team_id=2)

    assert creds.refresh_token == "refresh-abc"
    assert creds.client_id == "client-id"
    assert creds.client_secret == "client-secret"
    assert creds.token_uri == "https://oauth2.googleapis.com/token"
    assert creds.token is None
    # No scopes are forwarded on purpose: a refresh-token grant must not re-request
    # scopes, so a genuinely missing scope surfaces as a 403 on the accounts call
    # (mapped to an actionable "reconnect" message) instead of a masked
    # invalid_scope token-refresh failure that fails every sync.
    assert creds.scopes is None


def test_credentials_propagates_missing_integration(monkeypatch):
    def _raise(*_args, **_kwargs):
        raise Integration.DoesNotExist

    monkeypatch.setattr(ads, "_get_integration", _raise)

    with pytest.raises(Integration.DoesNotExist):
        _credentials(integration_id=1, team_id=2)


def test_google_adsense_session_mounts_tracked_adapter(monkeypatch):
    creds = mock.MagicMock()
    monkeypatch.setattr(ads, "_credentials", lambda integration_id, team_id: creds)
    session = mock.MagicMock()
    monkeypatch.setattr(ads, "AuthorizedSession", lambda c: session)
    adapter = mock.MagicMock()
    monkeypatch.setattr(ads, "make_tracked_adapter", lambda: adapter)

    result = google_adsense_session(integration_id=1, team_id=2)

    assert result is session
    assert [call.args for call in session.mount.call_args_list] == [("https://", adapter), ("http://", adapter)]


# ---------------------------------------------------------------------------
# Account picker
# ---------------------------------------------------------------------------


def test_list_accounts_returns_accounts_for_picker():
    session = mock.MagicMock()
    session.get.return_value = _fake_response(
        200, {"accounts": [{"name": "accounts/pub-1"}, {"name": "accounts/pub-2"}]}
    )
    assert list_accounts(session) == [{"name": "accounts/pub-1"}, {"name": "accounts/pub-2"}]


def test_list_accounts_returns_empty_when_picker_has_none():
    session = mock.MagicMock()
    session.get.return_value = _fake_response(200, {})
    assert list_accounts(session) == []


def test_list_accounts_propagates_permission_error_for_reconnect_mapping():
    # The accounts call is where a missing/mismatched OAuth scope shows up; the
    # HTTPError must bubble so the caller can map it to a "reconnect" message.
    session = mock.MagicMock()
    session.get.return_value = _fake_response(403, _PERMISSION_BODY)

    with pytest.raises(requests.HTTPError, match="403 Client Error"):
        list_accounts(session)


def test_get_account_returns_single_account():
    session = mock.MagicMock()
    session.get.return_value = _fake_response(200, {"name": "accounts/pub-1", "displayName": "My site"})
    assert get_account(session, "accounts/pub-1") == {"name": "accounts/pub-1", "displayName": "My site"}


def test_get_account_propagates_permission_error():
    session = mock.MagicMock()
    session.get.return_value = _fake_response(403, _PERMISSION_BODY)

    with pytest.raises(requests.HTTPError, match="403 Client Error"):
        get_account(session, "accounts/pub-1")


# ---------------------------------------------------------------------------
# Account time zone (window end is the account's "yesterday")
# ---------------------------------------------------------------------------


def test_account_time_zone_reads_nested_id():
    # accounts.get returns {"timeZone": {"id": "Africa/Lagos"}} — an object, not a string.
    session = mock.MagicMock()
    session.get.return_value = _fake_response(200, {"timeZone": {"id": "Africa/Lagos"}})

    assert ads._account_time_zone(session, "accounts/pub-1").key == "Africa/Lagos"


def test_account_time_zone_falls_back_to_utc_when_missing():
    session = mock.MagicMock()
    session.get.return_value = _fake_response(200, {"name": "accounts/pub-1"})

    assert ads._account_time_zone(session, "accounts/pub-1").key == "UTC"


def test_account_time_zone_falls_back_to_utc_on_unknown_id():
    session = mock.MagicMock()
    session.get.return_value = _fake_response(200, {"timeZone": {"id": "Not/AZone"}})

    assert ads._account_time_zone(session, "accounts/pub-1").key == "UTC"


def test_today_is_resolved_in_the_account_time_zone(monkeypatch):
    from zoneinfo import ZoneInfo

    # UTC+14: 2026-01-01T12:00Z is already 2026-01-02 for this account.
    monkeypatch.setattr(ads, "_account_time_zone", lambda session, account: ZoneInfo("Pacific/Kiritimati"))

    class _FrozenDatetime(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            instant = dt.datetime(2026, 1, 1, 12, 0, tzinfo=dt.UTC)
            return instant.astimezone(tz) if tz else instant

    monkeypatch.setattr(ads.dt, "datetime", _FrozenDatetime)

    # _today(team_id, integration_id, session, account_name) — the ids key the tz cache.
    assert ads._today(1, 1, mock.MagicMock(), "accounts/pub-1") == dt.date(2026, 1, 2)


# ---------------------------------------------------------------------------
# _fetch_reports_window: retry/backoff behavior
# ---------------------------------------------------------------------------


def test_fetch_window_retries_quota_then_succeeds(monkeypatch):
    monkeypatch.setattr(ads.time, "sleep", lambda _s: None)

    session = mock.MagicMock()
    session.get.side_effect = [
        _fake_response(403, _QUOTA_BODY),
        _fake_response(403, _QUOTA_BODY),
        _fake_response(200, {"headers": [], "rows": [{"cells": []}], "totalMatchedRows": "1"}),
    ]

    data = _fetch_reports_window(
        session, "accounts/pub-1", dt.date(2026, 4, 15), dt.date(2026, 4, 15), ["DATE"], ["CLICKS"]
    )
    assert data["rows"] == [{"cells": []}]
    assert session.get.call_count == 3


def test_fetch_window_raises_quota_error_after_max_retries(monkeypatch):
    monkeypatch.setattr(ads.time, "sleep", lambda _s: None)

    session = mock.MagicMock()
    session.get.return_value = _fake_response(403, _QUOTA_BODY)

    with pytest.raises(GoogleAdSenseQuotaExceededError):
        _fetch_reports_window(
            session, "accounts/pub-1", dt.date(2026, 4, 15), dt.date(2026, 4, 15), ["DATE"], ["CLICKS"]
        )

    assert session.get.call_count == QUOTA_MAX_RETRIES + 1


def test_fetch_window_daily_quota_raises_without_retry(monkeypatch):
    monkeypatch.setattr(ads.time, "sleep", lambda _s: None)

    session = mock.MagicMock()
    session.get.return_value = _fake_response(403, _DAILY_QUOTA_BODY)

    with pytest.raises(GoogleAdSenseQuotaExceededError):
        _fetch_reports_window(
            session, "accounts/pub-1", dt.date(2026, 4, 15), dt.date(2026, 4, 15), ["DATE"], ["CLICKS"]
        )

    assert session.get.call_count == 1


def test_fetch_window_row_quota_429_raises_without_retry(monkeypatch):
    # The report-row quota (429) is a daily condition: hand it to Temporal, don't spin inline.
    monkeypatch.setattr(ads.time, "sleep", lambda _s: None)

    session = mock.MagicMock()
    session.get.return_value = _fake_response(429, _ROW_QUOTA_429_BODY)

    with pytest.raises(GoogleAdSenseQuotaExceededError, match="daily quota"):
        _fetch_reports_window(
            session, "accounts/pub-1", dt.date(2026, 4, 15), dt.date(2026, 4, 15), ["DATE"], ["CLICKS"]
        )

    assert session.get.call_count == 1


def test_fetch_window_permission_error_is_not_retried(monkeypatch):
    monkeypatch.setattr(ads.time, "sleep", lambda _s: None)

    session = mock.MagicMock()
    session.get.return_value = _fake_response(403, _PERMISSION_BODY)

    with pytest.raises(requests.HTTPError, match="403 Client Error"):
        _fetch_reports_window(
            session, "accounts/pub-1", dt.date(2026, 4, 15), dt.date(2026, 4, 15), ["DATE"], ["CLICKS"]
        )

    assert session.get.call_count == 1


def test_fetch_window_retries_server_error_then_succeeds(monkeypatch):
    monkeypatch.setattr(ads.time, "sleep", lambda _s: None)

    session = mock.MagicMock()
    session.get.side_effect = [
        _fake_response(500),
        _fake_response(503),
        _fake_response(200, {"headers": [], "rows": [], "totalMatchedRows": "0"}),
    ]

    data = _fetch_reports_window(
        session, "accounts/pub-1", dt.date(2026, 4, 15), dt.date(2026, 4, 15), ["DATE"], ["CLICKS"]
    )
    assert data["rows"] == []
    assert session.get.call_count == 3


def test_fetch_window_server_error_bubbles_http_error_after_max_retries(monkeypatch):
    monkeypatch.setattr(ads.time, "sleep", lambda _s: None)

    session = mock.MagicMock()
    session.get.return_value = _fake_response(500)

    with pytest.raises(requests.HTTPError):
        _fetch_reports_window(
            session, "accounts/pub-1", dt.date(2026, 4, 15), dt.date(2026, 4, 15), ["DATE"], ["CLICKS"]
        )

    assert session.get.call_count == QUOTA_MAX_RETRIES + 1


def test_fetch_window_retries_connection_error_then_succeeds(monkeypatch):
    monkeypatch.setattr(ads.time, "sleep", lambda _s: None)

    session = mock.MagicMock()
    session.get.side_effect = [
        requests.ConnectionError("Connection aborted."),
        _fake_response(200, {"headers": [], "rows": [], "totalMatchedRows": "0"}),
    ]

    data = _fetch_reports_window(
        session, "accounts/pub-1", dt.date(2026, 4, 15), dt.date(2026, 4, 15), ["DATE"], ["CLICKS"]
    )
    assert data["rows"] == []
    assert session.get.call_count == 2


def test_fetch_window_connection_error_bubbles_after_max_retries(monkeypatch):
    monkeypatch.setattr(ads.time, "sleep", lambda _s: None)

    session = mock.MagicMock()
    session.get.side_effect = requests.ConnectionError("Connection aborted.")

    with pytest.raises(requests.ConnectionError):
        _fetch_reports_window(
            session, "accounts/pub-1", dt.date(2026, 4, 15), dt.date(2026, 4, 15), ["DATE"], ["CLICKS"]
        )

    assert session.get.call_count == QUOTA_MAX_RETRIES + 1


def test_fetch_window_retries_truncated_body_then_succeeds(monkeypatch):
    monkeypatch.setattr(ads.time, "sleep", lambda _s: None)

    truncated = _fake_response(200)
    truncated.json.side_effect = requests.exceptions.ChunkedEncodingError("Connection broken: IncompleteRead(...)")
    session = mock.MagicMock()
    session.get.side_effect = [truncated, _fake_response(200, {"headers": [], "rows": [], "totalMatchedRows": "0"})]

    data = _fetch_reports_window(
        session, "accounts/pub-1", dt.date(2026, 4, 15), dt.date(2026, 4, 15), ["DATE"], ["CLICKS"]
    )
    assert data["rows"] == []
    assert session.get.call_count == 2


def test_fetch_window_retries_transient_token_refresh_error_then_succeeds(monkeypatch):
    monkeypatch.setattr(ads.time, "sleep", lambda _s: None)

    session = mock.MagicMock()
    session.get.side_effect = [
        RefreshError(_HTML_502_BODY),
        _fake_response(200, {"headers": [], "rows": [], "totalMatchedRows": "0"}),
    ]

    data = _fetch_reports_window(
        session, "accounts/pub-1", dt.date(2026, 4, 15), dt.date(2026, 4, 15), ["DATE"], ["CLICKS"]
    )
    assert data["rows"] == []
    assert session.get.call_count == 2


def test_fetch_window_permanent_token_refresh_error_bubbles_without_retry(monkeypatch):
    monkeypatch.setattr(ads.time, "sleep", lambda _s: None)

    session = mock.MagicMock()
    session.get.side_effect = RefreshError("invalid_grant: Token has been expired or revoked.")

    with pytest.raises(RefreshError, match="invalid_grant"):
        _fetch_reports_window(
            session, "accounts/pub-1", dt.date(2026, 4, 15), dt.date(2026, 4, 15), ["DATE"], ["CLICKS"]
        )

    assert session.get.call_count == 1


def test_fetch_window_retries_token_refresh_transport_error_then_succeeds(monkeypatch):
    monkeypatch.setattr(ads.time, "sleep", lambda _s: None)

    session = mock.MagicMock()
    session.get.side_effect = [
        TransportError("Cannot connect to proxy."),
        _fake_response(200, {"headers": [], "rows": [], "totalMatchedRows": "0"}),
    ]

    data = _fetch_reports_window(
        session, "accounts/pub-1", dt.date(2026, 4, 15), dt.date(2026, 4, 15), ["DATE"], ["CLICKS"]
    )
    assert data["rows"] == []
    assert session.get.call_count == 2


def test_fetch_window_token_refresh_transport_error_bubbles_after_max_retries(monkeypatch):
    monkeypatch.setattr(ads.time, "sleep", lambda _s: None)

    session = mock.MagicMock()
    session.get.side_effect = TransportError("Cannot connect to proxy.")

    with pytest.raises(TransportError):
        _fetch_reports_window(
            session, "accounts/pub-1", dt.date(2026, 4, 15), dt.date(2026, 4, 15), ["DATE"], ["CLICKS"]
        )

    assert session.get.call_count == QUOTA_MAX_RETRIES + 1


# ---------------------------------------------------------------------------
# _query_reports: adaptive split-on-truncation
# ---------------------------------------------------------------------------


def test_query_reports_single_request_when_not_truncated(monkeypatch):
    monkeypatch.setattr(ads.time, "sleep", lambda _s: None)

    session = mock.MagicMock()
    session.get.return_value = _fake_response(
        200,
        {
            "headers": [{"name": "DATE", "type": "DIMENSION"}],
            "rows": [{"cells": [{"value": "2026-04-15"}]}],
            "totalMatchedRows": "1",
        },
    )

    # A single window fetch that isn't truncated costs exactly 1 request.
    data = _query_reports(
        session,
        "accounts/pub-1",
        dt.date(2024, 4, 30),
        dt.date(2026, 4, 29),
        ["DATE"],
        ["CLICKS"],
        table_name="daily_stats",
    )
    assert session.get.call_count == 1
    assert len(data["rows"]) == 1


def test_query_reports_splits_window_in_half_on_truncation(monkeypatch):
    monkeypatch.setattr(ads.time, "sleep", lambda _s: None)

    session = mock.MagicMock()

    def fake_get(url, params):
        start = next(v for k, v in params if k == "startDate.day")
        end = next(v for k, v in params if k == "endDate.day")
        if (start, end) == ("1", "10"):
            return _fake_response(200, {"headers": [], "rows": [{"cells": []}], "totalMatchedRows": "999999"})
        return _fake_response(200, {"headers": [], "rows": [{"cells": []}], "totalMatchedRows": "1"})

    session.get.side_effect = fake_get

    data = _query_reports(
        session,
        "accounts/pub-1",
        dt.date(2026, 4, 1),
        dt.date(2026, 4, 10),
        ["DATE"],
        ["CLICKS"],
        table_name="page_url_stats",
    )

    # 1 (truncated whole window) + 2 (both halves) = 3 requests, both halves' rows accumulated.
    assert session.get.call_count == 3
    assert len(data["rows"]) == 2


def test_query_reports_stops_splitting_at_single_day_and_logs(monkeypatch):
    monkeypatch.setattr(ads.time, "sleep", lambda _s: None)

    session = mock.MagicMock()
    session.get.return_value = _fake_response(
        200, {"headers": [], "rows": [{"cells": []}], "totalMatchedRows": "999999"}
    )

    logged = []
    monkeypatch.setattr(ads.logger, "warning", lambda msg, **kw: logged.append((msg, kw)))

    data = _query_reports(
        session,
        "accounts/pub-1",
        dt.date(2026, 4, 1),
        dt.date(2026, 4, 2),
        ["DATE"],
        ["CLICKS"],
        table_name="page_url_stats",
    )

    # Does not loop forever: stops once start == end, keeping whatever rows came back.
    assert len(data["rows"]) == 2  # one truncated single-day row per day in the range
    assert any("row cap" in msg for msg, _ in logged)


def test_query_reports_preserves_headers_across_split(monkeypatch):
    monkeypatch.setattr(ads.time, "sleep", lambda _s: None)

    session = mock.MagicMock()
    call_count = {"n": 0}

    def fake_get(url, params):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _fake_response(
                200,
                {
                    "headers": [{"name": "DATE", "type": "DIMENSION"}],
                    "rows": [{"cells": []}],
                    "totalMatchedRows": "999999",
                },
            )
        return _fake_response(200, {"headers": [], "rows": [{"cells": []}], "totalMatchedRows": "1"})

    session.get.side_effect = fake_get

    data = _query_reports(
        session,
        "accounts/pub-1",
        dt.date(2026, 4, 1),
        dt.date(2026, 4, 2),
        ["DATE"],
        ["CLICKS"],
        table_name="page_url_stats",
    )
    assert data["headers"] == [{"name": "DATE", "type": "DIMENSION"}]


# ---------------------------------------------------------------------------
# Throttle
# ---------------------------------------------------------------------------


def test_throttle_spaces_requests_per_project():
    ads._next_request_at.clear()
    sleeps: list[float] = []
    with mock.patch.object(ads.time, "monotonic", lambda: 100.0):
        with mock.patch.object(ads.time, "sleep", lambda s: sleeps.append(s)):
            _throttle_impl()
            _throttle_impl()

    assert sleeps == [pytest.approx(ads._MIN_REQUEST_INTERVAL_SECONDS)]
    # One shared slot for the whole project, not one per account.
    assert set(ads._next_request_at) == {ads._PROJECT_THROTTLE_KEY}


def test_throttle_does_not_wait_when_slots_are_available():
    ads._next_request_at.clear()
    sleeps: list[float] = []
    times = iter([100.0, 100.0 + ads._MIN_REQUEST_INTERVAL_SECONDS + 1])
    with mock.patch.object(ads.time, "monotonic", lambda: next(times)):
        with mock.patch.object(ads.time, "sleep", lambda s: sleeps.append(s)):
            _throttle_impl()
            _throttle_impl()

    assert sleeps == []


# ---------------------------------------------------------------------------
# Entity source (fan-out, full refresh)
# ---------------------------------------------------------------------------


def test_entity_source_response_is_unpartitioned_snapshot():
    response = google_adsense_source(
        config=_config(), resource_name="site", team_id=1, resumable_source_manager=_resume_manager()
    )
    assert response.primary_keys == ["name"]
    assert response.partition_keys is None
    assert response.partition_mode is None
    assert response.sort_mode is None


def test_entity_source_account_yields_single_row(monkeypatch):
    monkeypatch.setattr(ads, "google_adsense_session", lambda *a, **kw: mock.MagicMock())
    monkeypatch.setattr(ads, "get_account", lambda session, account_name: {"name": account_name})

    response = google_adsense_source(
        config=_config(), resource_name="account", team_id=1, resumable_source_manager=_resume_manager()
    )
    assert list(response.items()) == [[{"name": "accounts/pub-1234567890"}]]


def test_entity_source_ad_unit_fans_out_per_ad_client(monkeypatch):
    monkeypatch.setattr(ads, "google_adsense_session", lambda *a, **kw: mock.MagicMock())
    monkeypatch.setattr(
        ads,
        "list_ad_clients",
        lambda session, account_name: [
            {"name": "accounts/pub-1/adclients/111"},
            {"name": "accounts/pub-1/adclients/222"},
        ],
    )
    calls = []

    def fake_list_ad_units(session, ad_client_name):
        calls.append(ad_client_name)
        return [{"name": f"{ad_client_name}/adunits/x"}]

    monkeypatch.setattr(ads, "list_ad_units", fake_list_ad_units)

    response = google_adsense_source(
        config=_config(), resource_name="ad_unit", team_id=1, resumable_source_manager=_resume_manager()
    )
    rows = list(response.items())

    assert calls == ["accounts/pub-1/adclients/111", "accounts/pub-1/adclients/222"]
    assert rows == [
        [
            {"name": "accounts/pub-1/adclients/111/adunits/x"},
            {"name": "accounts/pub-1/adclients/222/adunits/x"},
        ]
    ]


def test_entity_source_yields_nothing_when_no_rows(monkeypatch):
    monkeypatch.setattr(ads, "google_adsense_session", lambda *a, **kw: mock.MagicMock())
    monkeypatch.setattr(ads, "list_sites", lambda session, account_name: [])

    response = google_adsense_source(
        config=_config(), resource_name="site", team_id=1, resumable_source_manager=_resume_manager()
    )
    assert list(response.items()) == []


def test_entity_rows_unknown_resource_raises(monkeypatch):
    monkeypatch.setattr(ads, "google_adsense_session", lambda *a, **kw: mock.MagicMock())
    config = _config()
    with pytest.raises(ValueError, match="Unknown entity resource"):
        list(_entity_rows(config, "not_a_real_entity", team_id=1))


# ---------------------------------------------------------------------------
# Reports source (end-to-end wiring + resume)
# ---------------------------------------------------------------------------


def test_reports_source_response_has_partition_metadata():
    response = google_adsense_source(
        config=_config(), resource_name="ad_unit_stats", team_id=1, resumable_source_manager=_resume_manager()
    )
    assert response.primary_keys == ["date", "ad_unit_id"]
    assert response.partition_keys == ["date"]
    assert response.partition_mode == "datetime"
    assert response.partition_format == "day"
    assert response.partition_count == 1
    assert response.partition_size == 1


def test_reports_source_yields_cast_rows(monkeypatch):
    # A single-day window keeps the batch assertion independent of how get_rows
    # chunks the range for checkpointing.
    config = _config(start_date=TODAY - dt.timedelta(days=1))
    monkeypatch.setattr(ads, "_today", lambda *_a, **_kw: TODAY)
    monkeypatch.setattr(ads, "google_adsense_session", lambda *a, **kw: mock.MagicMock())
    monkeypatch.setattr(
        ads,
        "_query_reports",
        lambda **kwargs: {
            "headers": [
                {"name": "DATE", "type": "DIMENSION"},
                {"name": "CLICKS", "type": "METRIC_TALLY"},
                {"name": "ESTIMATED_EARNINGS", "type": "METRIC_CURRENCY", "currencyCode": "USD"},
            ],
            "rows": [{"cells": [{"value": "2026-04-15"}, {"value": "3"}, {"value": "1.25"}]}],
        },
    )

    response = google_adsense_source(
        config=config, resource_name="daily_stats", team_id=1, resumable_source_manager=_resume_manager()
    )
    batches = list(response.items())

    assert batches == [
        [
            {
                "date": "2026-04-15",
                "clicks": 3,
                "estimated_earnings": 1.25,
                "currency_code": "USD",
                "account": "accounts/pub-1234567890",
            }
        ]
    ]


def test_reports_source_yields_nothing_when_no_rows(monkeypatch):
    config = _config(start_date=TODAY - dt.timedelta(days=1))
    monkeypatch.setattr(ads, "_today", lambda *_a, **_kw: TODAY)
    monkeypatch.setattr(ads, "google_adsense_session", lambda *a, **kw: mock.MagicMock())
    monkeypatch.setattr(ads, "_query_reports", lambda **kwargs: {"headers": [], "rows": []})

    response = google_adsense_source(
        config=config, resource_name="daily_stats", team_id=1, resumable_source_manager=_resume_manager()
    )
    assert list(response.items()) == []


def test_reports_source_passes_resolved_window_to_query(monkeypatch):
    config = _config(start_date=TODAY - dt.timedelta(days=30))
    monkeypatch.setattr(ads, "_today", lambda *_a, **_kw: TODAY)
    monkeypatch.setattr(ads, "google_adsense_session", lambda *a, **kw: mock.MagicMock())

    captured: dict = {}
    _capture_query(monkeypatch, captured)

    response = google_adsense_source(
        config=config, resource_name="daily_stats", team_id=1, resumable_source_manager=_resume_manager()
    )
    list(response.items())

    assert captured["account_name"] == "accounts/pub-1234567890"
    assert captured["table_name"] == "daily_stats"
    assert captured["dimensions"] == REPORTS_SCHEMAS["daily_stats"]["dimensions"]
    assert captured["metrics"] == REPORTS_SCHEMAS["daily_stats"]["metrics"]
    assert captured["start_date"] == TODAY - dt.timedelta(days=30)
    assert captured["end_date"] == TODAY - dt.timedelta(days=FRESHNESS_LAG_DAYS)


def test_reports_source_resolves_incremental_window_from_watermark(monkeypatch):
    config = _config(start_date=TODAY - dt.timedelta(days=365))
    monkeypatch.setattr(ads, "_today", lambda *_a, **_kw: TODAY)
    monkeypatch.setattr(ads, "google_adsense_session", lambda *a, **kw: mock.MagicMock())

    captured: dict = {}
    _capture_query(monkeypatch, captured)

    response = google_adsense_source(
        config=config,
        resource_name="daily_stats",
        team_id=1,
        resumable_source_manager=_resume_manager(),
        should_use_incremental_field=True,
        db_incremental_field_last_value=dt.date(2026, 4, 20),
    )
    list(response.items())

    # The cursor is the start of the window.
    assert captured["start_date"] == dt.date(2026, 4, 20)


def test_incremental_sync_does_not_reapply_the_lookback(monkeypatch):
    # The pipeline already shifted db_incremental_field_last_value back by the schema's
    # incremental lookback (source.py's default_incremental_lookback_seconds) before get_rows
    # runs. Subtracting a lookback here too would double the trailing window, so the source
    # must use the cursor exactly as given.
    config = _config(start_date=TODAY - dt.timedelta(days=365))
    monkeypatch.setattr(ads, "_today", lambda *_a, **_kw: TODAY)
    monkeypatch.setattr(ads, "google_adsense_session", lambda *a, **kw: mock.MagicMock())

    captured: dict = {}
    _capture_query(monkeypatch, captured)

    response = google_adsense_source(
        config=config,
        resource_name="daily_stats",
        team_id=1,
        resumable_source_manager=_resume_manager(),
        should_use_incremental_field=True,
        db_incremental_field_last_value=dt.date(2026, 4, 20),
    )
    list(response.items())

    assert captured["start_date"] == dt.date(2026, 4, 20)
    # Explicitly not shifted a further 7 days by the source.
    assert captured["start_date"] != dt.date(2026, 4, 13)


def test_reports_source_resumes_at_last_checkpointed_window(monkeypatch):
    monkeypatch.setattr(ads, "_today", lambda *_a, **_kw: TODAY)
    monkeypatch.setattr(ads, "google_adsense_session", lambda *a, **kw: mock.MagicMock())

    captured: dict = {}
    _capture_query(monkeypatch, captured)

    manager = _resume_manager(
        state=GoogleAdSenseResumeConfig(schema_name="daily_stats", window_start="2026-04-01", window_end="2026-04-20"),
        can_resume=True,
    )

    response = google_adsense_source(
        config=_config(), resource_name="daily_stats", team_id=1, resumable_source_manager=manager
    )
    list(response.items())

    # Resume starts at window_end itself: the checkpointed day is re-fetched rather than
    # skipped. Duplicate rows collapse on the merge key, and never advancing past
    # window_end means the window can't go empty when the watermark catches up to end_date.
    assert captured["start_date"] == dt.date(2026, 4, 20)


def test_reports_source_applies_checkpoint_without_a_table_guard(monkeypatch):
    monkeypatch.setattr(ads, "_today", lambda *_a, **_kw: TODAY)
    monkeypatch.setattr(ads, "google_adsense_session", lambda *a, **kw: mock.MagicMock())

    captured: dict = {}
    _capture_query(monkeypatch, captured)

    manager = _resume_manager(
        state=GoogleAdSenseResumeConfig(
            schema_name="country_stats", window_start="2026-04-01", window_end="2026-04-20"
        ),
        can_resume=True,
    )

    response = google_adsense_source(
        config=_config(), resource_name="daily_stats", team_id=1, resumable_source_manager=manager
    )
    list(response.items())

    # No schema_name guard: any checkpoint moves this table's window. schema_name is
    # recorded for diagnostics only, not used to scope the resume.
    assert captured["start_date"] == dt.date(2026, 4, 20)


def test_reports_source_ignores_checkpoint_when_not_resumable(monkeypatch):
    monkeypatch.setattr(ads, "_today", lambda *_a, **_kw: TODAY)
    monkeypatch.setattr(ads, "google_adsense_session", lambda *a, **kw: mock.MagicMock())

    captured: dict = {}
    _capture_query(monkeypatch, captured)

    manager = _resume_manager(
        state=GoogleAdSenseResumeConfig(schema_name="daily_stats", window_start="2000-01-01", window_end="2000-01-01"),
        can_resume=False,
    )
    response = google_adsense_source(
        config=_config(), resource_name="daily_stats", team_id=1, resumable_source_manager=manager
    )
    list(response.items())

    assert captured["start_date"] == TODAY - dt.timedelta(days=DEFAULT_HISTORY_DAYS)
    manager.load_state.assert_not_called()


def test_reports_source_saves_checkpoint_while_streaming(monkeypatch):
    config = _config(start_date=TODAY - dt.timedelta(days=1))
    monkeypatch.setattr(ads, "_today", lambda *_a, **_kw: TODAY)
    monkeypatch.setattr(ads, "google_adsense_session", lambda *a, **kw: mock.MagicMock())
    monkeypatch.setattr(
        ads,
        "_query_reports",
        lambda **kwargs: {"headers": [], "rows": [{"cells": [{"value": "2026-04-29"}]}]},
    )

    manager = _resume_manager()
    response = google_adsense_source(
        config=config, resource_name="daily_stats", team_id=1, resumable_source_manager=manager
    )
    batches = list(response.items())

    assert len(batches) == 1
    manager.save_state.assert_called()
    saved = manager.save_state.call_args.args[0]
    assert isinstance(saved, GoogleAdSenseResumeConfig)
    assert saved.schema_name == "daily_stats"
    assert saved.window_start == (TODAY - dt.timedelta(days=1)).isoformat()
    assert saved.window_end == (TODAY - dt.timedelta(days=FRESHNESS_LAG_DAYS)).isoformat()


def test_unknown_resource_name_raises():
    # Unknown schemas fall through to REPORTS_SCHEMAS[...] (KeyError); a guard that
    # raises a friendlier ValueError would also satisfy this test.
    with pytest.raises((KeyError, ValueError)):
        google_adsense_source(
            config=_config(),
            resource_name="not_a_real_schema",
            team_id=1,
            resumable_source_manager=_resume_manager(),
        )
