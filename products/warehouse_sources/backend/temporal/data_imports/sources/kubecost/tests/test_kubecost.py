from typing import Any

import pytest
import time_machine
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.kubecost.kubecost import (
    KubecostResumeConfig,
    get_rows,
    kubecost_source,
    normalize_host,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kubecost.settings import ENDPOINTS

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.kubecost.kubecost"


def _make_manager(resume_state: KubecostResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(body: Any, status_code: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = body
    resp.status_code = status_code
    resp.ok = status_code < 400
    return resp


def _allocation_set(names: list[str]) -> dict[str, Any]:
    return {
        name: {
            "name": name,
            "window": {"start": "2026-07-14T00:00:00Z", "end": "2026-07-15T00:00:00Z"},
            "totalCost": 1.5,
        }
        for name in names
    }


class TestNormalizeHost:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("https://kubecost.example.com", "https://kubecost.example.com"),
            ("kubecost.example.com", "https://kubecost.example.com"),
            ("https://kubecost.example.com/", "https://kubecost.example.com"),
            # The cost-model API prefix is re-appended per request, so a URL
            # entered with it must not produce `/model/model` paths.
            ("https://kubecost.example.com/model", "https://kubecost.example.com"),
            ("http://kubecost.internal:9090/model/", "http://kubecost.internal:9090"),
        ],
    )
    def test_valid_hosts(self, value, expected):
        assert normalize_host(value) == expected

    @pytest.mark.parametrize("value", ["", "   ", "ftp://example.com", "https://"])
    def test_invalid_hosts_raise(self, value):
        with pytest.raises(ValueError):
            normalize_host(value)


class TestValidateCredentials:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_no_api_key_sends_no_auth_header(self, mock_session):
        mock_session.return_value.get.return_value = _response({"code": 200, "data": [None]})

        is_valid, _ = validate_credentials("https://kubecost.example.com", None)

        assert is_valid is True
        assert mock_session.call_args.kwargs["headers"] is None

    @pytest.mark.parametrize(
        "status_code, expected_error",
        [
            (401, "authentication failed"),
            (403, "authentication failed"),
            (404, "unexpected status"),
        ],
    )
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_http_error_statuses(self, mock_session, status_code, expected_error):
        mock_session.return_value.get.return_value = _response({}, status_code=status_code)

        is_valid, error = validate_credentials("https://kubecost.example.com", "token")

        assert is_valid is False
        assert expected_error in (error or "")

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_error_envelope_fails_validation(self, mock_session):
        mock_session.return_value.get.return_value = _response({"code": 500, "message": "boom"})

        is_valid, error = validate_credentials("https://kubecost.example.com", "token")

        assert is_valid is False
        assert "boom" in (error or "")

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_non_json_response_fails_validation(self, mock_session):
        resp = _response({})
        resp.json.side_effect = ValueError("not json")
        mock_session.return_value.get.return_value = resp

        is_valid, error = validate_credentials("https://kubecost.example.com", "token")

        assert is_valid is False
        assert "did not return a Kubecost API response" in (error or "")

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_unreachable_host_fails_validation(self, mock_session):
        mock_session.return_value.get.side_effect = ConnectionError("nope")

        is_valid, error = validate_credentials("https://kubecost.example.com", "token")

        assert is_valid is False
        assert "Unable to reach" in (error or "")

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_api_key_over_plain_http_fails_before_any_request(self, mock_session):
        # The bearer token must never ride a plaintext connection.
        is_valid, error = validate_credentials("http://kubecost.example.com", "token")

        assert is_valid is False
        assert "https" in (error or "")
        mock_session.return_value.get.assert_not_called()


class TestGetRows:
    @pytest.fixture(autouse=True)
    def _frozen_clock(self):
        with time_machine.travel("2026-07-15T10:00:00Z", tick=False):
            yield

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_flattens_result_sets_and_injects_key_and_window(self, mock_session):
        mock_session.return_value.get.return_value = _response(
            {"code": 200, "data": [_allocation_set(["__idle__", "argocd"])]}
        )

        batches = list(
            get_rows(
                "https://k.example.com",
                "token",
                "allocation_by_namespace",
                mock.MagicMock(),
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value="2026-07-15T00:00:00Z",
            )
        )

        rows = [row for batch in batches for row in batch]
        assert {row["key"] for row in rows} == {"__idle__", "argocd"}
        # The server-reported window is preferred for the composite key columns.
        assert all(row["window_start"] == "2026-07-14T00:00:00Z" for row in rows)
        assert all(row["window_end"] == "2026-07-15T00:00:00Z" for row in rows)
        assert all(row["totalCost"] == 1.5 for row in rows)

    @pytest.mark.parametrize(
        "endpoint, expected_path, expected_aggregate",
        [
            ("allocation_by_namespace", "/model/allocation", "namespace"),
            ("allocation_by_controller", "/model/allocation", "controller"),
            ("allocation_by_pod", "/model/allocation", "pod"),
            ("assets", "/model/assets", None),
        ],
    )
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_endpoint_path_and_params(self, mock_session, endpoint, expected_path, expected_aggregate):
        mock_session.return_value.get.return_value = _response({"code": 200, "data": [None]})

        list(
            get_rows(
                "https://k.example.com",
                "token",
                endpoint,
                mock.MagicMock(),
                _make_manager(KubecostResumeConfig(next_date="2026-07-15")),
            )
        )

        call = mock_session.return_value.get.call_args
        assert call.args[0] == f"https://k.example.com{expected_path}"
        assert call.kwargs["params"].get("aggregate") == expected_aggregate
        assert call.kwargs["params"]["accumulate"] == "true"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_api_key_over_plain_http_raises_before_any_request(self, mock_session):
        with pytest.raises(ValueError, match="https"):
            list(
                get_rows(
                    "http://kubecost.example.com",
                    "token",
                    "allocation_by_namespace",
                    mock.MagicMock(),
                    _make_manager(),
                )
            )
        mock_session.return_value.get.assert_not_called()

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_error_envelope_raises(self, mock_session):
        mock_session.return_value.get.return_value = _response({"code": 400, "message": "bad request"})

        with pytest.raises(ValueError, match="bad request"):
            list(
                get_rows(
                    "https://k.example.com",
                    "token",
                    "allocation_by_namespace",
                    mock.MagicMock(),
                    _make_manager(KubecostResumeConfig(next_date="2026-07-15")),
                )
            )


class TestKubecostSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        response = kubecost_source("https://k.example.com", "token", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        # The result-set key is only unique within one window, so the window
        # start must be part of the composite key.
        assert response.primary_keys == ["key", "window_start"]
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["window_start"]
