from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.hibob.hibob import (
    get_rows,
    hibob_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hibob.settings import ENDPOINTS, HIBOB_ENDPOINTS


def _response(body: dict[str, Any]) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = body
    resp.status_code = 200
    resp.ok = True
    return resp


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_error",
        [
            (200, True, None),
            # Service users without category permissions 403 but are valid.
            (403, True, None),
            (401, False, "Invalid HiBob Service User credentials"),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.hibob.hibob.make_tracked_session")
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected_valid, expected_error):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("service-id", "token") == (expected_valid, expected_error)

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.hibob.hibob.make_tracked_session")
    def test_validate_credentials_surfaces_transport_errors(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("service-id", "token") == (False, "boom")


class TestGetRows:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.hibob.hibob.make_tracked_session")
    def test_employees_uses_post_for_read_with_body(self, mock_session):
        mock_session.return_value.post.return_value = _response({"employees": [{"id": "1"}]})

        batches = list(get_rows("service-id", "token", "employees", mock.MagicMock()))

        assert batches == [[{"id": "1"}]]
        mock_session.return_value.post.assert_called_once()
        call = mock_session.return_value.post.call_args
        assert call.args[0] == "https://api.hibob.com/v1/people/search"
        assert call.kwargs["json"] == {"showInactive": True, "humanReadable": "REPLACE"}
        mock_session.return_value.get.assert_not_called()

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.hibob.hibob.make_tracked_session")
    def test_tasks_uses_get(self, mock_session):
        mock_session.return_value.get.return_value = _response({"tasks": [{"id": 1}, {"id": 2}]})

        batches = list(get_rows("service-id", "token", "tasks", mock.MagicMock()))

        assert batches == [[{"id": 1}, {"id": 2}]]
        mock_session.return_value.get.assert_called_once_with("https://api.hibob.com/v1/tasks", timeout=mock.ANY)
        mock_session.return_value.post.assert_not_called()

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.hibob.hibob.make_tracked_session")
    def test_session_uses_basic_auth(self, mock_session):
        mock_session.return_value.get.return_value = _response({"tasks": []})

        list(get_rows("service-id", "token", "tasks", mock.MagicMock()))

        assert mock_session.return_value.auth == ("service-id", "token")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.hibob.hibob.make_tracked_session")
    def test_empty_response_yields_nothing(self, mock_session):
        mock_session.return_value.post.return_value = _response({"employees": []})

        assert list(get_rows("service-id", "token", "employees", mock.MagicMock())) == []

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.hibob.hibob.make_tracked_session")
    def test_missing_data_key_yields_nothing(self, mock_session):
        mock_session.return_value.post.return_value = _response({"unexpected": "shape"})

        assert list(get_rows("service-id", "token", "employees", mock.MagicMock())) == []


class TestHiBobSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = HIBOB_ENDPOINTS[endpoint]
        response = hibob_source("service-id", "token", endpoint, mock.MagicMock())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        assert response.partition_mode is None
        assert response.partition_keys is None
