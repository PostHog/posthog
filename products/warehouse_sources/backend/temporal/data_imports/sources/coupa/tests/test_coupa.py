from datetime import UTC, datetime
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.coupa.coupa import (
    CoupaResumeConfig,
    _normalize_keys,
    get_rows,
    hostname_of,
    normalize_host,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coupa.settings import ENDPOINTS, PAGE_SIZE

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.coupa.coupa"


def _make_manager(resume_state: CoupaResumeConfig | None = None) -> mock.MagicMock:
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
    return _response({"access_token": "tok-1", "token_type": "bearer", "expires_in": 86399})


class TestNormalizeHost:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("https://myorg.coupahost.com", "https://myorg.coupahost.com"),
            ("myorg.coupahost.com", "https://myorg.coupahost.com"),
            ("https://myorg.coupacloud.com/", "https://myorg.coupacloud.com"),
        ],
    )
    def test_valid_hosts(self, value, expected):
        assert normalize_host(value) == expected

    @pytest.mark.parametrize("value", ["", "   ", "ftp://example.com", "https://", "http://myorg.coupahost.com"])
    def test_invalid_hosts_raise(self, value):
        with pytest.raises(ValueError):
            normalize_host(value)

    def test_hostname_of(self):
        assert hostname_of("https://myorg.coupahost.com/api") == "myorg.coupahost.com"


class TestNormalizeKeys:
    def test_hyphenated_keys_become_underscored(self):
        row = {"id": 1, "updated-at": "2024-01-01T00:00:00Z", "invoice-number": "INV-1", "plain": "x"}
        assert _normalize_keys(row) == {
            "id": 1,
            "updated_at": "2024-01-01T00:00:00Z",
            "invoice_number": "INV-1",
            "plain": "x",
        }


class TestValidateCredentials:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_valid_credentials_mint_a_token(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()

        assert validate_credentials("https://myorg.coupahost.com", "cid", "sec") is True
        call = mock_session.return_value.post.call_args
        assert call.args[0] == "https://myorg.coupahost.com/oauth2/token"
        assert call.kwargs["auth"] == ("cid", "sec")
        assert call.kwargs["data"] == {"grant_type": "client_credentials"}

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_credentials(self, mock_session):
        response = _response({}, status_code=401)
        response.raise_for_status.side_effect = Exception("401")
        mock_session.return_value.post.return_value = response

        assert validate_credentials("https://myorg.coupahost.com", "cid", "bad") is False


class TestGetRows:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_mints_endpoint_scoped_token_and_paginates(self, mock_session):
        full_page = [{"id": i, "updated-at": "2024-01-01T00:00:00Z"} for i in range(PAGE_SIZE)]
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.side_effect = [
            _response(full_page),
            _response([{"id": "last", "updated-at": "2024-01-02T00:00:00Z"}]),
        ]

        manager = _make_manager()
        batches = list(get_rows("https://myorg.coupahost.com", "cid", "sec", "invoices", mock.MagicMock(), manager))

        assert [len(batch) for batch in batches] == [PAGE_SIZE, 1]
        # Keys are normalized so the cursor field always exists.
        assert all("updated_at" in row for batch in batches for row in batch)
        token_body = mock_session.return_value.post.call_args.kwargs["data"]
        assert token_body["scope"] == "core.invoice.read"
        second_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert f"offset={PAGE_SIZE}" in second_url
        assert [call.args[0].next_offset for call in manager.save_state.call_args_list] == [PAGE_SIZE]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_scope_rejection_falls_back_to_scopeless_token(self, mock_session):
        scope_rejected = _response({"error": "invalid_scope"}, status_code=400)
        mock_session.return_value.post.side_effect = [scope_rejected, _token_response()]
        mock_session.return_value.get.return_value = _response([])

        list(get_rows("https://myorg.coupahost.com", "cid", "sec", "invoices", mock.MagicMock(), _make_manager()))

        second_token_body = mock_session.return_value.post.call_args_list[1].kwargs["data"]
        assert "scope" not in second_token_body

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_non_scope_400_does_not_fall_back(self, mock_session):
        rejected = _response({"error": "invalid_client"}, status_code=400)
        rejected.raise_for_status.side_effect = Exception("400")
        mock_session.return_value.post.return_value = rejected

        with pytest.raises(Exception):
            list(get_rows("https://myorg.coupahost.com", "cid", "sec", "invoices", mock.MagicMock(), _make_manager()))

        # Only the original (scoped) request is made; no scopeless retry.
        assert mock_session.return_value.post.call_count == 1

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_incremental_passes_updated_at_gt(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _response([])

        list(
            get_rows(
                "https://myorg.coupahost.com",
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
        assert "updated_at%5Bgt%5D=2024-01-02T03%3A04%3A05Z" in url

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_from_saved_offset(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _response([{"id": 1}])

        manager = _make_manager(CoupaResumeConfig(next_offset=150))
        list(get_rows("https://myorg.coupahost.com", "cid", "sec", "invoices", mock.MagicMock(), manager))

        url = mock_session.return_value.get.call_args.args[0]
        assert "offset=150" in url

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_mid_sync_401_re_mints_token(self, mock_session):
        mock_session.return_value.post.side_effect = [_token_response(), _token_response()]
        mock_session.return_value.get.side_effect = [
            _response({}, status_code=401),
            _response([{"id": 1}]),
        ]

        batches = list(
            get_rows("https://myorg.coupahost.com", "cid", "sec", "invoices", mock.MagicMock(), _make_manager())
        )

        assert [row["id"] for batch in batches for row in batch] == [1]
        assert mock_session.return_value.post.call_count == 2

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_session_forces_json_accept_header(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _response([])

        list(get_rows("https://myorg.coupahost.com", "cid", "sec", "users", mock.MagicMock(), _make_manager()))

        # Coupa defaults to XML — the session must be created with Accept: application/json.
        session_headers = mock_session.call_args.kwargs["headers"]
        assert session_headers == {"Accept": "application/json"}


class TestCoupaSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        from products.warehouse_sources.backend.temporal.data_imports.sources.coupa.coupa import coupa_source

        response = coupa_source(
            "https://myorg.coupahost.com", "cid", "sec", endpoint, mock.MagicMock(), _make_manager()
        )

        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Ordering within an updated_at window is undocumented — deferred watermark.
        assert response.sort_mode == "desc"
