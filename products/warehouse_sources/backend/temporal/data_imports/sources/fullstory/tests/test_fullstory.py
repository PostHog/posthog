from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.fullstory.fullstory import (
    FullStoryResumeConfig,
    fullstory_source,
    get_rows,
    validate_credentials,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.fullstory.fullstory"


def _make_manager(resume_state: FullStoryResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(items: list[dict[str, Any]], next_token: str | None = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    body: dict[str, Any] = {"results": items}
    if next_token:
        body["next_page_token"] = next_token
    resp.json.return_value = body
    resp.status_code = 200
    resp.ok = True
    return resp


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("key") is expected

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key") is False

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_auth_header_uses_raw_key_after_basic(self, mock_session):
        response = mock.MagicMock()
        response.status_code = 200
        mock_session.return_value.get.return_value = response

        validate_credentials("key123")

        headers = mock_session.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Basic key123"


class TestGetRows:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_paginates_via_page_token(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response([{"id": "u1"}], next_token="tok1"),
            _response([{"id": "u2"}]),
        ]

        manager = _make_manager()
        batches = list(get_rows("key", "users", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["u1", "u2"]
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].next_page_token == "tok1"
        second_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert parse_qs(urlparse(second_url).query)["page_token"] == ["tok1"]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_from_saved_token(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        manager = _make_manager(FullStoryResumeConfig(next_page_token="tok_resume"))
        list(get_rows("key", "users", mock.MagicMock(), manager))

        url = mock_session.return_value.get.call_args.args[0]
        assert parse_qs(urlparse(url).query)["page_token"] == ["tok_resume"]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_empty_response_stops_without_saving_state(self, mock_session):
        mock_session.return_value.get.return_value = _response([], next_token="tok_loop")

        manager = _make_manager()
        batches = list(get_rows("key", "users", mock.MagicMock(), manager))

        assert batches == []
        assert mock_session.return_value.get.call_count == 1
        manager.save_state.assert_not_called()


class TestFullStorySourceResponse:
    def test_response_metadata(self):
        response = fullstory_source("key", "users", mock.MagicMock(), _make_manager())

        assert response.name == "users"
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        assert response.partition_mode is None
        assert response.partition_keys is None
