from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.alguna.alguna import (
    ALGUNA_API_VERSION,
    AlgunaResumeConfig,
    alguna_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.alguna.settings import ALGUNA_ENDPOINTS, ENDPOINTS

SESSION_PATCH_TARGET = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.alguna.alguna.make_tracked_session"
)


def _make_manager(resume_state: AlgunaResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(items: list[dict[str, Any]], status_code: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.json.return_value = {"data": items, "pagination": {"per_page": 100, "total_pages": 1}}
    return resp


def _query(call: mock._Call) -> dict[str, list[str]]:
    return parse_qs(urlparse(call.args[0]).query)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
            ("server_error", 500, False),
        ]
    )
    def test_validate_credentials_status_mapping(self, _name: str, status_code: int, expected: bool) -> None:
        response = mock.MagicMock()
        response.status_code = status_code

        with mock.patch(SESSION_PATCH_TARGET) as mock_session:
            mock_session.return_value.get.return_value = response
            assert validate_credentials("key") is expected

    def test_validate_credentials_swallows_exceptions(self):
        with mock.patch(SESSION_PATCH_TARGET) as mock_session:
            mock_session.return_value.get.side_effect = Exception("boom")
            assert validate_credentials("key") is False


class TestGetRows:
    @mock.patch(SESSION_PATCH_TARGET)
    def test_paginates_with_limit_offset(self, mock_session):
        full_page = [{"id": f"cust_{i}"} for i in range(100)]
        last_page = [{"id": "cust_last"}]
        mock_session.return_value.get.side_effect = [_response(full_page), _response(last_page)]

        manager = _make_manager()
        batches = list(get_rows("key", "customers", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == [*(f"cust_{i}" for i in range(100)), "cust_last"]

        calls = mock_session.return_value.get.call_args_list
        assert _query(calls[0])["offset"] == ["0"]
        assert _query(calls[0])["limit"] == ["100"]
        assert _query(calls[0])["sort"] == ["created_at:asc"]
        assert _query(calls[1])["offset"] == ["100"]

        # State is saved only after a full page has been yielded, so a crash re-yields
        # the last page instead of skipping it.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].offset == 100

    @mock.patch(SESSION_PATCH_TARGET)
    def test_requests_send_auth_and_version_headers(self, mock_session):
        mock_session.return_value.get.return_value = _response([{"id": "cust_1"}])

        list(get_rows("key", "customers", mock.MagicMock(), _make_manager()))

        headers = mock_session.return_value.get.call_args.kwargs["headers"]
        assert headers["Authorization"] == "Bearer key"
        # Alguna rejects any request without the date-based version header.
        assert headers["Alguna-Version"] == ALGUNA_API_VERSION

    @parameterized.expand([("payments",), ("products",)])
    def test_no_sort_param_for_endpoints_without_sort(self, endpoint: str) -> None:
        with mock.patch(SESSION_PATCH_TARGET) as mock_session:
            mock_session.return_value.get.return_value = _response([{"id": "x"}])

            list(get_rows("key", endpoint, mock.MagicMock(), _make_manager()))

            assert "sort" not in _query(mock_session.return_value.get.call_args)

    @mock.patch(SESSION_PATCH_TARGET)
    def test_resumes_from_saved_offset(self, mock_session):
        mock_session.return_value.get.return_value = _response([{"id": "cust_201"}])

        manager = _make_manager(AlgunaResumeConfig(offset=200))
        list(get_rows("key", "customers", mock.MagicMock(), manager))

        assert _query(mock_session.return_value.get.call_args_list[0])["offset"] == ["200"]

    @mock.patch(SESSION_PATCH_TARGET)
    def test_empty_first_page_stops_without_yield(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        manager = _make_manager()
        batches = list(get_rows("key", "customers", mock.MagicMock(), manager))

        assert batches == []
        manager.save_state.assert_not_called()

    @mock.patch(SESSION_PATCH_TARGET)
    def test_short_page_terminates_without_saving_state(self, mock_session):
        mock_session.return_value.get.return_value = _response([{"id": "cust_1"}, {"id": "cust_2"}])

        manager = _make_manager()
        batches = list(get_rows("key", "customers", mock.MagicMock(), manager))

        assert len(batches) == 1
        assert mock_session.return_value.get.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(SESSION_PATCH_TARGET)
    def test_missing_data_key_raises(self, mock_session):
        resp = mock.MagicMock()
        resp.status_code = 200
        resp.ok = True
        resp.json.return_value = {"unexpected": "envelope"}
        mock_session.return_value.get.return_value = resp

        # A 200 body without "data" means the response shape changed — the sync must fail
        # loudly instead of silently reporting 0 rows.
        with pytest.raises(KeyError):
            list(get_rows("key", "customers", mock.MagicMock(), _make_manager()))

    @mock.patch(SESSION_PATCH_TARGET)
    def test_auth_error_raises_without_retry(self, mock_session):
        resp = mock.MagicMock()
        resp.status_code = 401
        resp.ok = False
        resp.raise_for_status.side_effect = requests.HTTPError("401 Client Error", response=resp)
        mock_session.return_value.get.return_value = resp

        with pytest.raises(requests.HTTPError):
            list(get_rows("key", "customers", mock.MagicMock(), _make_manager()))

        # Credential failures must not burn retry attempts before surfacing.
        assert mock_session.return_value.get.call_count == 1


class TestAlgunaSourceResponse:
    @parameterized.expand([(endpoint,) for endpoint in ENDPOINTS])
    def test_response_metadata_per_endpoint(self, endpoint: str) -> None:
        config = ALGUNA_ENDPOINTS[endpoint]
        response = alguna_source("key", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == config.primary_keys
        assert response.partition_mode == "datetime"
        assert response.partition_keys == [config.partition_key]

    @parameterized.expand([(name, config) for name, config in ALGUNA_ENDPOINTS.items()])
    def test_partition_keys_are_stable_creation_fields(self, _name: str, config) -> None:
        assert config.partition_key == "created_at"
