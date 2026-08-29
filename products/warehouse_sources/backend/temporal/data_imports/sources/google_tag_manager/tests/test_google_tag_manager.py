from typing import Any, Optional

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googletagmanager import (
    GoogleTagManagerSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_tag_manager.google_tag_manager import (
    GTM_API_BASE,
    MAX_TRANSIENT_RETRIES,
    TRANSIENT_BACKOFF_BASE_SECONDS,
    GoogleTagManagerQuotaExceededError,
    RequestThrottle,
    _backoff_seconds,
    _is_quota_error,
    _list_page,
    get_accessible_account_ids,
    google_tag_manager_source,
    parse_account_ids,
)

SESSION_PATCH_TARGET = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.google_tag_manager.google_tag_manager"
    ".google_tag_manager_session"
)


def _config(account_ids: Optional[str] = None) -> GoogleTagManagerSourceConfig:
    return GoogleTagManagerSourceConfig(google_tag_manager_integration_id=1, account_ids=account_ids)


def _response(status_code: int = 200, json_body: Any = None, headers: dict[str, str] | None = None) -> mock.MagicMock:
    response = mock.MagicMock(spec=requests.Response)
    response.status_code = status_code
    response.ok = status_code < 400
    response.headers = headers or {}
    response.text = ""
    if json_body is None:
        response.json.side_effect = ValueError("no body")
    else:
        response.json.return_value = json_body
    if status_code >= 400:
        kind = "Client" if status_code < 500 else "Server"
        response.raise_for_status.side_effect = requests.HTTPError(
            f"{status_code} {kind} Error: for url: {GTM_API_BASE}", response=response
        )
    else:
        response.raise_for_status.return_value = None
    return response


def _fake_session(pages: dict[tuple[str, str | None], dict[str, Any]]) -> mock.MagicMock:
    """Session whose GET is routed by (path under the API base, pageToken); records every call."""
    session = mock.MagicMock()
    calls: list[tuple[str, dict[str, str]]] = []

    def get(url: str, params: dict[str, str] | None = None) -> mock.MagicMock:
        query = dict(params or {})
        path = url.removeprefix(f"{GTM_API_BASE}/")
        calls.append((path, query))
        return _response(200, pages[(path, query.get("pageToken"))])

    session.get.side_effect = get
    session.calls = calls
    return session


def _null_throttle() -> RequestThrottle:
    return RequestThrottle(interval_seconds=0)


def _rows(source: Any) -> list[dict[str, Any]]:
    return [row for page in source.items() for row in page]


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, None),
        ("", None),
        (" , ,", None),
        ("123", {"123"}),
        ("123, 456", {"123", "456"}),
        (" 123 ,,456 ,", {"123", "456"}),
    ],
)
def test_parse_account_ids(raw, expected):
    assert parse_account_ids(raw) == expected


@pytest.mark.parametrize(
    "response,expected",
    [
        # 429 is always quota, body or not.
        (_response(429), True),
        # Legacy 403 quota shapes carry a reason under error.errors.
        (_response(403, {"error": {"errors": [{"reason": "quotaExceeded"}]}}), True),
        (_response(403, {"error": {"errors": [{"reason": "rateLimitExceeded"}]}}), True),
        (_response(403, {"error": {"errors": [{"reason": "userRateLimitExceeded"}]}}), True),
        (_response(403, {"error": {"errors": [{"reason": "dailyLimitExceeded"}]}}), True),
        # Newer error shape signals quota via error.status.
        (_response(403, {"error": {"status": "RESOURCE_EXHAUSTED"}}), True),
        # Permission 403s must not be treated as quota, whatever the body looks like.
        (_response(403, {"error": {"errors": [{"reason": "insufficientPermissions"}]}}), False),
        (_response(403, {"error": "forbidden"}), False),
        (_response(403), False),
        (_response(500), False),
    ],
)
def test_is_quota_error(response, expected):
    assert _is_quota_error(response) is expected


@pytest.mark.parametrize(
    "headers,attempt,expected",
    [
        ({"Retry-After": "7"}, 0, 7.0),
        ({"Retry-After": "soon"}, 1, TRANSIENT_BACKOFF_BASE_SECONDS * 2),
        ({}, 0, TRANSIENT_BACKOFF_BASE_SECONDS),
        ({}, 2, TRANSIENT_BACKOFF_BASE_SECONDS * 4),
    ],
)
def test_backoff_seconds(headers, attempt, expected):
    assert _backoff_seconds(_response(429, headers=headers), attempt) == expected


def test_list_page_retries_quota_then_returns_payload():
    session = mock.MagicMock()
    session.get.side_effect = [_response(429), _response(200, {"account": [{"accountId": "1"}]})]

    with mock.patch("time.sleep") as sleep:
        payload = _list_page(session, _null_throttle(), f"{GTM_API_BASE}/accounts", {})

    assert payload == {"account": [{"accountId": "1"}]}
    assert session.get.call_count == 2
    assert sleep.call_count == 1


def test_list_page_exhausted_quota_raises_retryable_error():
    quota_body = {"error": {"errors": [{"reason": "quotaExceeded"}]}}
    session = mock.MagicMock()
    session.get.side_effect = [_response(403, quota_body) for _ in range(MAX_TRANSIENT_RETRIES + 1)]

    with mock.patch("time.sleep"), pytest.raises(GoogleTagManagerQuotaExceededError, match=r"\(retryable\)"):
        _list_page(session, _null_throttle(), f"{GTM_API_BASE}/accounts", {})

    assert session.get.call_count == MAX_TRANSIENT_RETRIES + 1


def test_list_page_permission_403_raises_without_retry():
    session = mock.MagicMock()
    session.get.side_effect = [_response(403, {"error": {"errors": [{"reason": "insufficientPermissions"}]}})]

    with pytest.raises(requests.HTTPError, match="403 Client Error"):
        _list_page(session, _null_throttle(), f"{GTM_API_BASE}/accounts", {})

    assert session.get.call_count == 1


def test_list_page_server_error_exhausts_to_http_error():
    session = mock.MagicMock()
    session.get.side_effect = [_response(503) for _ in range(MAX_TRANSIENT_RETRIES + 1)]

    with mock.patch("time.sleep"), pytest.raises(requests.HTTPError, match="503 Server Error"):
        _list_page(session, _null_throttle(), f"{GTM_API_BASE}/accounts", {})

    assert session.get.call_count == MAX_TRANSIENT_RETRIES + 1


def test_accounts_pagination_follows_next_page_token():
    pages: dict[tuple[str, str | None], dict[str, Any]] = {
        ("accounts", None): {"account": [{"accountId": "1", "path": "accounts/1"}], "nextPageToken": "t1"},
        ("accounts", "t1"): {"account": [{"accountId": "2", "path": "accounts/2"}]},
    }
    session = _fake_session(pages)

    with mock.patch(SESSION_PATCH_TARGET, return_value=session):
        source = google_tag_manager_source(_config(), "accounts", refresh_token="rt")
        rows = _rows(source)

    assert [row["accountId"] for row in rows] == ["1", "2"]
    assert session.calls[1][1]["pageToken"] == "t1"


def test_accounts_rows_respect_account_filter():
    pages: dict[tuple[str, str | None], dict[str, Any]] = {
        ("accounts", None): {
            "account": [
                {"accountId": "1", "path": "accounts/1"},
                {"accountId": "2", "path": "accounts/2"},
            ]
        },
    }

    with mock.patch(SESSION_PATCH_TARGET, return_value=_fake_session(pages)):
        source = google_tag_manager_source(_config(account_ids="2"), "accounts", refresh_token="rt")
        rows = _rows(source)

    assert [row["accountId"] for row in rows] == ["2"]


def test_tags_fan_out_walks_every_workspace():
    pages: dict[tuple[str, str | None], dict[str, Any]] = {
        ("accounts", None): {"account": [{"accountId": "1", "path": "accounts/1"}]},
        ("accounts/1/containers", None): {
            "container": [
                {"containerId": "10", "path": "accounts/1/containers/10"},
                {"containerId": "11", "path": "accounts/1/containers/11"},
            ]
        },
        ("accounts/1/containers/10/workspaces", None): {
            "workspace": [{"workspaceId": "100", "path": "accounts/1/containers/10/workspaces/100"}]
        },
        ("accounts/1/containers/11/workspaces", None): {
            "workspace": [{"workspaceId": "110", "path": "accounts/1/containers/11/workspaces/110"}]
        },
        ("accounts/1/containers/10/workspaces/100/tags", None): {
            "tag": [{"tagId": "5", "path": "accounts/1/containers/10/workspaces/100/tags/5"}]
        },
        ("accounts/1/containers/11/workspaces/110/tags", None): {
            "tag": [{"tagId": "6", "path": "accounts/1/containers/11/workspaces/110/tags/6"}]
        },
    }
    session = _fake_session(pages)

    with mock.patch(SESSION_PATCH_TARGET, return_value=session):
        source = google_tag_manager_source(_config(), "tags", refresh_token="rt")
        rows = _rows(source)

    assert [row["path"] for row in rows] == [
        "accounts/1/containers/10/workspaces/100/tags/5",
        "accounts/1/containers/11/workspaces/110/tags/6",
    ]


def test_fan_out_skips_accounts_outside_filter():
    pages: dict[tuple[str, str | None], dict[str, Any]] = {
        ("accounts", None): {
            "account": [
                {"accountId": "1", "path": "accounts/1"},
                {"accountId": "2", "path": "accounts/2"},
            ]
        },
        ("accounts/1/containers", None): {"container": [{"containerId": "10", "path": "accounts/1/containers/10"}]},
    }
    session = _fake_session(pages)

    with mock.patch(SESSION_PATCH_TARGET, return_value=session):
        source = google_tag_manager_source(_config(account_ids="1"), "containers", refresh_token="rt")
        rows = _rows(source)

    assert [row["containerId"] for row in rows] == ["10"]
    assert all(not path.startswith("accounts/2") for path, _ in session.calls)


def test_container_versions_request_includes_deleted_param():
    pages: dict[tuple[str, str | None], dict[str, Any]] = {
        ("accounts", None): {"account": [{"accountId": "1", "path": "accounts/1"}]},
        ("accounts/1/containers", None): {"container": [{"containerId": "10", "path": "accounts/1/containers/10"}]},
        ("accounts/1/containers/10/version_headers", None): {
            "containerVersionHeader": [
                {"containerVersionId": "3", "path": "accounts/1/containers/10/versions/3", "deleted": True}
            ]
        },
    }
    session = _fake_session(pages)

    with mock.patch(SESSION_PATCH_TARGET, return_value=session):
        source = google_tag_manager_source(_config(), "container_versions", refresh_token="rt")
        rows = _rows(source)

    assert [row["containerVersionId"] for row in rows] == ["3"]
    version_call = next(call for call in session.calls if call[0].endswith("version_headers"))
    assert version_call[1]["includeDeleted"] == "true"


def test_account_probe_walks_pages_until_filter_ids_found():
    pages: dict[tuple[str, str | None], dict[str, Any]] = {
        ("accounts", None): {"account": [{"accountId": "1"}], "nextPageToken": "t1"},
        ("accounts", "t1"): {"account": [{"accountId": "3"}], "nextPageToken": "t2"},
    }
    session = _fake_session(pages)

    ids, listed_all = get_accessible_account_ids(session, required_ids={"3"})

    assert ids == {"1", "3"}
    # Early exit on the found ID leaves page t2 unfetched, so the listing is not exhaustive.
    assert listed_all is False
    assert len(session.calls) == 2


def test_account_probe_reports_exhaustive_listing():
    pages: dict[tuple[str, str | None], dict[str, Any]] = {
        ("accounts", None): {"account": [{"accountId": "1"}], "nextPageToken": "t1"},
        ("accounts", "t1"): {"account": [{"accountId": "2"}]},
    }

    ids, listed_all = get_accessible_account_ids(_fake_session(pages), required_ids={"9"})

    assert ids == {"1", "2"}
    assert listed_all is True


def test_account_probe_stops_after_first_page_without_filter():
    pages: dict[tuple[str, str | None], dict[str, Any]] = {
        ("accounts", None): {"account": [{"accountId": "1"}], "nextPageToken": "t1"},
    }
    session = _fake_session(pages)

    ids, listed_all = get_accessible_account_ids(session, required_ids=None)

    assert ids == {"1"}
    assert listed_all is False
    assert len(session.calls) == 1


def test_account_probe_respects_page_cap():
    pages: dict[tuple[str, str | None], dict[str, Any]] = {
        ("accounts", None): {"account": [{"accountId": "1"}], "nextPageToken": "t1"},
        ("accounts", "t1"): {"account": [{"accountId": "2"}], "nextPageToken": "t2"},
    }
    session = _fake_session(pages)

    ids, listed_all = get_accessible_account_ids(session, required_ids={"9"}, max_pages=2)

    assert ids == {"1", "2"}
    assert listed_all is False
    assert len(session.calls) == 2


def test_source_response_primary_key_is_path():
    source = google_tag_manager_source(_config(), "tags", refresh_token="rt")
    assert source.name == "tags"
    assert source.primary_keys == ["path"]


def test_unknown_schema_raises():
    with pytest.raises(ValueError, match="Unknown Google Tag Manager schema"):
        google_tag_manager_source(_config(), "nonexistent", refresh_token="rt")


def test_request_throttle_spaces_requests():
    throttle = RequestThrottle(interval_seconds=4.5)

    with (
        mock.patch("time.monotonic", side_effect=[100.0, 100.1, 100.1]),
        mock.patch("time.sleep") as sleep,
    ):
        throttle.wait()
        throttle.wait()

    sleep.assert_called_once()
    assert sleep.call_args[0][0] == pytest.approx(4.4)
