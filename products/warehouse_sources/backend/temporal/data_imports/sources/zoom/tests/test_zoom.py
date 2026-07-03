import json
from typing import Any

import pytest
from unittest.mock import MagicMock, patch

from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.zoom.zoom import (
    ZoomClient,
    ZoomResumeConfig,
    get_rows,
    validate_credentials,
    zoom_source,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.zoom.zoom"


def _resp(body: dict[str, Any], status: int = 200) -> Response:
    response = Response()
    response.status_code = status
    response._content = json.dumps(body).encode()
    response.headers["Content-Type"] = "application/json"
    return response


def _manager(can_resume: bool = False, state: ZoomResumeConfig | None = None) -> MagicMock:
    manager = MagicMock(spec=ResumableSourceManager)
    manager.can_resume.return_value = can_resume
    manager.load_state.return_value = state
    return manager


class TestZoomResumeConfig:
    def test_defaults(self) -> None:
        assert ZoomResumeConfig() == ZoomResumeConfig(next_page_token="", user_index=0)

    def test_round_trips_through_manager_load(self) -> None:
        # Older state without user_index must still deserialize (default applies).
        assert ZoomResumeConfig(next_page_token="tok") == ZoomResumeConfig(next_page_token="tok", user_index=0)


class TestZoomClient:
    @patch(f"{MODULE}.make_tracked_session")
    def test_fetch_token_returns_access_token(self, mock_session: MagicMock) -> None:
        mock_session.return_value.post.return_value = _resp({"access_token": "tok-1", "expires_in": 3599})
        client = ZoomClient("acc", "cid", "secret")
        assert client.fetch_token() == "tok-1"

    @patch(f"{MODULE}.make_tracked_session")
    def test_fetch_token_raises_on_bad_credentials(self, mock_session: MagicMock) -> None:
        mock_session.return_value.post.return_value = _resp({"error": "invalid_client"}, status=400)
        client = ZoomClient("acc", "cid", "secret")
        with pytest.raises(HTTPError):
            client.fetch_token()

    @patch(f"{MODULE}.make_tracked_session")
    def test_fetch_token_raises_when_token_missing(self, mock_session: MagicMock) -> None:
        mock_session.return_value.post.return_value = _resp({"token_type": "bearer"})
        client = ZoomClient("acc", "cid", "secret")
        with pytest.raises(ValueError):
            client.fetch_token()

    @patch(f"{MODULE}.make_tracked_session")
    def test_request_refreshes_token_once_on_401(self, mock_session: MagicMock) -> None:
        session = mock_session.return_value
        session.post.return_value = _resp({"access_token": "tok"})
        session.get.side_effect = [
            _resp({"code": 124, "message": "Invalid access token."}, status=401),
            _resp({"users": []}, status=200),
        ]

        client = ZoomClient("acc", "cid", "secret")
        response = client.request("/users", {"page_size": 1})

        assert response.status_code == 200
        # Token fetched twice: initial + refresh after the 401.
        assert session.post.call_count == 2
        assert session.get.call_count == 2

    @patch(f"{MODULE}.make_tracked_session")
    def test_request_caches_token_across_calls(self, mock_session: MagicMock) -> None:
        session = mock_session.return_value
        session.post.return_value = _resp({"access_token": "tok"})
        session.get.return_value = _resp({"users": []})

        client = ZoomClient("acc", "cid", "secret")
        client.request("/users")
        client.request("/users")

        # Token is fetched lazily once and reused.
        assert session.post.call_count == 1


class TestTopLevelRows:
    def test_paginates_and_yields_each_page(self) -> None:
        client = MagicMock()
        client.request.side_effect = [
            _resp({"users": [{"id": "u1"}], "next_page_token": "t1"}),
            _resp({"users": [{"id": "u2"}], "next_page_token": ""}),
        ]
        manager = _manager()

        rows = list(get_rows(client, "users", MagicMock(), manager))

        assert rows == [[{"id": "u1"}], [{"id": "u2"}]]

    def test_saves_state_after_each_non_terminal_page(self) -> None:
        client = MagicMock()
        client.request.side_effect = [
            _resp({"users": [{"id": "u1"}], "next_page_token": "t1"}),
            _resp({"users": [{"id": "u2"}], "next_page_token": ""}),
        ]
        manager = _manager()

        list(get_rows(client, "users", MagicMock(), manager))

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert saved == [ZoomResumeConfig(next_page_token="t1")]

    def test_first_request_omits_token_then_carries_cursor(self) -> None:
        client = MagicMock()
        client.request.side_effect = [
            _resp({"users": [{"id": "u1"}], "next_page_token": "t1"}),
            _resp({"users": [{"id": "u2"}], "next_page_token": ""}),
        ]

        list(get_rows(client, "users", MagicMock(), _manager()))

        calls = client.request.call_args_list
        assert calls[0].args[0] == "/users"
        assert "next_page_token" not in calls[0].args[1]
        assert calls[1].args[1]["next_page_token"] == "t1"

    def test_resume_seeds_first_request_with_saved_token(self) -> None:
        client = MagicMock()
        client.request.side_effect = [
            _resp({"users": [{"id": "u9"}], "next_page_token": ""}),
        ]
        manager = _manager(can_resume=True, state=ZoomResumeConfig(next_page_token="resumed"))

        list(get_rows(client, "users", MagicMock(), manager))

        assert client.request.call_args_list[0].args[1]["next_page_token"] == "resumed"
        manager.load_state.assert_called_once()

    def test_terminal_single_page_saves_no_state(self) -> None:
        client = MagicMock()
        client.request.side_effect = [_resp({"users": [{"id": "u1"}], "next_page_token": ""})]
        manager = _manager()

        list(get_rows(client, "users", MagicMock(), manager))

        manager.save_state.assert_not_called()


class TestFanOutRows:
    def _client_with(self, responses: dict[str, Response]) -> MagicMock:
        client = MagicMock()

        def side_effect(path: str, params: dict[str, Any] | None = None) -> Response:
            assert path in responses, f"unexpected path {path}"
            return responses[path]

        client.request.side_effect = side_effect
        return client

    def test_fans_out_meetings_per_user(self) -> None:
        client = self._client_with(
            {
                "/users": _resp({"users": [{"id": "u1"}, {"id": "u2"}], "next_page_token": ""}),
                "/users/u1/meetings": _resp({"meetings": [{"id": 1}], "next_page_token": ""}),
                "/users/u2/meetings": _resp({"meetings": [{"id": 2}], "next_page_token": ""}),
            }
        )

        rows = list(get_rows(client, "meetings", MagicMock(), _manager()))

        assert rows == [[{"id": 1}], [{"id": 2}]]

    @pytest.mark.parametrize("status", [400, 404])
    def test_skips_user_lacking_feature(self, status: int) -> None:
        client = self._client_with(
            {
                "/users": _resp({"users": [{"id": "u1"}, {"id": "u2"}], "next_page_token": ""}),
                "/users/u1/webinars": _resp({"code": 200, "message": "no webinar plan"}, status=status),
                "/users/u2/webinars": _resp({"webinars": [{"id": 9}], "next_page_token": ""}),
            }
        )

        rows = list(get_rows(client, "webinars", MagicMock(), _manager()))

        # The unlicensed user is skipped without aborting the sync.
        assert rows == [[{"id": 9}]]

    def test_checkpoints_user_index_after_each_user(self) -> None:
        client = self._client_with(
            {
                "/users": _resp({"users": [{"id": "u1"}, {"id": "u2"}], "next_page_token": ""}),
                "/users/u1/meetings": _resp({"meetings": [{"id": 1}], "next_page_token": ""}),
                "/users/u2/meetings": _resp({"meetings": [{"id": 2}], "next_page_token": ""}),
            }
        )
        manager = _manager()

        list(get_rows(client, "meetings", MagicMock(), manager))

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert ZoomResumeConfig(next_page_token="", user_index=1) in saved
        assert ZoomResumeConfig(next_page_token="", user_index=2) in saved

    def test_resume_starts_at_saved_user_index(self) -> None:
        client = self._client_with(
            {
                "/users": _resp({"users": [{"id": "u1"}, {"id": "u2"}], "next_page_token": ""}),
                "/users/u2/meetings": _resp({"meetings": [{"id": 2}], "next_page_token": ""}),
            }
        )
        manager = _manager(can_resume=True, state=ZoomResumeConfig(next_page_token="", user_index=1))

        rows = list(get_rows(client, "meetings", MagicMock(), manager))

        # u1 is skipped entirely (its meetings path is never requested).
        assert rows == [[{"id": 2}]]
        requested = [call.args[0] for call in client.request.call_args_list]
        assert "/users/u1/meetings" not in requested


class TestZoomSource:
    def test_source_response_shape(self) -> None:
        response = zoom_source("acc", "cid", "secret", "users", MagicMock(), _manager())
        assert response.name == "users"
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]
        assert response.partition_format == "week"

    @pytest.mark.parametrize(
        ("endpoint", "primary_key"),
        [("users", "id"), ("meetings", "id"), ("webinars", "id")],
    )
    def test_primary_keys_per_endpoint(self, endpoint: str, primary_key: str) -> None:
        response = zoom_source("acc", "cid", "secret", endpoint, MagicMock(), _manager())
        assert response.primary_keys == [primary_key]


class TestValidateCredentials:
    @patch(f"{MODULE}.make_tracked_session")
    def test_bad_credentials_return_false(self, mock_session: MagicMock) -> None:
        mock_session.return_value.post.return_value = _resp({"error": "invalid_client"}, status=400)
        ok, error = validate_credentials("acc", "cid", "secret")
        assert ok is False
        assert error is not None

    @patch(f"{MODULE}.make_tracked_session")
    def test_source_create_only_validates_token(self, mock_session: MagicMock) -> None:
        session = mock_session.return_value
        session.post.return_value = _resp({"access_token": "tok"})
        ok, error = validate_credentials("acc", "cid", "secret", schema_name=None)
        assert ok is True
        assert error is None
        # No endpoint probe at source-create.
        session.get.assert_not_called()

    @patch(f"{MODULE}.make_tracked_session")
    def test_schema_probe_success(self, mock_session: MagicMock) -> None:
        session = mock_session.return_value
        session.post.return_value = _resp({"access_token": "tok"})
        session.get.return_value = _resp({"users": []})
        ok, error = validate_credentials("acc", "cid", "secret", schema_name="users")
        assert ok is True
        assert error is None

    @pytest.mark.parametrize("status", [401, 403])
    @patch(f"{MODULE}.make_tracked_session")
    def test_schema_probe_missing_scope(self, mock_session: MagicMock, status: int) -> None:
        session = mock_session.return_value
        session.post.return_value = _resp({"access_token": "tok"})
        session.get.return_value = _resp({"code": 104}, status=status)
        ok, error = validate_credentials("acc", "cid", "secret", schema_name="users")
        assert ok is False
        assert error is not None and "scope" in error
