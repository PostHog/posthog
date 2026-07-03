import datetime as dt
from collections.abc import Iterable
from typing import Any, cast

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import InstagramSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.instagram import instagram as ig
from products.warehouse_sources.backend.temporal.data_imports.sources.instagram.instagram import (
    INSIGHTS_LOOKBACK_DAYS,
    INSTAGRAM_AUTH_ERROR_MESSAGE,
    InstagramResumeConfig,
    _flatten_media_row,
    _insight_values_to_rows,
    _is_permanent_auth_error,
    _is_rate_limit_error,
    _parse_graph_datetime,
    _raise_graph_api_error,
    _resolve_insights_start,
    _strip_access_token,
    _to_unix_timestamp,
    discover_instagram_accounts,
    instagram_source,
)

TODAY = dt.date(2026, 4, 30)

ACCOUNT = {"id": "17841400000000001", "username": "posthog", "page_name": "PostHog"}
ACCOUNT_2 = {"id": "17841400000000002", "username": "hoggy", "page_name": "Hoggy"}


@pytest.mark.parametrize(
    "url,expected",
    [
        (
            "https://graph.facebook.com/v25.0/123/media?after=abc&access_token=SECRET",
            "https://graph.facebook.com/v25.0/123/media?after=abc",
        ),
        (
            "https://graph.facebook.com/v25.0/123/media?after=abc",
            "https://graph.facebook.com/v25.0/123/media?after=abc",
        ),
    ],
)
def test_strip_access_token(url, expected):
    assert _strip_access_token(url) == expected


@pytest.mark.parametrize(
    "error,expected",
    [
        ({"code": 190}, True),
        ({"code": 102}, True),
        ({"code": 10}, True),
        ({"code": 200}, True),
        ({"code": 299}, True),
        ({"code": 4}, False),
        ({"code": 1}, False),
        ({"code": "190"}, False),
        ({}, False),
    ],
)
def test_is_permanent_auth_error(error, expected):
    assert _is_permanent_auth_error(error) is expected


@pytest.mark.parametrize(
    "error,expected",
    [
        ({"code": 4}, True),
        ({"code": 17}, True),
        ({"code": 32}, True),
        ({"code": 613}, True),
        ({"code": 190}, False),
        ({}, False),
    ],
)
def test_is_rate_limit_error(error, expected):
    assert _is_rate_limit_error(error) is expected


def _response(status_code: int, body: dict | None):
    resp = mock.MagicMock()
    resp.status_code = status_code
    resp.text = str(body)
    if body is None:
        resp.json.side_effect = ValueError("not json")
    else:
        resp.json.return_value = body
    return resp


@pytest.mark.parametrize(
    "body,expected_substring",
    [
        ({"error": {"code": 190}}, INSTAGRAM_AUTH_ERROR_MESSAGE),
        ({"error": {"code": 4}}, "rate limit reached"),
        ({"error": {"code": 1}}, "request failed"),
        (None, "request failed"),
    ],
)
def test_raise_graph_api_error(body, expected_substring):
    with pytest.raises(Exception, match=expected_substring.replace("(", "\\(")):
        _raise_graph_api_error(_response(400, body))


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("2026-04-15T10:30:00+0000", dt.datetime(2026, 4, 15, 10, 30, 0, tzinfo=dt.UTC)),
        ("not-a-date", "not-a-date"),
        (None, None),
        (42, 42),
    ],
)
def test_parse_graph_datetime(raw, expected):
    assert _parse_graph_datetime(raw) == expected


def test_flatten_media_row():
    row = {
        "id": "media_1",
        "owner": {"id": "owner_1"},
        "timestamp": "2026-04-15T10:30:00+0000",
        "like_count": 5,
    }
    out = _flatten_media_row(row, ACCOUNT)

    assert out["owner_id"] == "owner_1"
    assert "owner" not in out
    assert out["timestamp"] == dt.datetime(2026, 4, 15, 10, 30, 0, tzinfo=dt.UTC)
    assert out["account_id"] == ACCOUNT["id"]
    assert out["account_username"] == "posthog"
    assert out["like_count"] == 5


@pytest.mark.parametrize(
    "value,expected",
    [
        (dt.datetime(2026, 4, 15, 0, 0, 0, tzinfo=dt.UTC), 1776211200),
        (dt.datetime(2026, 4, 15, 0, 0, 0), 1776211200),  # naive treated as UTC
        (dt.date(2026, 4, 15), 1776211200),
        ("2026-04-15T00:00:00+00:00", 1776211200),
        ("2026-04-15T00:00:00+0000", 1776211200),
    ],
)
def test_to_unix_timestamp(value, expected):
    assert _to_unix_timestamp(value) == expected


@pytest.mark.parametrize(
    "last_value,history_days,expected",
    [
        # No last value → metric availability floor.
        (None, 365, TODAY - dt.timedelta(days=365)),
        (None, 30, TODAY - dt.timedelta(days=30)),
        # Recent last value → lookback window before it.
        (TODAY - dt.timedelta(days=5), 365, TODAY - dt.timedelta(days=5 + INSIGHTS_LOOKBACK_DAYS)),
        # Old last value → clamped to the floor.
        (TODAY - dt.timedelta(days=400), 365, TODAY - dt.timedelta(days=365)),
        # String and datetime forms are accepted.
        ("2026-04-15", 365, dt.date(2026, 4, 15) - dt.timedelta(days=INSIGHTS_LOOKBACK_DAYS)),
        (dt.datetime(2026, 4, 15, 12, 0), 365, dt.date(2026, 4, 15) - dt.timedelta(days=INSIGHTS_LOOKBACK_DAYS)),
    ],
)
def test_resolve_insights_start(last_value, history_days, expected):
    assert _resolve_insights_start(TODAY, history_days, last_value) == expected


def test_insight_values_to_rows():
    payload = {
        "data": [
            {
                "name": "reach",
                "period": "day",
                "values": [
                    {"value": 10, "end_time": "2026-04-15T07:00:00+0000"},
                    {"value": 12, "end_time": "2026-04-16T07:00:00+0000"},
                ],
            }
        ]
    }
    rows = _insight_values_to_rows(payload, ACCOUNT)

    assert len(rows) == 2
    assert rows[0]["account_id"] == ACCOUNT["id"]
    assert rows[0]["metric"] == "reach"
    assert rows[0]["period"] == "day"
    assert rows[0]["date"] == dt.date(2026, 4, 15)
    assert rows[0]["value"] == 10
    assert rows[1]["date"] == dt.date(2026, 4, 16)


def test_discover_instagram_accounts_paginates_dedupes_and_sorts(monkeypatch):
    pages = [
        {
            "data": [
                {"name": "Hoggy", "instagram_business_account": {"id": ACCOUNT_2["id"], "username": "hoggy"}},
                {"name": "No IG page"},
            ],
            "paging": {"next": "https://graph.facebook.com/v25.0/me/accounts?after=abc&access_token=SECRET"},
        },
        {
            "data": [
                {"name": "PostHog", "instagram_business_account": {"id": ACCOUNT["id"], "username": "posthog"}},
                # Duplicate page linking the same IG account.
                {"name": "PostHog Alt", "instagram_business_account": {"id": ACCOUNT["id"], "username": "posthog"}},
            ],
        },
    ]
    requested_urls: list[str] = []

    def fake_graph_get(url, params):
        requested_urls.append(url)
        return pages[len(requested_urls) - 1]

    monkeypatch.setattr(ig, "_graph_get", fake_graph_get)

    accounts = discover_instagram_accounts("token")

    assert [a["id"] for a in accounts] == [ACCOUNT["id"], ACCOUNT_2["id"]]
    assert accounts[0]["page_name"] in ("PostHog", "PostHog Alt")
    # Pagination URL is followed with the token stripped (re-attached via params).
    assert requested_urls[1] == "https://graph.facebook.com/v25.0/me/accounts?after=abc"


def _config() -> InstagramSourceConfig:
    return InstagramSourceConfig(instagram_integration_id=1)


def _setup_source(monkeypatch, accounts, resume=None):
    monkeypatch.setattr(ig, "get_access_token", lambda *a, **kw: "token")
    monkeypatch.setattr(ig, "discover_instagram_accounts", lambda token: accounts)
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume is not None
    manager.load_state.return_value = resume
    saved_states: list[InstagramResumeConfig] = []
    manager.save_state.side_effect = lambda state: saved_states.append(state)
    return manager, saved_states


def test_source_raises_when_no_accounts(monkeypatch):
    manager, _ = _setup_source(monkeypatch, [])
    response = instagram_source(config=_config(), resource_name="users", team_id=1, resumable_source_manager=manager)
    with pytest.raises(Exception, match="No Instagram professional account"):
        list(cast(Iterable[Any], response.items()))


def test_users_stream_yields_one_row_per_account(monkeypatch):
    manager, saved_states = _setup_source(monkeypatch, [ACCOUNT, ACCOUNT_2])

    def fake_graph_get(url, params):
        account_id = url.rsplit("/", 1)[-1]
        return {"id": account_id, "username": "u", "followers_count": 10}

    monkeypatch.setattr(ig, "_graph_get", fake_graph_get)

    response = instagram_source(config=_config(), resource_name="users", team_id=1, resumable_source_manager=manager)
    batches = list(cast(Iterable[Any], response.items()))

    assert len(batches) == 2
    assert batches[0][0]["id"] == ACCOUNT["id"]
    assert batches[0][0]["page_name"] == "PostHog"
    assert saved_states == []


def test_media_stream_paginates_and_saves_token_free_state(monkeypatch):
    manager, saved_states = _setup_source(monkeypatch, [ACCOUNT])

    pages = [
        {
            "data": [{"id": "m1", "timestamp": "2026-04-15T10:00:00+0000", "owner": {"id": "o1"}}],
            "paging": {"next": "https://graph.facebook.com/v25.0/123/media?after=abc&access_token=SECRET"},
        },
        {"data": [{"id": "m2", "timestamp": "2026-04-14T10:00:00+0000"}]},
    ]
    calls: list[tuple[str, dict]] = []

    def fake_graph_get(url, params):
        calls.append((url, dict(params)))
        return pages[len(calls) - 1]

    monkeypatch.setattr(ig, "_graph_get", fake_graph_get)

    response = instagram_source(config=_config(), resource_name="media", team_id=1, resumable_source_manager=manager)
    batches = list(cast(Iterable[Any], response.items()))

    assert [row["id"] for batch in batches for row in batch] == ["m1", "m2"]
    assert all(row["account_id"] == ACCOUNT["id"] for batch in batches for row in batch)
    # Second request follows the stripped paging URL with the token via params.
    assert calls[1][0] == "https://graph.facebook.com/v25.0/123/media?after=abc"
    assert calls[1][1] == {"access_token": "token"}
    # Saved states never contain the access token.
    assert saved_states[0].next_url == "https://graph.facebook.com/v25.0/123/media?after=abc"
    assert saved_states[-1].next_url is None


def test_media_stream_passes_since_for_incremental(monkeypatch):
    manager, _ = _setup_source(monkeypatch, [ACCOUNT])
    calls: list[dict] = []

    def fake_graph_get(url, params):
        calls.append(dict(params))
        return {"data": []}

    monkeypatch.setattr(ig, "_graph_get", fake_graph_get)

    response = instagram_source(
        config=_config(),
        resource_name="media",
        team_id=1,
        resumable_source_manager=manager,
        should_use_incremental_field=True,
        db_incremental_field_last_value=dt.datetime(2026, 4, 15, tzinfo=dt.UTC),
    )
    list(cast(Iterable[Any], response.items()))

    assert calls[0]["since"] == 1776211200


def test_media_stream_resumes_from_saved_cursor(monkeypatch):
    resume = InstagramResumeConfig(
        account_id=ACCOUNT_2["id"], next_url="https://graph.facebook.com/v25.0/456/media?after=xyz"
    )
    manager, _ = _setup_source(monkeypatch, [ACCOUNT, ACCOUNT_2], resume=resume)
    calls: list[str] = []

    def fake_graph_get(url, params):
        calls.append(url)
        return {"data": []}

    monkeypatch.setattr(ig, "_graph_get", fake_graph_get)

    response = instagram_source(config=_config(), resource_name="media", team_id=1, resumable_source_manager=manager)
    list(cast(Iterable[Any], response.items()))

    # The first account is skipped entirely; the second starts at the saved cursor.
    assert calls == ["https://graph.facebook.com/v25.0/456/media?after=xyz"]


def test_media_resume_ignored_when_account_gone(monkeypatch):
    resume = InstagramResumeConfig(account_id="999", next_url="https://example.com/cursor")
    manager, _ = _setup_source(monkeypatch, [ACCOUNT], resume=resume)
    calls: list[str] = []

    def fake_graph_get(url, params):
        calls.append(url)
        return {"data": []}

    monkeypatch.setattr(ig, "_graph_get", fake_graph_get)

    response = instagram_source(config=_config(), resource_name="media", team_id=1, resumable_source_manager=manager)
    list(cast(Iterable[Any], response.items()))

    assert calls == [f"{ig.GRAPH_API_BASE}/{ACCOUNT['id']}/media"]


def test_stories_stream_never_saves_resume_state(monkeypatch):
    manager, saved_states = _setup_source(monkeypatch, [ACCOUNT])
    monkeypatch.setattr(ig, "_graph_get", lambda url, params: {"data": [{"id": "s1"}]})

    response = instagram_source(config=_config(), resource_name="stories", team_id=1, resumable_source_manager=manager)
    batches = list(cast(Iterable[Any], response.items()))

    assert batches[0][0]["id"] == "s1"
    assert saved_states == []


def test_user_insights_iterates_windows_per_metric(monkeypatch):
    manager, saved_states = _setup_source(monkeypatch, [ACCOUNT])
    monkeypatch.setattr(ig, "_today", lambda: TODAY)

    calls: list[dict] = []

    def fake_graph_get(url, params):
        calls.append(dict(params))
        return {
            "data": [
                {
                    "name": params["metric"],
                    "period": "day",
                    "values": [{"value": 1, "end_time": "2026-04-29T07:00:00+0000"}],
                }
            ]
        }

    monkeypatch.setattr(ig, "_graph_get", fake_graph_get)

    response = instagram_source(
        config=_config(),
        resource_name="user_insights",
        team_id=1,
        resumable_source_manager=manager,
        should_use_incremental_field=True,
        db_incremental_field_last_value=dt.date(2026, 4, 25),
    )
    batches = list(cast(Iterable[Any], response.items()))

    # Incremental: both metrics start at last value minus the lookback → one window each.
    assert [c["metric"] for c in calls] == ["reach", "follower_count"]
    expected_since = _to_unix_timestamp(dt.date(2026, 4, 25) - dt.timedelta(days=INSIGHTS_LOOKBACK_DAYS))
    assert all(c["since"] == expected_since for c in calls)
    assert all(c["until"] == _to_unix_timestamp(TODAY) for c in calls)
    assert len(batches) == 2
    # Window state saved per metric with the next window start.
    assert [(s.metric, s.window_start) for s in saved_states] == [
        ("reach", TODAY.isoformat()),
        ("follower_count", TODAY.isoformat()),
    ]


def test_user_insights_resume_skips_completed_metrics_and_windows(monkeypatch):
    resume = InstagramResumeConfig(account_id=ACCOUNT["id"], metric="follower_count", window_start="2026-04-20")
    manager, _ = _setup_source(monkeypatch, [ACCOUNT], resume=resume)
    monkeypatch.setattr(ig, "_today", lambda: TODAY)

    calls: list[dict] = []

    def fake_graph_get(url, params):
        calls.append(dict(params))
        return {"data": []}

    monkeypatch.setattr(ig, "_graph_get", fake_graph_get)

    response = instagram_source(
        config=_config(), resource_name="user_insights", team_id=1, resumable_source_manager=manager
    )
    list(cast(Iterable[Any], response.items()))

    # `reach` was already completed before the crash; follower_count resumes at its window.
    assert all(c["metric"] == "follower_count" for c in calls)
    assert calls[0]["since"] == _to_unix_timestamp(dt.date(2026, 4, 20))


def test_user_insights_full_refresh_respects_metric_floors(monkeypatch):
    manager, _ = _setup_source(monkeypatch, [ACCOUNT])
    monkeypatch.setattr(ig, "_today", lambda: TODAY)

    calls: list[dict] = []

    def fake_graph_get(url, params):
        calls.append(dict(params))
        return {"data": []}

    monkeypatch.setattr(ig, "_graph_get", fake_graph_get)

    response = instagram_source(
        config=_config(), resource_name="user_insights", team_id=1, resumable_source_manager=manager
    )
    list(cast(Iterable[Any], response.items()))

    reach_calls = [c for c in calls if c["metric"] == "reach"]
    follower_calls = [c for c in calls if c["metric"] == "follower_count"]
    # reach backfills 365 days in 30-day windows; follower_count only the API's 30-day floor.
    assert calls[0]["since"] == _to_unix_timestamp(TODAY - dt.timedelta(days=365))
    assert len(reach_calls) == 13
    assert len(follower_calls) == 1
    assert follower_calls[0]["since"] == _to_unix_timestamp(TODAY - dt.timedelta(days=30))


@pytest.mark.parametrize(
    "resource_name,expected_pk,expected_sort,expected_partition_mode",
    [
        ("users", ["id"], "asc", None),
        ("media", ["id"], "desc", "datetime"),
        ("stories", ["id"], "desc", None),
        ("user_insights", ["account_id", "date", "metric"], "asc", "datetime"),
    ],
)
def test_source_response_metadata(resource_name, expected_pk, expected_sort, expected_partition_mode):
    response = instagram_source(
        config=_config(), resource_name=resource_name, team_id=1, resumable_source_manager=mock.MagicMock()
    )

    assert response.primary_keys == expected_pk
    assert response.sort_mode == expected_sort
    assert response.partition_mode == expected_partition_mode


def test_unknown_resource_name_raises():
    with pytest.raises(ValueError, match="Unknown Instagram schema"):
        instagram_source(
            config=_config(), resource_name="not_real", team_id=1, resumable_source_manager=mock.MagicMock()
        )


def test_get_access_token_refreshes_stale_db_connection(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(ig, "close_old_connections", lambda: calls.append("close_old_connections"))

    integration = mock.MagicMock()
    integration.kind = "instagram"
    integration.errors = ""
    integration.sensitive_config = {"access_token": "token-123"}

    def fake_get(**kw):
        calls.append("Integration.objects.get")
        return integration

    monkeypatch.setattr(ig.Integration.objects, "get", fake_get)
    monkeypatch.setattr(ig.InstagramIntegration, "refresh_access_token", lambda self: calls.append("refresh"))

    token = ig.get_access_token(integration_id=1, team_id=1)

    assert token == "token-123"
    assert calls == ["close_old_connections", "Integration.objects.get", "refresh"]
