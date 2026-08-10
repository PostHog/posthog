import json
import contextlib
from collections.abc import Iterator
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.dropbox.dropbox import (
    CHECK_USER_QUERY,
    DropboxClient,
    DropboxCredentials,
    DropboxCursorReset,
    DropboxResumeConfig,
    check_endpoint_access,
    dropbox_source,
    format_time,
    get_rows,
    normalize_folder_path,
    normalize_row,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dropbox.settings import (
    DROPBOX_ENDPOINTS,
    ENDPOINTS,
    EVENT_ID_FIELD,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.dropbox.dropbox"

CREDENTIALS = DropboxCredentials(access_token="access-1")


class FakeResumeManager(ResumableSourceManager[DropboxResumeConfig]):
    """In-memory stand-in for the Redis-backed manager."""

    def __init__(self, state: DropboxResumeConfig | None = None) -> None:
        self.state = state
        self.saved: list[DropboxResumeConfig] = []
        self.clear_count = 0

    def can_resume(self) -> bool:
        return self.state is not None

    def load_state(self) -> DropboxResumeConfig | None:
        return self.state

    def save_state(self, data: DropboxResumeConfig) -> None:
        self.saved.append(data)

    def clear_state(self) -> None:
        self.clear_count += 1
        self.state = None


def _response(body: Any = None, status: int = 200) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status
    response.ok = status < 400
    response.text = json.dumps(body) if body is not None else ""
    response.json.return_value = {} if body is None else body
    if status >= 400:
        response.raise_for_status.side_effect = HTTPError(
            f"{status} Client Error: for url: https://api.dropboxapi.com/2/files/list_folder", response=response
        )
    return response


@contextlib.contextmanager
def patched_session(api_responses: list[Any] | None = None) -> Iterator[mock.MagicMock]:
    """Patch the session `DropboxClient` builds."""
    api_session = mock.MagicMock()
    if api_responses is not None:
        api_session.post.side_effect = api_responses
    with mock.patch(f"{_MODULE}.make_tracked_session", return_value=api_session):
        yield api_session


def _walk(
    endpoint: str,
    manager: FakeResumeManager,
    folder_path: str | None = None,
    should_use_incremental_field: bool = False,
    db_incremental_field_last_value: Any = None,
) -> list[list[dict[str, Any]]]:
    return list(
        get_rows(
            credentials=CREDENTIALS,
            endpoint=endpoint,
            folder_path=folder_path,
            logger=mock.MagicMock(),
            resumable_source_manager=manager,
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=db_incremental_field_last_value,
        )
    )


class TestHelpers:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, ""),
            ("", ""),
            ("/", ""),
            ("  ", ""),
            ("Reports", "/Reports"),
            ("/Reports", "/Reports"),
            ("/Reports/", "/Reports"),
            (" /Reports/2024/ ", "/Reports/2024"),
        ],
    )
    def test_normalize_folder_path(self, value: str | None, expected: str) -> None:
        assert normalize_folder_path(value) == expected

    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 5, 1, 2, 3, 4, 500000, tzinfo=UTC), "2024-05-01T02:03:04Z"),
            (datetime(2024, 5, 1, 2, 3, 4), "2024-05-01T02:03:04Z"),
            (date(2024, 5, 1), "2024-05-01T00:00:00Z"),
            ("2024-05-01T02:03:04Z", "2024-05-01T02:03:04Z"),
            ("2024-05-01T02:03:04.123456+00:00", "2024-05-01T02:03:04Z"),
            ("not a timestamp", None),
            (None, None),
        ],
    )
    def test_format_time(self, value: Any, expected: str | None) -> None:
        assert format_time(value) == expected

    def test_normalize_row_renames_tag_keys_at_every_level(self) -> None:
        row = normalize_row(
            "files",
            {
                ".tag": "file",
                "id": "id:1",
                "sharing_info": {".tag": "public", "nested": [{".tag": "deep"}]},
            },
        )

        assert row["tag"] == "file"
        assert row["sharing_info"]["tag"] == "public"
        assert row["sharing_info"]["nested"][0]["tag"] == "deep"
        assert ".tag" not in json.dumps(row)

    def test_normalize_row_keeps_existing_tag_column(self) -> None:
        row = normalize_row("files", {".tag": "file", "tag": "user-tag", "id": "id:1"})

        assert row["tag"] == "user-tag"
        assert row[".tag"] == "file"

    def test_normalize_row_lifts_team_member_profile_to_the_root(self) -> None:
        row = normalize_row(
            "team_members",
            {
                "profile": {"team_member_id": "dbmid:1", "email": "a@example.com", "status": {".tag": "active"}},
                "roles": [{"role_id": "team_admin"}],
            },
        )

        assert row["team_member_id"] == "dbmid:1"
        assert row["email"] == "a@example.com"
        assert row["status"]["tag"] == "active"
        assert row["roles"] == [{"role_id": "team_admin"}]
        assert "profile" not in row

    def test_normalize_row_gives_audit_events_a_stable_synthetic_id(self) -> None:
        event = {"timestamp": "2024-05-01T00:00:00Z", "event_type": {".tag": "login_success"}}

        first = normalize_row("team_events", dict(event))
        again = normalize_row("team_events", dict(event))
        other = normalize_row("team_events", {**event, "timestamp": "2024-05-02T00:00:00Z"})

        assert first[EVENT_ID_FIELD] == again[EVENT_ID_FIELD]
        assert first[EVENT_ID_FIELD] != other[EVENT_ID_FIELD]


class TestDropboxClient:
    def test_sends_the_integration_access_token(self) -> None:
        with patched_session([_response({"entries": []})]) as api_session:
            DropboxClient(CREDENTIALS).post("/2/files/list_folder", {"path": ""})

        assert api_session.post.call_args.kwargs["headers"]["Authorization"] == "Bearer access-1"

    def test_an_expired_token_is_surfaced_rather_than_refreshed(self) -> None:
        # Renewing the token belongs to the integration, so a 401 must fail the run and ask the
        # user to reconnect instead of being retried behind their back.
        with patched_session([_response({}, status=401)]) as api_session:
            with pytest.raises(HTTPError):
                DropboxClient(CREDENTIALS).post("/2/files/list_folder", {"path": ""})

        assert api_session.post.call_count == 1

    @pytest.mark.parametrize(
        "body",
        [
            {"error_summary": "reset/...", "error": {".tag": "reset"}},
            {"error_summary": "invalid_cursor/..."},
            {"error": {".tag": "reset"}},
        ],
    )
    def test_cursor_reset_bodies_raise_cursor_reset(self, body: dict[str, Any]) -> None:
        with patched_session([_response(body, status=409)]):
            with pytest.raises(DropboxCursorReset):
                DropboxClient(CREDENTIALS).post("/2/files/list_folder/continue", {"cursor": "c1"})

    def test_other_conflicts_are_raised_as_http_errors(self) -> None:
        with patched_session([_response({"error_summary": "path/not_found/..."}, status=409)]):
            with pytest.raises(HTTPError):
                DropboxClient(CREDENTIALS).post("/2/files/list_folder", {"path": "/nope"})

    def test_select_user_header_is_sent_for_user_endpoints_only(self) -> None:
        credentials = DropboxCredentials(access_token="access-1", team_member_id="dbmid:1")
        with patched_session([_response({"entries": []}), _response({"members": []})]) as api_session:
            client = DropboxClient(credentials)
            client.post("/2/files/list_folder", {"path": ""}, select_user=True)
            client.post("/2/team/members/list_v2", {}, select_user=False)

        user_headers, team_headers = [call.kwargs["headers"] for call in api_session.post.call_args_list]
        assert user_headers["Dropbox-API-Select-User"] == "dbmid:1"
        assert "Dropbox-API-Select-User" not in team_headers

    def test_path_root_header_targets_the_team_space(self) -> None:
        credentials = DropboxCredentials(access_token="access-1", root_namespace_id="12345")
        with patched_session([_response({"entries": []})]) as api_session:
            DropboxClient(credentials).post("/2/files/list_folder", {"path": ""})

        header = api_session.post.call_args.kwargs["headers"]["Dropbox-API-Path-Root"]
        assert json.loads(header) == {".tag": "root", "root": "12345"}


class TestGetRows:
    def test_files_walks_the_continue_endpoint_and_checkpoints_each_page(self) -> None:
        manager = FakeResumeManager()
        pages = [
            _response({"entries": [{"id": "id:1", ".tag": "file"}], "cursor": "c1", "has_more": True}),
            _response({"entries": [{"id": "id:2", ".tag": "folder"}], "cursor": "c2", "has_more": False}),
        ]
        with patched_session(pages) as api_session:
            batches = _walk("files", manager, folder_path="Reports")

        assert [[row["id"] for row in batch] for batch in batches] == [["id:1"], ["id:2"]]
        first, second = api_session.post.call_args_list
        assert first.args[0].endswith("/2/files/list_folder")
        assert first.kwargs["json"]["path"] == "/Reports"
        assert first.kwargs["json"]["recursive"] is True
        assert second.args[0].endswith("/2/files/list_folder/continue")
        assert second.kwargs["json"] == {"cursor": "c1"}
        assert [state.cursor for state in manager.saved] == ["c1"]
        assert manager.clear_count == 1

    def test_shared_links_sends_the_cursor_back_to_the_same_path(self) -> None:
        manager = FakeResumeManager()
        pages = [
            _response({"links": [{"url": "u1"}], "cursor": "c1", "has_more": True}),
            _response({"links": [{"url": "u2"}], "has_more": False}),
        ]
        with patched_session(pages) as api_session:
            batches = _walk("shared_links", manager)

        assert [[row["url"] for row in batch] for batch in batches] == [["u1"], ["u2"]]
        assert [call.args[0] for call in api_session.post.call_args_list] == [
            "https://api.dropboxapi.com/2/sharing/list_shared_links"
        ] * 2
        assert api_session.post.call_args_list[1].kwargs["json"] == {"cursor": "c1"}

    @pytest.mark.parametrize(
        "page_body, expected_calls",
        [
            ({"entries": [{"shared_folder_id": "s1"}]}, 1),
            ({"entries": [{"shared_folder_id": "s1"}], "has_more": False, "cursor": "c1"}, 1),
            ({"entries": [{"shared_folder_id": "s1"}], "cursor": None}, 1),
        ],
    )
    def test_pagination_terminates_without_a_usable_cursor(
        self, page_body: dict[str, Any], expected_calls: int
    ) -> None:
        manager = FakeResumeManager()
        with patched_session([_response(page_body)]) as api_session:
            batches = _walk("shared_folders", manager)

        assert len(batches) == 1
        assert api_session.post.call_count == expected_calls
        assert manager.saved == []

    def test_a_cursor_without_has_more_keeps_paginating(self) -> None:
        manager = FakeResumeManager()
        pages = [
            _response({"entries": [{"shared_folder_id": "s1"}], "cursor": "c1"}),
            _response({"entries": [{"shared_folder_id": "s2"}]}),
        ]
        with patched_session(pages) as api_session:
            batches = _walk("shared_folders", manager)

        assert len(batches) == 2
        assert api_session.post.call_args_list[1].args[0].endswith("/2/sharing/list_folders/continue")

    def test_resumes_from_the_saved_cursor(self) -> None:
        manager = FakeResumeManager(DropboxResumeConfig(cursor="saved-cursor"))
        with patched_session([_response({"entries": [{"id": "id:9"}]})]) as api_session:
            _walk("files", manager)

        call = api_session.post.call_args
        assert call.args[0].endswith("/2/files/list_folder/continue")
        assert call.kwargs["json"] == {"cursor": "saved-cursor"}

    def test_a_reset_cursor_restarts_the_listing_from_scratch(self) -> None:
        manager = FakeResumeManager(DropboxResumeConfig(cursor="stale"))
        pages = [
            _response({"error_summary": "reset/..."}, status=409),
            _response({"entries": [{"id": "id:1"}], "has_more": False}),
        ]
        with patched_session(pages) as api_session:
            batches = _walk("files", manager)

        assert [[row["id"] for row in batch] for batch in batches] == [["id:1"]]
        assert manager.clear_count == 2  # once on reset, once when the walk completes
        assert api_session.post.call_args_list[1].args[0].endswith("/2/files/list_folder")

    def test_a_reset_on_the_first_page_is_not_swallowed(self) -> None:
        manager = FakeResumeManager()
        with patched_session([_response({"error_summary": "reset/..."}, status=409)]):
            with pytest.raises(DropboxCursorReset):
                _walk("files", manager)

    def test_rows_without_a_primary_key_are_dropped(self) -> None:
        manager = FakeResumeManager()
        page = _response({"entries": [{"id": "id:1"}, {".tag": "deleted", "name": "gone.csv"}]})
        with patched_session([page]):
            batches = _walk("files", manager)

        assert batches == [[{"id": "id:1"}]]

    def test_an_empty_page_yields_nothing(self) -> None:
        manager = FakeResumeManager()
        with patched_session([_response({"entries": []})]):
            assert _walk("files", manager) == []

    def test_team_events_window_starts_at_the_watermark(self) -> None:
        manager = FakeResumeManager()
        with patched_session([_response({"events": []})]) as api_session:
            _walk(
                "team_events",
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 5, 1, tzinfo=UTC),
            )

        body = api_session.post.call_args.kwargs["json"]
        assert body["time"] == {"start_time": "2024-05-01T00:00:00Z"}
        assert body["limit"] == 1000

    def test_team_events_full_refresh_sends_no_window(self) -> None:
        manager = FakeResumeManager()
        with patched_session([_response({"events": []})]) as api_session:
            _walk("team_events", manager)

        assert "time" not in api_session.post.call_args.kwargs["json"]

    def test_team_events_rows_carry_the_synthetic_primary_key(self) -> None:
        manager = FakeResumeManager()
        page = _response({"events": [{"timestamp": "2024-05-01T00:00:00Z", "event_type": {".tag": "login_success"}}]})
        with patched_session([page]):
            batches = _walk("team_events", manager)

        assert len(batches[0][0][EVENT_ID_FIELD]) == 64

    def test_team_endpoints_do_not_select_a_member(self) -> None:
        credentials = DropboxCredentials(access_token="access-1", team_member_id="dbmid:1")
        manager = FakeResumeManager()
        with patched_session([_response({"members": []})]) as api_session:
            list(
                get_rows(
                    credentials=credentials,
                    endpoint="team_members",
                    folder_path=None,
                    logger=mock.MagicMock(),
                    resumable_source_manager=manager,
                )
            )

        assert "Dropbox-API-Select-User" not in api_session.post.call_args.kwargs["headers"]


class TestValidateCredentials:
    def test_valid_when_the_token_check_echoes_the_query(self) -> None:
        with patched_session([_response({"result": CHECK_USER_QUERY})]) as api_session:
            assert validate_credentials(CREDENTIALS) == (True, None)

        call = api_session.post.call_args
        # `check/user` needs no scopes, so a connection missing a per-table scope still connects.
        assert call.args[0].endswith("/2/check/user")
        assert call.kwargs["json"] == {"query": CHECK_USER_QUERY}
        assert "Dropbox-API-Select-User" not in call.kwargs["headers"]

    @pytest.mark.parametrize("status", [400, 401])
    def test_invalid_when_dropbox_rejects_the_token(self, status: int) -> None:
        with patched_session([_response({"error_summary": "invalid_access_token/..."}, status=status)]):
            is_valid, error = validate_credentials(CREDENTIALS)

        assert is_valid is False
        assert error is not None and "Reconnect" in error

    def test_invalid_when_the_echo_does_not_come_back(self) -> None:
        with patched_session([_response({"result": "something else"})]):
            assert validate_credentials(CREDENTIALS)[0] is False

    def test_invalid_when_the_request_raises(self) -> None:
        api_session = mock.MagicMock()
        api_session.post.side_effect = Exception("boom")
        with mock.patch(f"{_MODULE}.make_tracked_session", return_value=api_session):
            assert validate_credentials(CREDENTIALS)[0] is False


class TestCheckEndpointAccess:
    def test_reports_missing_scopes_per_endpoint(self) -> None:
        responses = [
            _response({"entries": []}),
            _response({"error_summary": "missing_scope/..."}, status=403),
            _response({}, status=500),
        ]
        with patched_session(responses) as api_session:
            results = check_endpoint_access(CREDENTIALS, ["files", "team_events", "shared_folders"])

        assert results["files"] is None
        assert results["team_events"] is not None and "Dropbox Business team" in results["team_events"]
        # A 5xx is not a permission problem.
        assert results["shared_folders"] is None
        assert api_session.post.call_args_list[0].kwargs["json"]["limit"] == 1

    def test_a_missing_folder_is_reported_against_the_files_table(self) -> None:
        with patched_session([_response({"error_summary": "path/not_found/..."}, status=409)]):
            results = check_endpoint_access(CREDENTIALS, ["files"])

        assert results["files"] is not None and "folder path" in results["files"]

    def test_unknown_endpoints_are_reported_as_reachable(self) -> None:
        with patched_session([]):
            assert check_endpoint_access(CREDENTIALS, ["nope"]) == {"nope": None}


class TestDropboxSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = DROPBOX_ENDPOINTS[endpoint]
        response = dropbox_source(
            credentials=CREDENTIALS,
            endpoint=endpoint,
            folder_path=None,
            logger=mock.MagicMock(),
            resumable_source_manager=FakeResumeManager(),
        )

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        # Dropbox documents no ordering, so the watermark is only committed at run end.
        assert response.sort_mode == "desc"
        if endpoint == "team_events":
            assert response.partition_mode == "datetime"
            assert response.partition_keys == ["timestamp"]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
