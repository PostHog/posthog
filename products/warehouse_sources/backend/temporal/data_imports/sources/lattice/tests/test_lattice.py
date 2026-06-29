from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.lattice.lattice import (
    PAGE_SIZE,
    LatticeResumeConfig,
    _base_url,
    get_rows,
    lattice_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lattice.settings import (
    ENDPOINTS,
    LATTICE_ENDPOINTS,
)


def _make_manager(resume_state: LatticeResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(items: list[dict[str, Any]], has_more: bool = False, ending_cursor: str | None = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = {"data": items, "hasMore": has_more, "endingCursor": ending_cursor}
    resp.status_code = 200
    resp.ok = True
    return resp


class TestBaseUrl:
    def test_us_and_emea_hosts(self):
        assert _base_url("us") == "https://api.latticehq.com"
        assert _base_url("emea") == "https://api.emea.latticehq.com"

    def test_invalid_region_raises(self):
        with pytest.raises(ValueError):
            _base_url("evil.example.com")


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_message",
        [
            (200, True, None),
            # Keys inherit the creating user's privileges; 403 means a scope
            # gap, not a bad key.
            (403, True, None),
            (401, False, "Invalid Lattice API key"),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.lattice.lattice.make_tracked_session")
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected_valid, expected_message):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("us", "key") == (expected_valid, expected_message)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.lattice.lattice.make_tracked_session")
    def test_validate_credentials_rejects_bad_region_without_request(self, mock_session):
        is_valid, error = validate_credentials("evil", "key")
        assert is_valid is False
        assert error is not None
        mock_session.return_value.get.assert_not_called()

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.lattice.lattice.make_tracked_session")
    def test_validate_credentials_transport_error_is_not_invalid_key(self, mock_session):
        # A transient connectivity failure must not be reported as a bad key.
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")

        is_valid, error = validate_credentials("us", "key")
        assert is_valid is False
        assert error is not None
        assert "Invalid Lattice API key" not in error


class TestGetRows:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.lattice.lattice.make_tracked_session")
    def test_paginates_via_ending_cursor(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response([{"id": "1"}], has_more=True, ending_cursor="cur_abc"),
            _response([{"id": "2"}], has_more=False),
        ]

        manager = _make_manager()
        batches = list(get_rows("us", "key", "users", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["1", "2"]
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].starting_after == "cur_abc"
        second_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert parse_qs(urlparse(second_url).query)["startingAfter"] == ["cur_abc"]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.lattice.lattice.make_tracked_session")
    def test_first_request_uses_max_page_size(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        manager = _make_manager()
        list(get_rows("us", "key", "goals", mock.MagicMock(), manager))

        url = mock_session.return_value.get.call_args.args[0]
        parsed = urlparse(url)
        assert parsed.path == "/v1/goals"
        assert parse_qs(parsed.query)["limit"] == [str(PAGE_SIZE)]
        assert "startingAfter" not in parse_qs(parsed.query)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.lattice.lattice.make_tracked_session")
    def test_emea_region_uses_emea_host(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        manager = _make_manager()
        list(get_rows("emea", "key", "users", mock.MagicMock(), manager))

        url = mock_session.return_value.get.call_args.args[0]
        assert urlparse(url).netloc == "api.emea.latticehq.com"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.lattice.lattice.make_tracked_session")
    def test_resumes_from_saved_cursor(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        manager = _make_manager(LatticeResumeConfig(starting_after="cur_resume"))
        list(get_rows("us", "key", "users", mock.MagicMock(), manager))

        url = mock_session.return_value.get.call_args.args[0]
        assert parse_qs(urlparse(url).query)["startingAfter"] == ["cur_resume"]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.lattice.lattice.make_tracked_session")
    def test_has_more_without_cursor_stops(self, mock_session):
        mock_session.return_value.get.return_value = _response([{"id": "1"}], has_more=True, ending_cursor=None)

        manager = _make_manager()
        batches = list(get_rows("us", "key", "users", mock.MagicMock(), manager))

        assert len(batches) == 1
        assert mock_session.return_value.get.call_count == 1

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.lattice.lattice.make_tracked_session")
    def test_empty_response_stops_without_saving_state(self, mock_session):
        mock_session.return_value.get.return_value = _response([], has_more=True, ending_cursor="cur_loop")

        manager = _make_manager()
        batches = list(get_rows("us", "key", "users", mock.MagicMock(), manager))

        assert batches == []
        manager.save_state.assert_not_called()


class TestLatticeSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = LATTICE_ENDPOINTS[endpoint]
        response = lattice_source("us", "key", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        assert response.partition_mode is None
        assert response.partition_keys is None
