from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.ramp.ramp import (
    PAGE_SIZE,
    RampResumeConfig,
    _base_url,
    _format_timestamp,
    get_rows,
    ramp_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ramp.settings import (
    ENDPOINTS,
    RAMP_ENDPOINTS,
    TOKEN_SCOPES,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.ramp.ramp"


def _make_manager(resume_state: RampResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _token_response() -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = {"access_token": "the-token", "expires_in": 864000}
    resp.status_code = 200
    resp.ok = True
    return resp


def _page_response(items: list[dict[str, Any]], next_url: str | None = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = {"data": items, "page": {"next": next_url}}
    resp.status_code = 200
    resp.ok = True
    return resp


class TestBaseUrl:
    def test_production_and_sandbox_hosts(self):
        assert _base_url("production") == "https://api.ramp.com"
        assert _base_url("sandbox") == "https://demo-api.ramp.com"

    def test_invalid_environment_raises(self):
        with pytest.raises(ValueError):
            _base_url("evil")


class TestFormatTimestamp:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05Z"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05Z"),
            (date(2024, 1, 2), "2024-01-02T00:00:00Z"),
            ("2024-01-02T03:04:05Z", "2024-01-02T03:04:05Z"),
        ],
    )
    def test_format_values(self, value, expected):
        assert _format_timestamp(value) == expected


class TestValidateCredentials:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_valid_when_token_mints(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        assert validate_credentials("production", "cid", "sec") == (True, None)

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_mint_requests_documented_scopes(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()

        validate_credentials("production", "cid", "sec")

        body = mock_session.return_value.post.call_args.kwargs["data"]
        assert body == {"grant_type": "client_credentials", "scope": TOKEN_SCOPES}
        assert mock_session.return_value.post.call_args.kwargs["auth"] == ("cid", "sec")

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_when_token_mint_rejected(self, mock_session):
        error_response = mock.MagicMock()
        error_response.status_code = 401
        resp = mock.MagicMock()
        resp.raise_for_status.side_effect = requests.HTTPError("401 Client Error", response=error_response)
        mock_session.return_value.post.return_value = resp

        is_valid, message = validate_credentials("production", "cid", "sec")
        assert is_valid is False
        assert "credentials" in (message or "")

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_transient_error_is_not_reported_as_invalid_credentials(self, mock_session):
        mock_session.return_value.post.side_effect = requests.ConnectionError("connection refused")

        is_valid, message = validate_credentials("production", "cid", "sec")
        assert is_valid is False
        assert "Could not reach Ramp" in (message or "")


class TestGetRows:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_paginates_via_page_next_url(self, mock_session):
        next_url = "https://api.ramp.com/developer/v1/transactions?start=abc&page_size=100"
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.side_effect = [
            _page_response([{"id": "t1"}], next_url=next_url),
            _page_response([{"id": "t2"}]),
        ]

        manager = _make_manager()
        batches = list(get_rows("production", "cid", "sec", "transactions", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["t1", "t2"]
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].next_url == next_url
        assert mock_session.return_value.get.call_args_list[1].args[0] == next_url

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_incremental_transactions_use_from_date(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _page_response([])

        manager = _make_manager()
        list(
            get_rows(
                "production",
                "cid",
                "sec",
                "transactions",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
            )
        )

        url = mock_session.return_value.get.call_args.args[0]
        query = parse_qs(urlparse(url).query)
        assert query["from_date"] == ["2024-01-02T00:00:00Z"]
        assert query["page_size"] == [str(PAGE_SIZE)]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_full_refresh_has_no_from_date(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _page_response([])

        manager = _make_manager()
        list(get_rows("production", "cid", "sec", "users", mock.MagicMock(), manager))

        url = mock_session.return_value.get.call_args.args[0]
        assert urlparse(url).path == "/developer/v1/users"
        assert "from_date" not in parse_qs(urlparse(url).query)

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_remints_token_on_401(self, mock_session):
        expired = mock.MagicMock()
        expired.status_code = 401
        expired.ok = False
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.side_effect = [expired, _page_response([{"id": "t1"}])]

        manager = _make_manager()
        batches = list(get_rows("production", "cid", "sec", "transactions", mock.MagicMock(), manager))

        assert batches == [[{"id": "t1"}]]
        assert mock_session.return_value.post.call_count == 2

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_from_saved_url(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _page_response([])

        resume_url = "https://api.ramp.com/developer/v1/transactions?start=resume"
        manager = _make_manager(RampResumeConfig(next_url=resume_url))
        list(get_rows("production", "cid", "sec", "transactions", mock.MagicMock(), manager))

        assert mock_session.return_value.get.call_args_list[0].args[0] == resume_url

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_empty_page_with_next_url_stops(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _page_response(
            [], next_url="https://api.ramp.com/developer/v1/transactions?start=loop"
        )

        manager = _make_manager()
        batches = list(get_rows("production", "cid", "sec", "transactions", mock.MagicMock(), manager))

        assert batches == []
        manager.save_state.assert_not_called()

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_rejects_off_host_next_url(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _page_response(
            [{"id": "t1"}], next_url="https://evil.example.com/developer/v1/transactions"
        )

        manager = _make_manager()
        with pytest.raises(ValueError):
            list(get_rows("production", "cid", "sec", "transactions", mock.MagicMock(), manager))

        manager.save_state.assert_not_called()

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_rejects_off_host_resume_url(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()

        manager = _make_manager(RampResumeConfig(next_url="https://evil.example.com/developer/v1/transactions"))
        with pytest.raises(ValueError):
            list(get_rows("production", "cid", "sec", "transactions", mock.MagicMock(), manager))


class TestRampSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = RAMP_ENDPOINTS[endpoint]
        response = ramp_source("production", "cid", "sec", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        # Ordering within incremental windows is undocumented — desc defers
        # the watermark commit to run completion.
        assert response.sort_mode == ("desc" if config.incremental_fields else "asc")
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None

    @pytest.mark.parametrize("config", list(RAMP_ENDPOINTS.values()))
    def test_partition_keys_are_stable_fields(self, config):
        if config.partition_key:
            assert config.partition_key == "user_transaction_time"
