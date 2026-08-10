import json
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any, Optional, cast

import pytest
from unittest import mock

import requests
import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.google_drive import google_drive
from products.warehouse_sources.backend.temporal.data_imports.sources.google_drive.google_drive import (
    AUTH_FAILED_ERROR_PREFIX,
    INVALID_SERVICE_ACCOUNT_KEY_ERROR,
    GoogleDriveAuth,
    GoogleDriveAuthError,
    GoogleDriveClient,
    GoogleDriveResumeConfig,
    GoogleDriveRetryableError,
    _build_initial_params,
    _error_reason,
    _fetch_page,
    _format_drive_datetime,
    _get_fan_out_rows,
    _get_top_level_rows,
    get_rows,
    google_drive_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_drive.oauth import (
    MISSING_INTEGRATION_ID_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.google_drive.settings import (
    GOOGLE_DRIVE_ENDPOINTS,
)

OAUTH_AUTH = GoogleDriveAuth(integration_id=42, team_id=7)
SERVICE_ACCOUNT_KEY = json.dumps(
    {"type": "service_account", "client_email": "sa@project.iam.gserviceaccount.com", "private_key": "-----KEY-----"}
)

LOGGER = structlog.get_logger(__name__)


class _FakeResumeManager(ResumableSourceManager[GoogleDriveResumeConfig]):
    """Stand-in for the Redis-backed manager: records saved checkpoints in memory."""

    def __init__(self, state: Optional[GoogleDriveResumeConfig] = None) -> None:
        self._state = state
        self.saved_states: list[GoogleDriveResumeConfig] = []

    def can_resume(self) -> bool:
        return self._state is not None

    def load_state(self) -> Optional[GoogleDriveResumeConfig]:
        return self._state

    def save_state(self, data: GoogleDriveResumeConfig) -> None:
        self.saved_states.append(data)

    def clear_state(self) -> None:
        self._state = None


def _response(json_body: Any, status: int = 200) -> mock.Mock:
    response = mock.Mock(spec=requests.Response)
    response.status_code = status
    response.ok = status < 400
    response.text = ""
    response.json.return_value = json_body
    if status >= 400:
        response.raise_for_status.side_effect = requests.exceptions.HTTPError(
            f"{status} Client Error: for url: https://www.googleapis.com/drive/v3/files", response=response
        )
    else:
        response.raise_for_status.return_value = None
    return response


@pytest.fixture(autouse=True)
def integration_token() -> Iterator[mock.Mock]:
    """The OAuth path reads its bearer token off the integration row, so stub that lookup for every
    test here. Tests that care about the token sequence re-patch it with their own side effect."""
    with mock.patch.object(google_drive, "resolve_google_drive_oauth_token", return_value="minted-token") as resolve:
        yield resolve


def _make_client(
    api_responses: list[Any],
    auth: GoogleDriveAuth = OAUTH_AUTH,
) -> tuple[GoogleDriveClient, mock.Mock, mock.Mock]:
    api_session = mock.Mock()
    api_session.get.side_effect = list(api_responses)
    token_session = mock.Mock()

    with mock.patch.object(google_drive, "make_tracked_session", side_effect=[api_session, token_session]):
        client = GoogleDriveClient(auth)

    return client, api_session, token_session


def _fake_client(pages: list[Any]) -> GoogleDriveClient:
    """A client whose `get` returns (or raises) the given sequence, for paginator-level tests."""
    client = mock.Mock(spec=GoogleDriveClient)
    client.get.side_effect = list(pages)
    return cast(GoogleDriveClient, client)


def _get_calls(client: GoogleDriveClient) -> list[Any]:
    return cast(Any, client).get.call_args_list


def _requested_paths(client: GoogleDriveClient) -> list[str]:
    return [call.args[0] for call in _get_calls(client)]


def _requested_params(client: GoogleDriveClient) -> list[dict[str, str]]:
    return [call.args[1] for call in _get_calls(client)]


@pytest.mark.parametrize(
    "value,expected",
    [
        (datetime(2024, 6, 1, 12, 30, 45, 123456, tzinfo=UTC), "2024-06-01T12:30:45.123Z"),
        # Naive values are read as UTC rather than local time
        (datetime(2024, 6, 1, 12, 30, 45), "2024-06-01T12:30:45.000Z"),
        (date(2024, 6, 1), "2024-06-01T00:00:00.000Z"),
        # Anything already stringified is passed through untouched
        ("2024-06-01T00:00:00Z", "2024-06-01T00:00:00Z"),
    ],
)
def test_format_drive_datetime(value: Any, expected: str) -> None:
    assert _format_drive_datetime(value) == expected


@pytest.mark.parametrize(
    "endpoint,should_use_incremental,last_value,incremental_field,expected_q,expected_order_by",
    [
        # Server-side search filter plus an ascending order on the chosen cursor field
        (
            "files",
            True,
            datetime(2024, 6, 1, tzinfo=UTC),
            "modifiedTime",
            "modifiedTime > '2024-06-01T00:00:00.000Z'",
            "modifiedTime",
        ),
        (
            "files",
            True,
            datetime(2024, 6, 1, tzinfo=UTC),
            "createdTime",
            "createdTime > '2024-06-01T00:00:00.000Z'",
            "createdTime",
        ),
        # Full walks order on the immutable createdTime so edits can't reshuffle pages
        ("files", False, datetime(2024, 6, 1, tzinfo=UTC), "modifiedTime", None, "createdTime"),
        ("files", True, None, "modifiedTime", None, "createdTime"),
        # A cursor field Drive can't filter on server-side must not become a q clause
        ("files", True, datetime(2024, 6, 1, tzinfo=UTC), "viewedByMeTime", None, "createdTime"),
        # Full-refresh endpoints take neither q nor orderBy (drives.list has no orderBy param)
        ("drives", True, datetime(2024, 6, 1, tzinfo=UTC), None, None, None),
        ("drive_permissions", True, datetime(2024, 6, 1, tzinfo=UTC), None, None, None),
    ],
)
def test_build_initial_params_incremental_behavior(
    endpoint: str,
    should_use_incremental: bool,
    last_value: Any,
    incremental_field: Optional[str],
    expected_q: Optional[str],
    expected_order_by: Optional[str],
) -> None:
    params = _build_initial_params(
        GOOGLE_DRIVE_ENDPOINTS[endpoint], should_use_incremental, last_value, incremental_field, None
    )

    assert params.get("q") == expected_q
    assert params.get("orderBy") == expected_order_by


@pytest.mark.parametrize(
    "endpoint,drive_id,expected",
    [
        # Without a drive id the files walk still has to opt into shared drive items, or it only
        # sees My Drive
        ("files", None, {"supportsAllDrives": "true", "includeItemsFromAllDrives": "true"}),
        (
            "files",
            "drive-1",
            {
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
                "corpora": "drive",
                "driveId": "drive-1",
            },
        ),
        # The drive id scopes the files table only; it must not leak into the other endpoints
        ("drives", "drive-1", {}),
        ("drive_permissions", "drive-1", {"supportsAllDrives": "true"}),
    ],
)
def test_build_initial_params_drive_scoping(endpoint: str, drive_id: Optional[str], expected: dict[str, str]) -> None:
    params = _build_initial_params(GOOGLE_DRIVE_ENDPOINTS[endpoint], False, None, None, drive_id)

    scope_keys = {"supportsAllDrives", "includeItemsFromAllDrives", "corpora", "driveId"}
    assert {key: value for key, value in params.items() if key in scope_keys} == expected


@pytest.mark.parametrize("endpoint", sorted(GOOGLE_DRIVE_ENDPOINTS))
def test_build_initial_params_always_requests_page_size_and_fields(endpoint: str) -> None:
    config = GOOGLE_DRIVE_ENDPOINTS[endpoint]
    params = _build_initial_params(config, False, None, None, None)

    assert params["pageSize"] == str(config.page_size)
    # A partial-response selection is mandatory: without it Drive returns only id/name/mimeType
    assert params["fields"].startswith(f"nextPageToken,{config.data_path}(")
    assert "id" in params["fields"]


@pytest.mark.parametrize(
    "body,expected",
    [
        ({"error": {"errors": [{"reason": "rateLimitExceeded"}]}}, "ratelimitexceeded"),
        ({"error": {"errors": [{"reason": "insufficientFilePermissions"}]}}, "insufficientfilepermissions"),
        # Newer style envelopes only carry `status`
        ({"error": {"status": "PERMISSION_DENIED"}}, "permission_denied"),
        ({"error": {}}, ""),
        ({}, ""),
        ("not json at all", ""),
    ],
)
def test_error_reason_extraction(body: Any, expected: str) -> None:
    assert _error_reason(_response(body, status=403)) == expected


def test_error_reason_survives_a_non_json_body() -> None:
    response = mock.Mock(spec=requests.Response)
    response.json.side_effect = ValueError("no json")
    assert _error_reason(response) == ""


def test_the_integration_token_is_read_once_and_reused(integration_token: mock.Mock) -> None:
    client, api_session, _ = _make_client([_response({"files": []}), _response({"files": []})])

    client.get("/files", {})
    client.get("/files", {})

    # One row lookup serves both requests
    assert integration_token.call_count == 1
    assert integration_token.call_args.args == (42, 7)
    assert api_session.get.call_args.kwargs["headers"]["Authorization"] == "Bearer minted-token"


def test_a_401_re_reads_the_token_once_and_retries(integration_token: mock.Mock) -> None:
    # A cached token can be invalidated before its stated expiry, so the retry asks the row for a
    # freshly refreshed one rather than replaying the same bearer.
    integration_token.side_effect = ["stale", "fresh"]
    client, api_session, _ = _make_client([_response({}, status=401), _response({"files": [{"id": "f1"}]})])

    assert client.get("/files", {}) == {"files": [{"id": "f1"}]}
    assert [call.kwargs["force_refresh"] for call in integration_token.call_args_list] == [False, True]
    authorizations = [call.kwargs["headers"]["Authorization"] for call in api_session.get.call_args_list]
    assert authorizations == ["Bearer stale", "Bearer fresh"]


def test_a_persistent_401_is_raised_after_one_re_read(integration_token: mock.Mock) -> None:
    integration_token.side_effect = ["a", "b"]
    client, api_session, _ = _make_client([_response({}, status=401), _response({}, status=401)])

    with pytest.raises(requests.exceptions.HTTPError):
        client.get("/files", {})

    assert api_session.get.call_count == 2


@pytest.mark.parametrize(
    "reason,expected_error",
    [
        # Drive reports quota exhaustion as a 403, which the transport's status retries never see
        ("userRateLimitExceeded", GoogleDriveRetryableError),
        ("rateLimitExceeded", GoogleDriveRetryableError),
        ("quotaExceeded", GoogleDriveRetryableError),
        # Every other 403 is permanent: a missing scope or no access to the item
        ("insufficientFilePermissions", requests.exceptions.HTTPError),
        ("accessNotConfigured", requests.exceptions.HTTPError),
    ],
)
def test_403_reasons_are_classified_as_retryable_or_permanent(reason: str, expected_error: type[Exception]) -> None:
    client, _, _ = _make_client([_response({"error": {"errors": [{"reason": reason}]}}, status=403)])

    with pytest.raises(expected_error):
        client.get("/files", {})


def test_rate_limited_pages_are_retried_then_succeed() -> None:
    client = _fake_client(
        [
            GoogleDriveRetryableError("Google Drive rate limit (retryable)"),
            {"files": [{"id": "f1"}]},
        ]
    )

    with mock.patch("tenacity.nap.time.sleep"):
        assert _fetch_page(client, "/files", {}) == {"files": [{"id": "f1"}]}

    assert len(_get_calls(client)) == 2


@pytest.mark.parametrize(
    "raw_key,expected_message",
    [
        ("not-json", INVALID_SERVICE_ACCOUNT_KEY_ERROR),
        (json.dumps({"client_email": "a@b.c"}), INVALID_SERVICE_ACCOUNT_KEY_ERROR),
        (json.dumps({"private_key": "k"}), INVALID_SERVICE_ACCOUNT_KEY_ERROR),
        (json.dumps(["not", "an", "object"]), INVALID_SERVICE_ACCOUNT_KEY_ERROR),
    ],
)
def test_a_malformed_service_account_key_fails_before_any_request(raw_key: str, expected_message: str) -> None:
    with mock.patch.object(google_drive, "make_tracked_session") as make_session:
        with pytest.raises(GoogleDriveAuthError, match=expected_message):
            GoogleDriveClient(GoogleDriveAuth(service_account_key=raw_key))

    make_session.assert_not_called()


def test_service_account_tokens_are_minted_through_google_auth() -> None:
    credentials = mock.Mock()
    credentials.token = "sa-token"
    credentials.expiry = datetime(2099, 1, 1, 12, 0, 0)

    api_session = mock.Mock()
    api_session.get.side_effect = [_response({"files": []})]

    with mock.patch.object(google_drive, "make_tracked_session", side_effect=[api_session, mock.Mock()]):
        with mock.patch.object(
            google_drive.service_account.Credentials, "from_service_account_info", return_value=credentials
        ) as from_info:
            client = GoogleDriveClient(
                GoogleDriveAuth(service_account_key=SERVICE_ACCOUNT_KEY, impersonated_user_email="user@example.com")
            )
            client.get("/files", {})

    assert from_info.call_args.kwargs["subject"] == "user@example.com"
    assert from_info.call_args.kwargs["scopes"] == list(google_drive.DRIVE_READONLY_SCOPES)
    credentials.refresh.assert_called_once()
    assert api_session.get.call_args.kwargs["headers"]["Authorization"] == "Bearer sa-token"


def test_service_account_impersonation_is_omitted_when_unset() -> None:
    credentials = mock.Mock()
    credentials.token = "sa-token"
    credentials.expiry = None

    with mock.patch.object(google_drive, "make_tracked_session", side_effect=[mock.Mock(), mock.Mock()]):
        with mock.patch.object(
            google_drive.service_account.Credentials, "from_service_account_info", return_value=credentials
        ) as from_info:
            client = GoogleDriveClient(GoogleDriveAuth(service_account_key=SERVICE_ACCOUNT_KEY))
            assert client.access_token() == "sa-token"

    assert from_info.call_args.kwargs["subject"] is None


@pytest.mark.parametrize(
    "auth",
    [
        GoogleDriveAuth(),
        GoogleDriveAuth(integration_id=42),
        GoogleDriveAuth(team_id=7),
    ],
)
def test_an_unreferenced_integration_fails_without_a_lookup(
    auth: GoogleDriveAuth, integration_token: mock.Mock
) -> None:
    client, _, _ = _make_client([], auth=auth)

    with pytest.raises(GoogleDriveAuthError, match=MISSING_INTEGRATION_ID_ERROR):
        client.access_token()

    integration_token.assert_not_called()


def test_a_missing_integration_row_becomes_an_auth_error(integration_token: mock.Mock) -> None:
    # The row is gone (integration deleted, or moved to another team), which no retry can fix.
    integration_token.side_effect = ValueError("Integration not found: 42")
    client, _, _ = _make_client([])

    with pytest.raises(GoogleDriveAuthError, match="Integration not found: 42"):
        client.access_token()


def test_a_service_account_that_mints_no_token_is_an_auth_error() -> None:
    credentials = mock.Mock()
    credentials.token = None

    with mock.patch.object(google_drive, "make_tracked_session", side_effect=[mock.Mock(), mock.Mock()]):
        with mock.patch.object(
            google_drive.service_account.Credentials, "from_service_account_info", return_value=credentials
        ):
            client = GoogleDriveClient(GoogleDriveAuth(service_account_key=SERVICE_ACCOUNT_KEY))

            with pytest.raises(GoogleDriveAuthError, match=AUTH_FAILED_ERROR_PREFIX):
                client.access_token()


def test_secret_values_are_registered_for_redaction() -> None:
    with mock.patch.object(google_drive, "make_tracked_session") as make_session:
        make_session.return_value = mock.Mock()
        GoogleDriveClient(GoogleDriveAuth(service_account_key=SERVICE_ACCOUNT_KEY))

    for call in make_session.call_args_list:
        assert "-----KEY-----" in call.kwargs["redact_values"]
    # Neither session may capture HTTP samples: the token exchange body is the bearer token, and the
    # Drive API responses carry tenant file names, owner/sharing identities, and permission emails
    # the name-based scrubbers can't recognise. Both must stay out of the shared sample prefix.
    api_call, token_call = make_session.call_args_list
    assert api_call.kwargs["capture"] is False
    assert token_call.kwargs["capture"] is False


def test_a_caller_supplied_token_uri_is_overridden() -> None:
    # google-auth calls token_uri during credential refresh, so honoring a submitted one would let a
    # malicious key point the worker at an internal host (SSRF). It must be pinned to Google's.
    raw_key = json.dumps(
        {
            "client_email": "sa@project.iam.gserviceaccount.com",
            "private_key": "-----KEY-----",
            "token_uri": "http://169.254.169.254/",
        }
    )
    info = google_drive._parse_service_account_key(raw_key)
    assert info["token_uri"] == google_drive.GOOGLE_TOKEN_URL


def test_top_level_pagination_follows_page_tokens_and_terminates() -> None:
    client = _fake_client(
        [
            {"files": [{"id": "f1"}], "nextPageToken": "p2"},
            {"files": [{"id": "f2"}], "nextPageToken": "p3"},
            {"files": [{"id": "f3"}]},
        ]
    )
    manager = _FakeResumeManager()

    batches = list(_get_top_level_rows(client, GOOGLE_DRIVE_ENDPOINTS["files"], {"pageSize": "1000"}, manager, LOGGER))

    assert [[row["id"] for row in batch] for batch in batches] == [["f1"], ["f2"], ["f3"]]
    assert [params.get("pageToken") for params in _requested_params(client)] == [None, "p2", "p3"]
    # State is saved after each yielded page while pages remain, and never for the final page —
    # otherwise the next attempt would resume past the end of the list.
    assert [state.page_token for state in manager.saved_states] == ["p2", "p3"]


def test_top_level_pagination_resumes_from_the_saved_page_token() -> None:
    client = _fake_client([{"files": [{"id": "f9"}]}])
    manager = _FakeResumeManager(GoogleDriveResumeConfig(page_token="saved-token"))

    batches = list(_get_top_level_rows(client, GOOGLE_DRIVE_ENDPOINTS["files"], {}, manager, LOGGER))

    assert [row["id"] for row in batches[0]] == ["f9"]
    assert _requested_params(client)[0]["pageToken"] == "saved-token"


@pytest.mark.parametrize(
    "page",
    [
        {"files": []},
        {},
        # A malformed payload must terminate cleanly rather than loop or raise
        {"files": "not-a-list"},
    ],
)
def test_top_level_pagination_stops_on_an_empty_or_malformed_page(page: dict[str, Any]) -> None:
    client = _fake_client([page])
    manager = _FakeResumeManager()

    assert list(_get_top_level_rows(client, GOOGLE_DRIVE_ENDPOINTS["files"], {}, manager, LOGGER)) == []
    assert manager.saved_states == []


def test_an_empty_page_with_a_next_token_keeps_walking() -> None:
    # Drive can return an empty page mid-walk (every item on it filtered out by `q`), so an empty
    # page must not be mistaken for the end of the list.
    client = _fake_client([{"files": [], "nextPageToken": "p2"}, {"files": [{"id": "f1"}]}])
    manager = _FakeResumeManager()

    batches = list(_get_top_level_rows(client, GOOGLE_DRIVE_ENDPOINTS["files"], {}, manager, LOGGER))

    assert [[row["id"] for row in batch] for batch in batches] == [["f1"]]
    assert len(_get_calls(client)) == 2


def test_fan_out_injects_the_parent_drive_into_every_permission_row() -> None:
    client = _fake_client(
        [
            {"drives": [{"id": "d1", "name": "Engineering"}, {"id": "d2", "name": "Sales"}]},
            {"permissions": [{"id": "perm-1", "role": "organizer"}]},
            {"permissions": [{"id": "perm-1", "role": "reader"}]},
        ]
    )
    manager = _FakeResumeManager()

    batches = list(_get_fan_out_rows(client, GOOGLE_DRIVE_ENDPOINTS["drive_permissions"], {}, manager, LOGGER))

    rows = [row for batch in batches for row in batch]
    # Permission ids repeat across drives, so the parent drive is what keeps the key unique
    assert [(row["drive_id"], row["drive_name"], row["id"]) for row in rows] == [
        ("d1", "Engineering", "perm-1"),
        ("d2", "Sales", "perm-1"),
    ]
    assert _requested_paths(client) == ["/drives", "/files/d1/permissions", "/files/d2/permissions"]


def test_fan_out_bookmarks_the_next_drive_between_drives() -> None:
    client = _fake_client(
        [
            {"drives": [{"id": "d1", "name": "One"}, {"id": "d2", "name": "Two"}]},
            {"permissions": [{"id": "p1"}]},
            {"permissions": [{"id": "p2"}]},
        ]
    )
    manager = _FakeResumeManager()

    list(_get_fan_out_rows(client, GOOGLE_DRIVE_ENDPOINTS["drive_permissions"], {}, manager, LOGGER))

    assert [(state.drive_id, state.page_token) for state in manager.saved_states] == [("d2", None)]


def test_fan_out_resumes_from_the_bookmarked_drive_and_page() -> None:
    client = _fake_client(
        [
            {"drives": [{"id": "d1"}, {"id": "d2"}, {"id": "d3"}]},
            {"permissions": [{"id": "p2"}]},
            {"permissions": [{"id": "p3"}]},
        ]
    )
    manager = _FakeResumeManager(GoogleDriveResumeConfig(page_token="mid-list", drive_id="d2"))

    list(_get_fan_out_rows(client, GOOGLE_DRIVE_ENDPOINTS["drive_permissions"], {}, manager, LOGGER))

    # d1 is already done; d2 picks up mid-list and d3 starts from its first page
    assert _requested_paths(client) == ["/drives", "/files/d2/permissions", "/files/d3/permissions"]
    assert [params.get("pageToken") for params in _requested_params(client)[1:]] == ["mid-list", None]


def test_fan_out_restarts_when_the_bookmarked_drive_is_gone() -> None:
    client = _fake_client([{"drives": [{"id": "d1"}]}, {"permissions": [{"id": "p1"}]}])
    manager = _FakeResumeManager(GoogleDriveResumeConfig(page_token="mid-list", drive_id="deleted-drive"))

    list(_get_fan_out_rows(client, GOOGLE_DRIVE_ENDPOINTS["drive_permissions"], {}, manager, LOGGER))

    # The stale page token must not be replayed against a different drive
    assert _requested_params(client)[1].get("pageToken") is None


@pytest.mark.parametrize("status", [403, 404])
def test_fan_out_skips_a_drive_it_cannot_read(status: int) -> None:
    unreadable = requests.exceptions.HTTPError("error", response=_response({}, status=status))
    client = _fake_client(
        [
            {"drives": [{"id": "d1"}, {"id": "d2"}]},
            unreadable,
            {"permissions": [{"id": "p1"}]},
        ]
    )
    manager = _FakeResumeManager()

    batches = list(_get_fan_out_rows(client, GOOGLE_DRIVE_ENDPOINTS["drive_permissions"], {}, manager, LOGGER))

    assert [row["drive_id"] for batch in batches for row in batch] == ["d2"]


def test_fan_out_reraises_unexpected_http_errors() -> None:
    fatal = requests.exceptions.HTTPError("error", response=_response({}, status=500))
    client = _fake_client([{"drives": [{"id": "d1"}]}, fatal])
    manager = _FakeResumeManager()

    with pytest.raises(requests.exceptions.HTTPError):
        list(_get_fan_out_rows(client, GOOGLE_DRIVE_ENDPOINTS["drive_permissions"], {}, manager, LOGGER))


def test_shared_drive_enumeration_pages_before_fanning_out() -> None:
    client = _fake_client(
        [
            {"drives": [{"id": "d1"}], "nextPageToken": "next"},
            {"drives": [{"id": "d2"}, {"no": "id"}]},
            {"permissions": []},
            {"permissions": []},
        ]
    )
    manager = _FakeResumeManager()

    list(_get_fan_out_rows(client, GOOGLE_DRIVE_ENDPOINTS["drive_permissions"], {}, manager, LOGGER))

    # Drives without an id can't be addressed, so they're dropped rather than requested
    assert _requested_paths(client) == ["/drives", "/drives", "/files/d1/permissions", "/files/d2/permissions"]


def test_get_rows_builds_the_client_from_the_resolved_api_version() -> None:
    client = _fake_client([{"files": [{"id": "f1"}]}])
    manager = _FakeResumeManager()

    with mock.patch.object(google_drive, "GoogleDriveClient", return_value=client) as client_class:
        batches = list(
            get_rows(
                auth=OAUTH_AUTH,
                endpoint="files",
                api_version="v3",
                source_logger=LOGGER,
                resumable_source_manager=manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 6, 1, tzinfo=UTC),
                incremental_field="modifiedTime",
            )
        )

    assert client_class.call_args.args[1] == "v3"
    assert [row["id"] for batch in batches for row in batch] == ["f1"]
    assert _requested_params(client)[0]["q"] == "modifiedTime > '2024-06-01T00:00:00.000Z'"


@pytest.mark.parametrize(
    "endpoint,expected_primary_keys,expected_partition_keys",
    [
        ("files", ["id"], ["createdTime"]),
        ("drives", ["id"], None),
        # Permission ids only repeat, so the parent drive is part of the key
        ("drive_permissions", ["drive_id", "id"], None),
    ],
)
def test_source_response_shape(
    endpoint: str, expected_primary_keys: list[str], expected_partition_keys: Optional[list[str]]
) -> None:
    response = google_drive_source(
        auth=OAUTH_AUTH,
        endpoint=endpoint,
        api_version="v3",
        source_logger=LOGGER,
        resumable_source_manager=_FakeResumeManager(),
    )

    assert response.name == endpoint
    assert response.primary_keys == expected_primary_keys
    assert response.partition_keys == expected_partition_keys
    # Files are requested in ascending cursor order, so per-batch watermark checkpointing is safe
    assert response.sort_mode == "asc"


def test_validate_credentials_probes_about() -> None:
    client, api_session, _ = _make_client([_response({"user": {"emailAddress": "a@b.c"}})])

    with mock.patch.object(google_drive, "GoogleDriveClient", return_value=client):
        assert validate_credentials(OAUTH_AUTH) == (True, None)

    assert api_session.get.call_args.args[0] == "https://www.googleapis.com/drive/v3/about"


@pytest.mark.parametrize(
    "status,body,expected_fragment",
    [
        (401, {}, "rejected these credentials"),
        (403, {"error": {"errors": [{"reason": "accessNotConfigured"}]}}, "not enabled"),
        (403, {"error": {"errors": [{"reason": "insufficientPermissions"}]}}, "drive.readonly"),
        (404, {}, "status 404"),
    ],
)
def test_validate_credentials_maps_http_failures(status: int, body: Any, expected_fragment: str) -> None:
    # A 401 re-reads the token and retries once, so both paths need a second canned response
    client, _, _ = _make_client([_response(body, status=status), _response(body, status=status)])

    with mock.patch.object(google_drive, "GoogleDriveClient", return_value=client):
        valid, message = validate_credentials(OAUTH_AUTH)

    assert valid is False
    assert expected_fragment in cast(str, message)


def test_validate_credentials_reports_auth_errors_verbatim() -> None:
    with mock.patch.object(
        google_drive, "GoogleDriveClient", side_effect=GoogleDriveAuthError(INVALID_SERVICE_ACCOUNT_KEY_ERROR)
    ):
        assert validate_credentials(GoogleDriveAuth(service_account_key="bad")) == (
            False,
            INVALID_SERVICE_ACCOUNT_KEY_ERROR,
        )


def test_validate_credentials_reports_network_failures() -> None:
    client, _, _ = _make_client([requests.exceptions.ConnectionError("boom")])

    with mock.patch.object(google_drive, "GoogleDriveClient", return_value=client):
        valid, message = validate_credentials(OAUTH_AUTH)

    assert valid is False
    assert "boom" in cast(str, message)
