import datetime as dt
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest import mock

from django.db import OperationalError

import requests
from google.auth.exceptions import RefreshError

from posthog.models.integration import Integration

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googleanalytics import (
    GoogleAnalyticsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_analytics import google_analytics as ga
from products.warehouse_sources.backend.temporal.data_imports.sources.google_analytics.google_analytics import (
    LOOKBACK_DAYS,
    RUNREPORT_MAX_RETRIES,
    GoogleAnalyticsQuotaExceededError,
    GoogleAnalyticsResumeConfig,
    _convert_metric_value,
    _credentials,
    _get_integration,
    _initial_start_date,
    _is_quota_error,
    _is_transient_refresh_error,
    _parse_ga4_date,
    _resolve_window,
    _run_report,
    _runreport_backoff_seconds,
    google_analytics_source,
)

TODAY = dt.date(2026, 4, 30)


@pytest.mark.parametrize(
    "last_value,expected_start",
    [
        # No last value → full history window from today backwards.
        (None, _initial_start_date(TODAY)),
        # Very old last value → clamped to the history floor.
        (TODAY - dt.timedelta(days=10_000), _initial_start_date(TODAY)),
        # Recent date → re-fetch from the lookback window before it.
        (TODAY - dt.timedelta(days=10), TODAY - dt.timedelta(days=10 + LOOKBACK_DAYS)),
        # ISO string is accepted and parsed.
        ("2026-04-15", dt.date(2026, 4, 15) - dt.timedelta(days=LOOKBACK_DAYS)),
        # Datetime is accepted and truncated to its date.
        (dt.datetime(2026, 4, 15, 12, 0, 0), dt.date(2026, 4, 15) - dt.timedelta(days=LOOKBACK_DAYS)),
    ],
)
def test_resolve_window_start(last_value, expected_start):
    start, end = _resolve_window(TODAY, last_value)
    assert start == expected_start
    # Today's aggregates are still accruing — the window always ends at yesterday.
    assert end == TODAY - dt.timedelta(days=1)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("20260415", dt.date(2026, 4, 15)),
        # Unparseable values pass through untouched rather than crashing the sync.
        ("(other)", "(other)"),
        ("2026-04-15", "2026-04-15"),
    ],
)
def test_parse_ga4_date(raw, expected):
    assert _parse_ga4_date(raw) == expected


@pytest.mark.parametrize(
    "value,metric_type,expected",
    [
        ("123", "TYPE_INTEGER", 123),
        ("12.5", "TYPE_FLOAT", 12.5),
        ("88.2", "TYPE_SECONDS", 88.2),
        ("0.25", "TYPE_STANDARD", 0.25),
        # Integers parse as ints, everything else as floats.
        ("123", "", 123.0),
        # Garbage falls back to the raw value.
        ("not-a-number", "TYPE_INTEGER", "not-a-number"),
        (None, "TYPE_FLOAT", None),
    ],
)
def test_convert_metric_value(value, metric_type, expected):
    assert _convert_metric_value(value, metric_type) == expected


def test_credentials_refreshes_stale_db_connection_before_query(monkeypatch):
    # The ORM read runs lazily inside `get_rows` on a worker thread whose pooled
    # Django connection may have been closed server-side. We must drop the stale
    # connection before querying, so the read happens on a fresh connection.
    calls: list[str] = []

    monkeypatch.setattr(ga, "close_old_connections", lambda: calls.append("close_old_connections"))

    integration = mock.MagicMock()
    integration.refresh_token = "refresh-token"

    def fake_get(*args, **kwargs):
        calls.append("Integration.objects.get")
        return integration

    monkeypatch.setattr(ga.Integration.objects, "get", fake_get)

    creds = _credentials(integration_id=1, team_id=1)

    assert calls == ["close_old_connections", "Integration.objects.get"]
    assert creds.refresh_token == "refresh-token"


_INTEGRATION_GET_PATH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.google_analytics.google_analytics."
    "Integration.objects.get"
)
_CLOSE_CONNECTIONS_PATH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.google_analytics.google_analytics."
    "close_old_connections"
)
_SLEEP_PATH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.google_analytics.google_analytics.time.sleep"
)


class TestGetIntegrationDbResilience:
    def test_reraises_after_exhausting_attempts(self):
        get = mock.Mock(side_effect=OperationalError("query_wait_timeout"))

        with (
            mock.patch(_INTEGRATION_GET_PATH, get),
            mock.patch(_CLOSE_CONNECTIONS_PATH),
            mock.patch(_SLEEP_PATH),
        ):
            with pytest.raises(OperationalError):
                _get_integration(integration_id=1, team_id=2)

        # Bounded attempts: it gives up rather than looping forever, leaving Temporal to retry the activity.
        assert get.call_count == 4

    def test_missing_integration_is_not_retried(self):
        get = mock.Mock(side_effect=Integration.DoesNotExist())

        with mock.patch(_INTEGRATION_GET_PATH, get), mock.patch(_CLOSE_CONNECTIONS_PATH), mock.patch(_SLEEP_PATH):
            with pytest.raises(Integration.DoesNotExist):
                _get_integration(integration_id=1, team_id=2)

        # A deleted integration row is non-retryable — don't mask it as a transient drop.
        assert get.call_count == 1


def _fake_response(status_code: int, json_body: dict | None = None, headers: dict | None = None):
    resp = mock.MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.headers = headers or {}
    resp.text = "" if json_body is None else str(json_body)
    resp.json.return_value = json_body if json_body is not None else {}

    def raise_for_status():
        if not resp.ok:
            raise requests.HTTPError(f"{status_code} Client Error: oops for url: https://example", response=resp)

    resp.raise_for_status.side_effect = raise_for_status
    return resp


@pytest.mark.parametrize(
    "status_code,expected",
    [
        (429, True),
        (403, False),
        (500, False),
        (200, False),
    ],
)
def test_is_quota_error(status_code, expected):
    assert _is_quota_error(_fake_response(status_code)) is expected


def test_quota_backoff_honors_retry_after():
    response = _fake_response(429, headers={"Retry-After": "17"})
    assert _runreport_backoff_seconds(response, attempt=0) == 17.0


def test_quota_backoff_falls_back_to_exponential():
    response = _fake_response(429, headers={"Retry-After": "soon"})
    assert _runreport_backoff_seconds(response, attempt=2) == ga.RUNREPORT_BACKOFF_BASE_SECONDS * 4


def test_run_report_retries_quota_errors_then_succeeds(monkeypatch):
    monkeypatch.setattr(ga.time, "sleep", lambda _: None)
    payload = {"rows": [], "rowCount": 0}
    session = mock.MagicMock()
    session.post.side_effect = [
        _fake_response(429),
        _fake_response(429),
        _fake_response(200, payload),
    ]

    result = _run_report(
        session=session,
        property_id="123",
        start_date="2026-04-01",
        end_date="2026-04-30",
        dimensions=["date"],
        metrics=["totalUsers"],
        offset=0,
    )

    assert result == payload
    assert session.post.call_count == 3


def test_run_report_raises_after_exhausting_quota_retries(monkeypatch):
    monkeypatch.setattr(ga.time, "sleep", lambda _: None)
    session = mock.MagicMock()
    session.post.return_value = _fake_response(429)

    with pytest.raises(GoogleAnalyticsQuotaExceededError):
        _run_report(
            session=session,
            property_id="123",
            start_date="2026-04-01",
            end_date="2026-04-30",
            dimensions=["date"],
            metrics=["totalUsers"],
            offset=0,
        )

    assert session.post.call_count == RUNREPORT_MAX_RETRIES + 1


@pytest.mark.parametrize("status_code", [400, 401, 403, 404])
def test_run_report_raises_http_error_for_non_quota_failures(status_code):
    session = mock.MagicMock()
    session.post.return_value = _fake_response(status_code)

    with pytest.raises(requests.HTTPError):
        _run_report(
            session=session,
            property_id="123",
            start_date="2026-04-01",
            end_date="2026-04-30",
            dimensions=["date"],
            metrics=["totalUsers"],
            offset=0,
        )

    assert session.post.call_count == 1


# A Bad Gateway from Google's OAuth token endpoint arrives as an HTML page, not JSON.
_HTML_502_BODY = (
    "<!DOCTYPE html>\n<html lang=en>\n  <title>Error 502 (Server Error)!!1</title>\n"
    "  <p><b>502.</b> That's an error.\n  <p>The server encountered a temporary error "
    "and could not complete your request."
)


@pytest.mark.parametrize(
    "error,expected",
    [
        # 502 gateway page: google-auth omits 502 from its retryable status codes, but it's transient.
        (RefreshError(_HTML_502_BODY), True),
        # google-auth flags 500/503/504/408/429 (and JSON server errors) retryable itself.
        (RefreshError("temporarily_unavailable: try again later", retryable=True), True),
        # Revoked/expired refresh token — permanent, must not be retried inline.
        (RefreshError("invalid_grant: Token has been expired or revoked."), False),
        (RefreshError("invalid_scope: Bad Request"), False),
    ],
)
def test_is_transient_refresh_error(error, expected):
    assert _is_transient_refresh_error(error) is expected


def test_run_report_retries_transient_token_refresh_error_then_succeeds(monkeypatch):
    monkeypatch.setattr(ga.time, "sleep", lambda _: None)
    payload = {"rows": [], "rowCount": 0}
    session = mock.MagicMock()
    session.post.side_effect = [
        # AuthorizedSession raises RefreshError from post() when the token endpoint 502s mid-refresh.
        RefreshError(_HTML_502_BODY),
        _fake_response(200, payload),
    ]

    result = _run_report(
        session=session,
        property_id="123",
        start_date="2026-04-01",
        end_date="2026-04-30",
        dimensions=["date"],
        metrics=["totalUsers"],
        offset=0,
    )

    assert result == payload
    assert session.post.call_count == 2


def test_run_report_permanent_token_refresh_error_bubbles_without_retry(monkeypatch):
    monkeypatch.setattr(ga.time, "sleep", lambda _: None)
    session = mock.MagicMock()
    session.post.side_effect = RefreshError("invalid_grant: Token has been expired or revoked.")

    # A revoked/expired refresh token never recovers, so it must bubble on the first attempt
    # (matching get_non_retryable_errors' "invalid_grant") rather than burning the inline budget.
    with pytest.raises(RefreshError, match="invalid_grant"):
        _run_report(
            session=session,
            property_id="123",
            start_date="2026-04-01",
            end_date="2026-04-30",
            dimensions=["date"],
            metrics=["totalUsers"],
            offset=0,
        )

    assert session.post.call_count == 1


_CONNECTION_DROPS = [
    requests.exceptions.ChunkedEncodingError("Connection broken: IncompleteRead(5398 bytes read, 4842 more expected)"),
    requests.exceptions.ConnectionError(
        "('Connection aborted.', ConnectionResetError(104, 'Connection reset by peer'))"
    ),
    requests.exceptions.ReadTimeout("Read timed out."),
]


@pytest.mark.parametrize("error", _CONNECTION_DROPS)
def test_run_report_raises_connection_drop_after_exhausting_retries(monkeypatch, error):
    monkeypatch.setattr(ga.time, "sleep", lambda _: None)
    session = mock.MagicMock()
    session.post.side_effect = error

    with pytest.raises(type(error)):
        _run_report(
            session=session,
            property_id="123",
            start_date="2026-04-01",
            end_date="2026-04-30",
            dimensions=["date"],
            metrics=["totalUsers"],
            offset=0,
        )

    assert session.post.call_count == RUNREPORT_MAX_RETRIES + 1


def test_run_report_raises_http_error_after_exhausting_server_error_retries(monkeypatch):
    monkeypatch.setattr(ga.time, "sleep", lambda _: None)
    session = mock.MagicMock()
    session.post.return_value = _fake_response(503)

    with pytest.raises(requests.HTTPError):
        _run_report(
            session=session,
            property_id="123",
            start_date="2026-04-01",
            end_date="2026-04-30",
            dimensions=["date"],
            metrics=["totalUsers"],
            offset=0,
        )

    assert session.post.call_count == RUNREPORT_MAX_RETRIES + 1


def _report_payload(dates: list[str], users: list[int], row_count: int | None = None) -> dict:
    return {
        "dimensionHeaders": [{"name": "date"}],
        "metricHeaders": [{"name": "totalUsers", "type": "TYPE_INTEGER"}],
        "rows": [
            {"dimensionValues": [{"value": date}], "metricValues": [{"value": str(value)}]}
            for date, value in zip(dates, users)
        ],
        "rowCount": row_count if row_count is not None else len(dates),
    }


def _patch_session(monkeypatch):
    monkeypatch.setattr(
        "products.warehouse_sources.backend.temporal.data_imports.sources.google_analytics.google_analytics.google_analytics_session",
        lambda *a, **kw: mock.MagicMock(),
    )


def _config(custom_reports: str | None = None) -> GoogleAnalyticsSourceConfig:
    return GoogleAnalyticsSourceConfig(
        property_id="123456789", google_analytics_integration_id=1, custom_reports=custom_reports
    )


def test_source_paginates_within_chunk_and_saves_offsets(monkeypatch):
    fake_today = dt.date(2026, 4, 30)
    monkeypatch.setattr(ga, "_today", lambda: fake_today)
    _patch_session(monkeypatch)

    pages = {
        0: _report_payload(["20260423", "20260424"], [1, 2], row_count=3),
        2: _report_payload(["20260425"], [3], row_count=3),
    }

    def fake_run_report(session, property_id, start_date, end_date, dimensions, metrics, offset, limit=50000):
        return pages[offset]

    monkeypatch.setattr(ga, "_run_report", fake_run_report)

    manager = mock.MagicMock()
    manager.can_resume.return_value = False
    saved_states: list[GoogleAnalyticsResumeConfig] = []
    manager.save_state.side_effect = lambda state: saved_states.append(state)

    response = google_analytics_source(
        config=_config(),
        resource_name="website_overview",
        team_id=1,
        resumable_source_manager=manager,
        should_use_incremental_field=True,
        db_incremental_field_last_value=dt.date(2026, 4, 25),
    )

    batches = list(cast(Iterable[Any], response.items()))

    assert len(batches) == 2
    # Mid-chunk state saves the in-progress chunk with the next offset; the final
    # page advances to the next chunk.
    assert [(s.chunk_start, s.offset) for s in saved_states] == [("2026-04-23", 2), ("2026-04-30", 0)]


def test_source_resume_past_end_date_yields_nothing(monkeypatch):
    fake_today = dt.date(2026, 4, 30)
    monkeypatch.setattr(ga, "_today", lambda: fake_today)
    _patch_session(monkeypatch)

    fake_run_report = mock.MagicMock()
    monkeypatch.setattr(ga, "_run_report", fake_run_report)

    manager = mock.MagicMock()
    manager.can_resume.return_value = True
    # Saved state says everything up to the end of the window is already synced.
    manager.load_state.return_value = GoogleAnalyticsResumeConfig(chunk_start="2026-04-30", offset=0)

    response = google_analytics_source(
        config=_config(),
        resource_name="website_overview",
        team_id=1,
        resumable_source_manager=manager,
        should_use_incremental_field=True,
        db_incremental_field_last_value=dt.date(2026, 4, 25),
    )

    assert list(cast(Iterable[Any], response.items())) == []
    fake_run_report.assert_not_called()


def test_source_requests_user_defined_custom_report(monkeypatch):
    # A custom report drives the exact dimensions/metrics sent to runReport (date prepended),
    # proving user config reaches the generic fetch layer, and its primary key is date + dims.
    fake_today = dt.date(2026, 4, 30)
    monkeypatch.setattr(ga, "_today", lambda: fake_today)
    _patch_session(monkeypatch)

    seen: list[tuple[list[str], list[str]]] = []

    def fake_run_report(session, property_id, start_date, end_date, dimensions, metrics, offset, limit=50000):
        seen.append((dimensions, metrics))
        return _report_payload([], [])

    monkeypatch.setattr(ga, "_run_report", fake_run_report)

    custom = '[{"name": "paid_campaigns", "dimensions": ["sessionCampaignName", "sessionSource"], "metrics": ["sessions", "purchaseRevenue"]}]'
    response = google_analytics_source(
        config=_config(custom_reports=custom),
        resource_name="paid_campaigns",
        team_id=1,
        resumable_source_manager=mock.MagicMock(can_resume=mock.Mock(return_value=False)),
    )

    list(cast(Iterable[Any], response.items()))

    assert response.primary_keys == ["date", "sessionCampaignName", "sessionSource"]
    assert seen[0] == (["date", "sessionCampaignName", "sessionSource"], ["sessions", "purchaseRevenue"])


def test_unknown_resource_name_raises():
    with pytest.raises(ValueError, match="Unknown Google Analytics schema"):
        google_analytics_source(
            config=_config(),
            resource_name="not_a_real_schema",
            team_id=1,
            resumable_source_manager=mock.MagicMock(),
        )
