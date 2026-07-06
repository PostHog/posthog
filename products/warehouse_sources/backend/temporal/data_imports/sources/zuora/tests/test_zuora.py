from datetime import UTC, datetime
from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.zuora.settings import (
    ENDPOINTS,
    ZUORA_ENDPOINTS,
    ZUORA_ENVIRONMENT_HOSTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.zuora.zuora import (
    ZuoraResumeConfig,
    _base_url,
    get_rows,
    validate_credentials,
    zuora_source,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.zuora.zuora"


def _make_manager(resume_state: ZuoraResumeConfig | None = None) -> mock.MagicMock:
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


def _token_response() -> mock.MagicMock:
    return _response({"access_token": "tok-1", "token_type": "bearer", "expires_in": 3599})


class TestBaseUrl:
    @pytest.mark.parametrize("environment, expected", list(ZUORA_ENVIRONMENT_HOSTS.items()))
    def test_environment_hosts(self, environment, expected):
        assert _base_url(environment) == expected

    def test_invalid_environment_raises(self):
        with pytest.raises(ValueError):
            _base_url("nope")


class TestValidateCredentials:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_valid_credentials_mint_a_token(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()

        assert validate_credentials("us_production", "cid", "sec") is True
        call = mock_session.return_value.post.call_args
        assert call.args[0] == "https://rest.zuora.com/oauth/token"
        assert call.kwargs["data"] == {"grant_type": "client_credentials", "client_id": "cid", "client_secret": "sec"}

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_credentials(self, mock_session):
        response = _response({}, status_code=401)
        response.raise_for_status.side_effect = requests.HTTPError("401", response=requests.Response())
        mock_session.return_value.post.return_value = response

        assert validate_credentials("us_production", "cid", "bad") is False

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_network_error_propagates(self, mock_session):
        # A transient network failure must not be reported as invalid credentials.
        mock_session.return_value.post.side_effect = requests.ConnectionError("boom")

        with pytest.raises(requests.ConnectionError):
            validate_credentials("us_production", "cid", "sec")

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_sandbox_environment_uses_sandbox_host(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()

        validate_credentials("eu_sandbox", "cid", "sec")

        assert mock_session.return_value.post.call_args.args[0] == "https://rest.sandbox.eu.zuora.com/oauth/token"


class TestGetRows:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_paginates_with_next_page_cursor(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.side_effect = [
            _response({"data": [{"id": "a1"}], "nextPage": "cur-1"}),
            _response({"data": [{"id": "a2"}], "nextPage": None}),
        ]

        manager = _make_manager()
        batches = list(get_rows("us_production", "cid", "sec", "accounts", mock.MagicMock(), manager))

        assert [row["id"] for batch in batches for row in batch] == ["a1", "a2"]
        first_url = mock_session.return_value.get.call_args_list[0].args[0]
        assert first_url.startswith("https://rest.zuora.com/object-query/accounts?")
        assert "pageSize=99" in first_url
        assert "sort%5B%5D=updateddate.ASC" in first_url
        second_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert "cursor=cur-1" in second_url
        # The cursor encodes the full query context, so the original params are dropped.
        assert "pageSize" not in second_url
        assert "sort%5B%5D" not in second_url
        assert [call.args[0].cursor for call in manager.save_state.call_args_list] == ["cur-1"]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_incremental_passes_updateddate_gt_filter(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _response({"data": [], "nextPage": None})

        list(
            get_rows(
                "us_production",
                "cid",
                "sec",
                "invoices",
                mock.MagicMock(),
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC),
            )
        )

        url = mock_session.return_value.get.call_args.args[0]
        assert "filter%5B%5D=updateddate.GT%3A2024-01-02T03%3A04%3A05Z" in url

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_from_saved_cursor(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _response({"data": [{"id": "a9"}], "nextPage": None})

        manager = _make_manager(ZuoraResumeConfig(cursor="cur-9"))
        list(get_rows("us_production", "cid", "sec", "accounts", mock.MagicMock(), manager))

        url = mock_session.return_value.get.call_args.args[0]
        assert "cursor=cur-9" in url

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_mid_sync_401_re_mints_token(self, mock_session):
        mock_session.return_value.post.side_effect = [_token_response(), _token_response()]
        mock_session.return_value.get.side_effect = [
            _response({}, status_code=401),
            _response({"data": [{"id": "a1"}], "nextPage": None}),
        ]

        batches = list(get_rows("us_production", "cid", "sec", "accounts", mock.MagicMock(), _make_manager()))

        assert [row["id"] for batch in batches for row in batch] == ["a1"]
        assert mock_session.return_value.post.call_count == 2

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_hyphenated_object_paths(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _response({"data": [], "nextPage": None})

        list(get_rows("us_production", "cid", "sec", "credit_memos", mock.MagicMock(), _make_manager()))

        url = mock_session.return_value.get.call_args.args[0]
        assert "/object-query/credit-memos?" in url


class TestZuoraSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        response = zuora_source("us_production", "cid", "sec", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Pages are requested sorted ascending by updateddate.
        assert response.sort_mode == "asc"

    def test_all_endpoints_have_paths(self):
        assert set(ENDPOINTS) == set(ZUORA_ENDPOINTS.keys())
