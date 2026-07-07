from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.mollie.mollie import (
    MollieResumeConfig,
    get_rows,
    mollie_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mollie.settings import ENDPOINTS, MOLLIE_ENDPOINTS


def _make_manager(resume_state: MollieResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(embedded_key: str, items: list[dict[str, Any]], next_url: str | None = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    body: dict[str, Any] = {"count": len(items), "_embedded": {embedded_key: items}, "_links": {}}
    if next_url:
        body["_links"]["next"] = {"href": next_url}
    resp.json.return_value = body
    resp.status_code = 200
    resp.ok = True
    return resp


def _error_response(status_code: int) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.status_code = status_code
    resp.ok = status_code < 400
    resp.raise_for_status.side_effect = requests.HTTPError(f"status {status_code}", response=resp)
    return resp


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            # Org access tokens 4xx without a profileId but are still valid keys.
            (400, True),
            (403, True),
            (401, False),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mollie.mollie.make_tracked_session")
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("live_key") is expected

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mollie.mollie.make_tracked_session")
    def test_validate_credentials_swallows_network_errors(self, mock_session):
        mock_session.return_value.get.side_effect = requests.ConnectionError("boom")
        assert validate_credentials("live_key") is False


class TestGetRows:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mollie.mollie.make_tracked_session")
    def test_paginates_via_hal_next_link(self, mock_session):
        next_url = "https://api.mollie.com/v2/payments?from=tr_next&limit=250"
        mock_session.return_value.get.side_effect = [
            _response("payments", [{"id": "tr_1"}, {"id": "tr_2"}], next_url=next_url),
            _response("payments", [{"id": "tr_3"}]),
        ]

        manager = _make_manager()
        batches = list(get_rows("live_key", "payments", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["tr_1", "tr_2", "tr_3"]
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].next_url == next_url
        assert mock_session.return_value.get.call_args_list[1].args[0] == next_url

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mollie.mollie.make_tracked_session")
    def test_first_request_uses_endpoint_path_and_limit(self, mock_session):
        mock_session.return_value.get.return_value = _response("payment_links", [])

        manager = _make_manager()
        list(get_rows("live_key", "payment_links", mock.MagicMock(), manager))

        url = mock_session.return_value.get.call_args.args[0]
        assert url == "https://api.mollie.com/v2/payment-links?limit=250"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mollie.mollie.make_tracked_session")
    def test_resumes_from_saved_state(self, mock_session):
        mock_session.return_value.get.return_value = _response("payments", [{"id": "tr_9"}])

        resume_url = "https://api.mollie.com/v2/payments?from=tr_resume&limit=250"
        manager = _make_manager(MollieResumeConfig(next_url=resume_url))

        list(get_rows("live_key", "payments", mock.MagicMock(), manager))

        assert mock_session.return_value.get.call_args_list[0].args[0] == resume_url

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mollie.mollie.make_tracked_session")
    def test_empty_response_stops_without_saving_state(self, mock_session):
        mock_session.return_value.get.return_value = _response("payments", [])

        manager = _make_manager()
        batches = list(get_rows("live_key", "payments", mock.MagicMock(), manager))

        assert batches == []
        manager.save_state.assert_not_called()

    @pytest.mark.parametrize("retryable_status", [429, 500, 503])
    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mollie.mollie.make_tracked_session")
    def test_retryable_status_triggers_retry_then_succeeds(self, mock_session, _mock_sleep, retryable_status):
        # tenacity's backoff sleep is patched out so the retry resolves instantly.
        mock_session.return_value.get.side_effect = [
            _error_response(retryable_status),
            _response("payments", [{"id": "tr_1"}]),
        ]

        manager = _make_manager()
        batches = list(get_rows("live_key", "payments", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["tr_1"]
        assert mock_session.return_value.get.call_count == 2

    @mock.patch("tenacity.nap.time.sleep", return_value=None)
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mollie.mollie.make_tracked_session")
    def test_non_retryable_4xx_raises_immediately(self, mock_session, _mock_sleep):
        mock_session.return_value.get.side_effect = [_error_response(403)]

        manager = _make_manager()
        with pytest.raises(requests.HTTPError):
            list(get_rows("live_key", "payments", mock.MagicMock(), manager))

        assert mock_session.return_value.get.call_count == 1

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.mollie.mollie.make_tracked_session")
    def test_missing_embedded_block_yields_nothing(self, mock_session):
        resp = mock.MagicMock()
        resp.json.return_value = {"count": 0, "_links": {}}
        resp.status_code = 200
        resp.ok = True
        mock_session.return_value.get.return_value = resp

        manager = _make_manager()
        assert list(get_rows("live_key", "payments", mock.MagicMock(), manager)) == []


class TestMollieSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = MOLLIE_ENDPOINTS[endpoint]
        response = mollie_source("live_key", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["createdAt"]

    @pytest.mark.parametrize("config", list(MOLLIE_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        assert config.partition_key == "createdAt"
