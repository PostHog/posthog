import datetime as dt

import pytest
from unittest import mock

from django.db import OperationalError

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    GoogleSearchConsoleSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console import (
    google_search_console as gsc,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.google_search_console import (
    FRESHNESS_LAG_DAYS,
    HISTORY_DAYS,
    QUOTA_MAX_RETRIES,
    GoogleSearchConsoleQuotaExceededError,
    GoogleSearchConsoleResumeConfig,
    _credentials,
    _get_integration,
    _initial_start_date,
    _is_daily_quota_error,
    _is_quota_error,
    _is_server_error,
    _iter_dates,
    _query_search_analytics,
    _quota_backoff_seconds,
    _resolve_window,
    _row_to_dict,
    google_search_console_source,
    normalize_site_url,
    suggest_registered_site,
)

TODAY = dt.date(2026, 4, 30)


@pytest.mark.parametrize(
    "last_value,expected_start",
    [
        # No last value → full history window from today backwards.
        (None, _initial_start_date(TODAY)),
        # Very old last value → clamped to the history floor.
        (TODAY - dt.timedelta(days=10_000), _initial_start_date(TODAY)),
        # Recent date → used as-is.
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


def test_resolve_window_full_history_spans_history_days():
    # Sanity-check the constant — the no-last-value start is exactly `HISTORY_DAYS` back.
    start, _ = _resolve_window(TODAY, None)
    assert (TODAY - start).days == HISTORY_DAYS


@pytest.mark.parametrize(
    "start,end,expected",
    [
        (
            dt.date(2026, 4, 1),
            dt.date(2026, 4, 3),
            [dt.date(2026, 4, 1), dt.date(2026, 4, 2), dt.date(2026, 4, 3)],
        ),
        # start > end yields no dates.
        (dt.date(2026, 4, 5), dt.date(2026, 4, 1), []),
    ],
)
def test_iter_dates(start, end, expected):
    assert list(_iter_dates(start, end)) == expected


def test_row_to_dict_with_date_and_query():
    row = {"keys": ["2026-04-15", "posthog"], "clicks": 10, "impressions": 100, "ctr": 0.1, "position": 4.5}
    out = _row_to_dict(row, ["date", "query"])

    assert out["date"] == dt.date(2026, 4, 15)
    assert out["query"] == "posthog"
    assert out["clicks"] == 10
    assert out["impressions"] == 100
    assert out["ctr"] == pytest.approx(0.1)
    assert out["position"] == pytest.approx(4.5)


def test_row_to_dict_handles_missing_metrics():
    out = _row_to_dict({"keys": ["2026-04-15"]}, ["date"])
    assert out["clicks"] == 0
    assert out["impressions"] == 0
    assert out["ctr"] == 0.0
    assert out["position"] == 0.0


def test_row_to_dict_injects_iter_date_when_date_not_in_dimensions():
    # `searchAppearance` schema can't include date in its API request, so the iterator
    # supplies the date externally to keep the per-day partition.
    row = {"keys": ["RICH_RESULT"], "clicks": 5, "impressions": 50, "ctr": 0.1, "position": 3.0}
    out = _row_to_dict(row, ["searchAppearance"], iter_date=dt.date(2026, 4, 15))

    assert out["date"] == dt.date(2026, 4, 15)
    assert out["searchAppearance"] == "RICH_RESULT"


def test_row_to_dict_prefers_api_date_over_iter_date():
    # When date IS in dimensions, the API's value wins — iter_date is a fallback only.
    row = {"keys": ["2026-04-15", "posthog"], "clicks": 1, "impressions": 1, "ctr": 1.0, "position": 1.0}
    out = _row_to_dict(row, ["date", "query"], iter_date=dt.date(1999, 1, 1))

    assert out["date"] == dt.date(2026, 4, 15)


def test_credentials_refreshes_stale_db_connection_before_query(monkeypatch):
    # The ORM read runs lazily inside `get_rows` on a worker thread whose pooled
    # Django connection may have been closed server-side, surfacing as
    # `OperationalError: the connection is closed`. We must drop the stale
    # connection before querying, so the read happens on a fresh connection.
    calls: list[str] = []

    monkeypatch.setattr(gsc, "close_old_connections", lambda: calls.append("close_old_connections"))

    integration = mock.MagicMock()
    integration.refresh_token = "refresh-token"

    def fake_get(*args, **kwargs):
        calls.append("Integration.objects.get")
        return integration

    monkeypatch.setattr(gsc.Integration.objects, "get", fake_get)

    creds = _credentials(integration_id=1, team_id=1)

    assert calls == ["close_old_connections", "Integration.objects.get"]
    assert creds.refresh_token == "refresh-token"


def test_get_integration_rides_out_pool_wait_timeout_then_succeeds(monkeypatch):
    # A saturated connection pooler rejects the query with `query_wait_timeout`; the short
    # backoff lets the pool drain so a later attempt on a fresh connection succeeds.
    integration = mock.MagicMock()
    get = mock.Mock(
        side_effect=[
            OperationalError("query_wait_timeout"),
            OperationalError("query_wait_timeout"),
            integration,
        ]
    )

    monkeypatch.setattr(gsc, "close_old_connections", lambda: None)
    monkeypatch.setattr(gsc.Integration.objects, "get", get)
    sleeps: list[float] = []
    monkeypatch.setattr(gsc.time, "sleep", lambda seconds: sleeps.append(seconds))

    result = _get_integration(integration_id=1, team_id=2)

    assert result is integration
    assert get.call_count == 3
    assert sleeps == [2, 4]


def test_get_integration_reraises_after_exhausting_attempts(monkeypatch):
    get = mock.Mock(side_effect=OperationalError("query_wait_timeout"))

    monkeypatch.setattr(gsc, "close_old_connections", lambda: None)
    monkeypatch.setattr(gsc.Integration.objects, "get", get)
    sleeps: list[float] = []
    monkeypatch.setattr(gsc.time, "sleep", lambda seconds: sleeps.append(seconds))

    with pytest.raises(OperationalError):
        _get_integration(integration_id=1, team_id=2)

    # Bounded attempts: it gives up rather than looping forever, leaving Temporal to retry the activity.
    assert get.call_count == 4
    assert sleeps == [2, 4, 6]


def _make_response(config: GoogleSearchConsoleSourceConfig, rows_per_call: list[list[dict]]):
    """Build a SourceResponse where _query_search_analytics returns the given pages in order."""
    inputs = mock.MagicMock()
    inputs.team_id = 1
    inputs.job_id = "job-1"

    manager = mock.MagicMock()
    manager.can_resume.return_value = False

    saved_states: list[GoogleSearchConsoleResumeConfig] = []
    manager.save_state.side_effect = lambda state: saved_states.append(state)

    response = google_search_console_source(
        config=config,
        resource_name="search_analytics_by_date",
        team_id=1,
        resumable_source_manager=manager,
        should_use_incremental_field=True,
        db_incremental_field_last_value=dt.date(2026, 4, 25),
    )
    return response, manager, saved_states


def test_source_yields_rows_and_advances_dates(monkeypatch):
    config = GoogleSearchConsoleSourceConfig(
        site_url="https://example.com/",
        google_search_console_integration_id=1,
    )

    fake_today = dt.date(2026, 4, 30)
    pages_per_date: dict[str, list[list[dict]]] = {
        "2026-04-25": [[{"keys": ["2026-04-25"], "clicks": 1, "impressions": 5, "ctr": 0.2, "position": 3.0}]],
        "2026-04-26": [[{"keys": ["2026-04-26"], "clicks": 2, "impressions": 6, "ctr": 0.33, "position": 2.5}]],
        "2026-04-27": [[]],
    }
    end_date = fake_today - dt.timedelta(days=FRESHNESS_LAG_DAYS)
    # Fill any remaining dates with empty pages
    cursor = dt.date(2026, 4, 25)
    while cursor <= end_date:
        pages_per_date.setdefault(cursor.isoformat(), [[]])
        cursor += dt.timedelta(days=1)

    queries: list[tuple[str, int]] = []

    def fake_query(session, site_url, start_date, end_date, dimensions, start_row, row_limit=25000):
        queries.append((start_date, start_row))
        pages = pages_per_date.get(start_date, [[]])
        return pages.pop(0) if pages else []

    response, _manager, saved_states = _make_response(config, [])

    monkeypatch.setattr(
        "products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.google_search_console._today",
        lambda: fake_today,
    )
    monkeypatch.setattr(
        "products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.google_search_console.google_search_console_session",
        lambda *a, **kw: mock.MagicMock(),
    )
    monkeypatch.setattr(
        "products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.google_search_console._query_search_analytics",
        fake_query,
    )

    batches = list(response.items())

    yielded_dates = [batch[0]["date"] for batch in batches]
    assert dt.date(2026, 4, 25) in yielded_dates
    assert dt.date(2026, 4, 26) in yielded_dates
    # Each non-empty date that had a single page advances state to the *next* date with start_row=0
    advance_to_next_states = [s for s in saved_states if s.start_row == 0]
    assert any(s.current_date == "2026-04-26" for s in advance_to_next_states)
    assert any(s.current_date == "2026-04-27" for s in advance_to_next_states)


def test_source_resumes_from_saved_state(monkeypatch):
    config = GoogleSearchConsoleSourceConfig(
        site_url="https://example.com/",
        google_search_console_integration_id=1,
    )

    fake_today = dt.date(2026, 4, 30)
    queries: list[tuple[str, int]] = []

    def fake_query(session, site_url, start_date, end_date, dimensions, start_row, row_limit=25000):
        queries.append((start_date, start_row))
        return []

    manager = mock.MagicMock()
    manager.can_resume.return_value = True
    manager.load_state.return_value = GoogleSearchConsoleResumeConfig(current_date="2026-04-26", start_row=5000)

    monkeypatch.setattr(
        "products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.google_search_console._today",
        lambda: fake_today,
    )
    monkeypatch.setattr(
        "products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.google_search_console.google_search_console_session",
        lambda *a, **kw: mock.MagicMock(),
    )
    monkeypatch.setattr(
        "products.warehouse_sources.backend.temporal.data_imports.sources.google_search_console.google_search_console._query_search_analytics",
        fake_query,
    )

    response = google_search_console_source(
        config=config,
        resource_name="search_analytics_by_date",
        team_id=1,
        resumable_source_manager=manager,
        should_use_incremental_field=True,
        db_incremental_field_last_value=dt.date(2026, 4, 1),
    )

    list(response.items())  # type: ignore[arg-type]

    # Earliest query should be the resumed date+offset
    assert queries[0] == ("2026-04-26", 5000)
    # No queries at earlier dates
    assert all(q[0] >= "2026-04-26" for q in queries)


def test_source_response_has_partition_metadata():
    config = GoogleSearchConsoleSourceConfig(
        site_url="https://example.com/",
        google_search_console_integration_id=1,
    )
    manager = mock.MagicMock()
    response = google_search_console_source(
        config=config,
        resource_name="search_analytics_by_query",
        team_id=1,
        resumable_source_manager=manager,
    )

    assert response.primary_keys == ["date", "query"]
    assert response.partition_keys == ["date"]
    assert response.partition_mode == "datetime"
    assert response.partition_format == "day"
    assert response.partition_count == 1
    assert response.partition_size == 1


def test_unknown_resource_name_raises():
    config = GoogleSearchConsoleSourceConfig(
        site_url="https://example.com/",
        google_search_console_integration_id=1,
    )
    with pytest.raises(ValueError, match="Unknown Google Search Console schema"):
        google_search_console_source(
            config=config,
            resource_name="not_a_real_schema",
            team_id=1,
            resumable_source_manager=mock.MagicMock(),
        )


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


_QUOTA_BODY = {"error": {"code": 403, "errors": [{"domain": "usageLimits", "reason": "quotaExceeded"}]}}
_PERMISSION_BODY = {"error": {"code": 403, "errors": [{"domain": "global", "reason": "forbidden"}]}}
_DAILY_QUOTA_BODY = {"error": {"code": 403, "errors": [{"domain": "usageLimits", "reason": "dailyLimitExceeded"}]}}


@pytest.mark.parametrize(
    "response,expected",
    [
        (_fake_response(200, {"rows": []}), False),
        (_fake_response(429), True),
        (_fake_response(403, _QUOTA_BODY), True),
        (_fake_response(403, {"error": {"errors": [{"reason": "rateLimitExceeded"}]}}), True),
        (_fake_response(403, _PERMISSION_BODY), False),
        (_fake_response(403, {}), False),
        (_fake_response(403, {"error": None}), False),
        (_fake_response(403, {"error": "Forbidden"}), False),
        (_fake_response(401), False),
    ],
)
def test_is_quota_error(response, expected):
    assert _is_quota_error(response) is expected


@pytest.mark.parametrize(
    "response,expected",
    [
        (_fake_response(403, _DAILY_QUOTA_BODY), True),
        (_fake_response(403, _QUOTA_BODY), False),
        (_fake_response(403, {"error": None}), False),
        (_fake_response(403, {"error": "Forbidden"}), False),
        (_fake_response(429), False),
        (_fake_response(200, {"rows": []}), False),
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
        (_fake_response(403, _PERMISSION_BODY), False),
        (_fake_response(200, {"rows": []}), False),
    ],
)
def test_is_server_error(response, expected):
    assert _is_server_error(response) is expected


def test_quota_backoff_prefers_retry_after_header():
    resp = _fake_response(403, _QUOTA_BODY, headers={"Retry-After": "30"})
    assert _quota_backoff_seconds(resp, attempt=0) == 30.0


def test_quota_backoff_falls_back_to_exponential():
    resp = _fake_response(403, _QUOTA_BODY)
    assert _quota_backoff_seconds(resp, attempt=0) == 2.0
    assert _quota_backoff_seconds(resp, attempt=2) == 8.0


def test_query_retries_quota_then_succeeds(monkeypatch):
    monkeypatch.setattr(gsc.time, "sleep", lambda _s: None)
    monkeypatch.setattr(gsc, "_throttle", lambda _site: None)

    session = mock.MagicMock()
    session.post.side_effect = [
        _fake_response(403, _QUOTA_BODY),
        _fake_response(403, _QUOTA_BODY),
        _fake_response(200, {"rows": [{"keys": ["2026-04-15"], "clicks": 1}]}),
    ]

    rows = _query_search_analytics(session, "sc-domain:example.com", "2026-04-15", "2026-04-15", ["date"], 0)

    assert rows == [{"keys": ["2026-04-15"], "clicks": 1}]
    assert session.post.call_count == 3


def test_query_raises_quota_error_after_max_retries(monkeypatch):
    monkeypatch.setattr(gsc.time, "sleep", lambda _s: None)
    monkeypatch.setattr(gsc, "_throttle", lambda _site: None)

    session = mock.MagicMock()
    session.post.return_value = _fake_response(403, _QUOTA_BODY)

    with pytest.raises(GoogleSearchConsoleQuotaExceededError):
        _query_search_analytics(session, "sc-domain:example.com", "2026-04-15", "2026-04-15", ["date"], 0)

    # Initial attempt + QUOTA_MAX_RETRIES retries.
    assert session.post.call_count == QUOTA_MAX_RETRIES + 1


def test_query_daily_quota_raises_without_retry(monkeypatch):
    monkeypatch.setattr(gsc.time, "sleep", lambda _s: None)
    monkeypatch.setattr(gsc, "_throttle", lambda _site: None)

    session = mock.MagicMock()
    session.post.return_value = _fake_response(403, _DAILY_QUOTA_BODY)

    with pytest.raises(GoogleSearchConsoleQuotaExceededError):
        _query_search_analytics(session, "sc-domain:example.com", "2026-04-15", "2026-04-15", ["date"], 0)

    assert session.post.call_count == 1


def test_query_permission_error_is_not_retried(monkeypatch):
    monkeypatch.setattr(gsc.time, "sleep", lambda _s: None)
    monkeypatch.setattr(gsc, "_throttle", lambda _site: None)

    session = mock.MagicMock()
    session.post.return_value = _fake_response(403, _PERMISSION_BODY)

    with pytest.raises(requests.HTTPError, match="403 Client Error"):
        _query_search_analytics(session, "sc-domain:example.com", "2026-04-15", "2026-04-15", ["date"], 0)

    # Fatal on the first response — no retries.
    assert session.post.call_count == 1


def test_query_retries_server_error_then_succeeds(monkeypatch):
    monkeypatch.setattr(gsc.time, "sleep", lambda _s: None)
    monkeypatch.setattr(gsc, "_throttle", lambda _site: None)

    session = mock.MagicMock()
    session.post.side_effect = [
        _fake_response(500),
        _fake_response(503),
        _fake_response(200, {"rows": [{"keys": ["2026-04-15"], "clicks": 1}]}),
    ]

    rows = _query_search_analytics(session, "sc-domain:example.com", "2026-04-15", "2026-04-15", ["date"], 0)

    assert rows == [{"keys": ["2026-04-15"], "clicks": 1}]
    assert session.post.call_count == 3


def test_query_server_error_bubbles_http_error_after_max_retries(monkeypatch):
    monkeypatch.setattr(gsc.time, "sleep", lambda _s: None)
    monkeypatch.setattr(gsc, "_throttle", lambda _site: None)

    session = mock.MagicMock()
    session.post.return_value = _fake_response(500)

    # A persistent 5xx exhausts the inline budget and surfaces the real HTTPError (retryable
    # at the activity level), not the quota error.
    with pytest.raises(requests.HTTPError):
        _query_search_analytics(session, "sc-domain:example.com", "2026-04-15", "2026-04-15", ["date"], 0)

    assert session.post.call_count == QUOTA_MAX_RETRIES + 1


def test_throttle_spaces_requests_per_site(monkeypatch):
    gsc._next_request_at.clear()
    fake_now = {"t": 100.0}
    sleeps: list[float] = []
    monkeypatch.setattr(gsc.time, "monotonic", lambda: fake_now["t"])
    monkeypatch.setattr(gsc.time, "sleep", lambda s: sleeps.append(s))

    # First call for a site doesn't wait; the next is spaced by the min interval.
    gsc._throttle("sc-domain:example.com")
    gsc._throttle("sc-domain:example.com")

    assert sleeps == [pytest.approx(gsc._MIN_REQUEST_INTERVAL_SECONDS)]


@pytest.mark.parametrize(
    "raw,expected",
    [
        # Already canonical — left untouched.
        ("https://example.com/", "https://example.com/"),
        ("sc-domain:example.com", "sc-domain:example.com"),
        # Percent-encoded values copied from a URL bar.
        ("sc-domain%3Abidsstack.com", "sc-domain:bidsstack.com"),
        ("sc-domain%3Atopol.io", "sc-domain:topol.io"),
        ("https%3A%2F%2Fexample.com%2F", "https://example.com/"),
        # URL-prefix property missing its trailing slash.
        ("https://agentic30.app", "https://agentic30.app/"),
        ("https://docebo.com", "https://docebo.com/"),
        # Capitalized scheme/host — Google stores both lowercase, so an exact match needs them lowered.
        ("Https://www.veteranpcs.com/", "https://www.veteranpcs.com/"),
        ("HTTPS://Example.com", "https://example.com/"),
        # Path case is preserved — it can be significant for a URL-prefix property.
        ("Https://example.com/Blog", "https://example.com/Blog/"),
        # Surrounding whitespace.
        ("  https://example.com/  ", "https://example.com/"),
        # The full Search Console UI URL — the property lives in resource_id.
        (
            "https://search.google.com/search-console/performance/search-analytics"
            "?resource_id=https%3A%2F%2Fwww.viamar.ca%2F&metrics=CLICKS%2CIMPRESSIONS",
            "https://www.viamar.ca/",
        ),
        # Bare hostname is ambiguous (URL-prefix vs domain) — left untouched.
        ("agentic30.app", "agentic30.app"),
        ("agentic30.app/", "agentic30.app/"),
    ],
)
def test_normalize_site_url(raw, expected):
    assert normalize_site_url(raw) == expected


@pytest.mark.parametrize(
    "site_url,registered,expected",
    [
        # Bare hostname matches a registered URL-prefix property.
        ("plotlens.ai", ["https://plotlens.ai/"], "https://plotlens.ai/"),
        ("buyticketbrasil.com", ["https://buyticketbrasil.com/"], "https://buyticketbrasil.com/"),
        # Bare hostname matches a registered domain property.
        ("autocomply.dev", ["sc-domain:autocomply.dev"], "sc-domain:autocomply.dev"),
        # URL-prefix preferred when both forms are registered.
        ("example.com", ["sc-domain:example.com", "https://example.com/"], "https://example.com/"),
        # A trailing slash on the bare hostname is tolerated.
        ("plotlens.ai/", ["https://plotlens.ai/"], "https://plotlens.ai/"),
        # An uppercase bare hostname is lowercased to match Google's canonical property names.
        ("PlotLens.AI", ["https://plotlens.ai/"], "https://plotlens.ai/"),
        ("EXAMPLE.COM", ["sc-domain:example.com"], "sc-domain:example.com"),
        # No registered property matches — nothing to suggest.
        ("plotlens.ai", ["https://other.com/"], None),
        # Already scheme-qualified or a domain property: not ambiguous, so no suggestion.
        ("https://plotlens.ai/", ["https://plotlens.ai/"], None),
        ("sc-domain:plotlens.ai", ["sc-domain:plotlens.ai"], None),
    ],
)
def test_suggest_registered_site(site_url, registered, expected):
    assert suggest_registered_site(site_url, registered) == expected
