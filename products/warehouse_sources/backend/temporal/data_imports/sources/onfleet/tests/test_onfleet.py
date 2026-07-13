import base64
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.onfleet.onfleet import (
    OnfleetResumeConfig,
    _basic_auth_token,
    _build_url,
    _to_epoch_ms,
    get_credentials_status,
    get_rows,
    onfleet_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onfleet.settings import (
    ENDPOINTS,
    ONFLEET_ENDPOINTS,
)

_TRANSPORT = "products.warehouse_sources.backend.temporal.data_imports.sources.onfleet.onfleet.make_tracked_session"


def _make_manager(resume_state: OnfleetResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _resp(body: Any) -> mock.MagicMock:
    resp = mock.MagicMock(status_code=200, ok=True)
    resp.json.return_value = body
    return resp


class TestToEpochMs:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (True, None),
            (1700000000000, 1700000000000),
            (1700000000000.5, 1700000000000),
            ("1700000000000", 1700000000000),
            ("not-a-number", None),
            # datetime/date must convert to MILLISECONDS, not seconds — the crux of Onfleet's `from`.
            (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), 1700000000000),
            (date(2023, 11, 15), int(datetime(2023, 11, 15, tzinfo=UTC).timestamp()) * 1000),
        ],
    )
    def test_to_epoch_ms_values(self, value, expected):
        assert _to_epoch_ms(value) == expected


class TestBasicAuth:
    def test_api_key_is_username_with_empty_password(self):
        # Onfleet Basic auth: API key as username, empty password.
        assert base64.b64decode(_basic_auth_token("my-key")).decode() == "my-key:"


class TestBuildUrl:
    def test_no_params(self):
        assert _build_url("/tasks/all", {}) == "https://onfleet.com/api/v2/tasks/all"

    def test_drops_none_values_and_encodes(self):
        url = _build_url("/tasks/all", {"from": 0, "lastId": None})
        assert url == "https://onfleet.com/api/v2/tasks/all?from=0"


class TestGetRowsPaginated:
    @mock.patch(_TRANSPORT)
    def test_paginates_via_last_id_and_stops_when_absent(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _resp({"lastId": "abc", "tasks": [{"id": "1"}, {"id": "2"}]}),
            _resp({"tasks": [{"id": "3"}]}),  # no lastId -> final page
        ]
        manager = _make_manager()

        batches = list(get_rows("key", "tasks", mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == ["1", "2", "3"]
        # Second request continues after the first page's lastId.
        assert "lastId=abc" in mock_session.return_value.get.call_args_list[1].args[0]
        # State saved once (only while a next cursor exists), after yielding the page.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].last_id == "abc"

    @mock.patch(_TRANSPORT)
    def test_resumes_from_saved_cursor(self, mock_session):
        mock_session.return_value.get.return_value = _resp({"tasks": [{"id": "9"}]})
        manager = _make_manager(OnfleetResumeConfig(last_id="saved", from_ms=1234))

        list(get_rows("key", "tasks", mock.MagicMock(), manager))

        first_url = mock_session.return_value.get.call_args_list[0].args[0]
        assert "lastId=saved" in first_url
        assert "from=1234" in first_url

    @mock.patch(_TRANSPORT)
    def test_incremental_from_value_used_as_epoch_ms(self, mock_session):
        mock_session.return_value.get.return_value = _resp({"tasks": [{"id": "1"}]})
        manager = _make_manager()

        list(
            get_rows(
                "key",
                "tasks",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=1700000000000,
            )
        )

        assert "from=1700000000000" in mock_session.return_value.get.call_args_list[0].args[0]

    @mock.patch(_TRANSPORT)
    def test_full_refresh_defaults_from_to_zero(self, mock_session):
        mock_session.return_value.get.return_value = _resp({"tasks": [{"id": "1"}]})
        manager = _make_manager()

        list(get_rows("key", "tasks", mock.MagicMock(), manager))

        assert "from=0" in mock_session.return_value.get.call_args_list[0].args[0]

    @mock.patch(_TRANSPORT)
    def test_empty_page_with_advancing_cursor_keeps_paginating(self, mock_session):
        # A page can be empty yet still carry an advancing lastId; pagination must continue
        # (not terminate) so later, non-empty pages are not skipped.
        mock_session.return_value.get.side_effect = [
            _resp({"lastId": "p2", "tasks": []}),
            _resp({"tasks": [{"id": "1"}]}),  # no lastId -> final page
        ]
        manager = _make_manager()

        batches = list(get_rows("key", "tasks", mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == ["1"]
        assert "lastId=p2" in mock_session.return_value.get.call_args_list[1].args[0]
        # No batch was yielded for the empty page, so no state was saved for it.
        manager.save_state.assert_not_called()

    @mock.patch(_TRANSPORT)
    def test_non_advancing_cursor_terminates(self, mock_session):
        # A repeated lastId must not loop forever.
        mock_session.return_value.get.side_effect = [
            _resp({"lastId": "x", "tasks": [{"id": "1"}]}),
            _resp({"lastId": "x", "tasks": [{"id": "1"}]}),
        ]
        manager = _make_manager()

        batches = list(get_rows("key", "tasks", mock.MagicMock(), manager))

        assert mock_session.return_value.get.call_count == 2
        assert [row["id"] for batch in batches for row in batch] == ["1", "1"]


class TestGetRowsNonPaginated:
    @mock.patch(_TRANSPORT)
    def test_bare_array_endpoint_yields_once(self, mock_session):
        mock_session.return_value.get.return_value = _resp([{"id": "w1"}, {"id": "w2"}])
        manager = _make_manager()

        batches = list(get_rows("key", "workers", mock.MagicMock(), manager))

        assert batches == [[{"id": "w1"}, {"id": "w2"}]]
        assert mock_session.return_value.get.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(_TRANSPORT)
    def test_single_object_endpoint_wraps_in_list(self, mock_session):
        mock_session.return_value.get.return_value = _resp({"id": "org1", "name": "Acme"})
        manager = _make_manager()

        batches = list(get_rows("key", "organization", mock.MagicMock(), manager))

        assert batches == [[{"id": "org1", "name": "Acme"}]]


class TestGetCredentialsStatus:
    @pytest.mark.parametrize("status_code", [200, 401, 403, 500])
    @mock.patch(_TRANSPORT)
    def test_returns_status_code(self, mock_session, status_code):
        mock_session.return_value.get.return_value = mock.MagicMock(status_code=status_code)
        assert get_credentials_status("key") == status_code

    @mock.patch(_TRANSPORT)
    def test_returns_none_on_transport_error(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert get_credentials_status("key") is None


class TestOnfleetSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = ONFLEET_ENDPOINTS[endpoint]
        response = onfleet_source("key", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.sort_mode == "asc"
        # Onfleet epoch-ms timestamps would misbucket under the datetime partitioner, so partitioning is off.
        assert response.partition_mode is None
        assert response.partition_keys is None
