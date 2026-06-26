from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.checkout_com.checkout_com import (
    PAGE_SIZE,
    CheckoutComResumeConfig,
    _format_timestamp,
    _hosts,
    checkout_com_source,
    get_rows,
    validate_credentials,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.checkout_com.checkout_com"


def _make_manager(resume_state: CheckoutComResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _token_response() -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = {"access_token": "the-token", "expires_in": 3600}
    resp.status_code = 200
    resp.ok = True
    return resp


def _disputes_response(items: list[dict[str, Any]], total: int | None = None) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = {
        "limit": PAGE_SIZE,
        "total_count": total if total is not None else len(items),
        "data": items,
    }
    resp.status_code = 200
    resp.ok = True
    return resp


class TestHosts:
    def test_production_and_sandbox_hosts(self):
        assert _hosts("production")["api"] == "https://api.checkout.com"
        assert _hosts("sandbox")["auth"] == "https://access.sandbox.checkout.com/connect/token"

    def test_invalid_environment_raises(self):
        with pytest.raises(ValueError):
            _hosts("evil")


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
        assert validate_credentials("production", "ack_id", "secret") is True

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_when_token_mint_fails(self, mock_session):
        resp = mock.MagicMock()
        resp.raise_for_status.side_effect = requests.HTTPError("401 Client Error", response=resp)
        mock_session.return_value.post.return_value = resp
        assert validate_credentials("production", "ack_id", "secret") is False

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_on_exception(self, mock_session):
        mock_session.return_value.post.side_effect = Exception("boom")
        assert validate_credentials("production", "ack_id", "secret") is False


class TestGetRows:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_paginates_via_skip_until_total(self, mock_session):
        full_page = [{"id": f"dsp_{i}"} for i in range(PAGE_SIZE)]
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.side_effect = [
            _disputes_response(full_page, total=PAGE_SIZE + 1),
            _disputes_response([{"id": "dsp_last"}], total=PAGE_SIZE + 1),
        ]

        manager = _make_manager()
        batches = list(get_rows("production", "ack_id", "secret", "disputes", mock.MagicMock(), manager))

        assert len(batches) == 2
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].skip == PAGE_SIZE
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert parse_qs(urlparse(urls[0]).query)["skip"] == ["0"]
        assert parse_qs(urlparse(urls[1]).query)["skip"] == [str(PAGE_SIZE)]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_incremental_request_includes_from_filter(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _disputes_response([], total=0)

        manager = _make_manager()
        list(
            get_rows(
                "production",
                "ack_id",
                "secret",
                "disputes",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
            )
        )

        url = mock_session.return_value.get.call_args.args[0]
        assert parse_qs(urlparse(url).query)["from"] == ["2024-01-02T00:00:00Z"]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_remints_token_on_401(self, mock_session):
        expired = mock.MagicMock()
        expired.status_code = 401
        expired.ok = False
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.side_effect = [expired, _disputes_response([{"id": "dsp_1"}])]

        manager = _make_manager()
        batches = list(get_rows("production", "ack_id", "secret", "disputes", mock.MagicMock(), manager))

        assert batches == [[{"id": "dsp_1"}]]
        # One mint at start + one re-mint after the 401.
        assert mock_session.return_value.post.call_count == 2

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_from_saved_skip(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _disputes_response([], total=0)

        manager = _make_manager(CheckoutComResumeConfig(skip=500))
        list(get_rows("production", "ack_id", "secret", "disputes", mock.MagicMock(), manager))

        url = mock_session.return_value.get.call_args.args[0]
        assert parse_qs(urlparse(url).query)["skip"] == ["500"]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_sandbox_uses_sandbox_hosts(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _disputes_response([], total=0)

        manager = _make_manager()
        list(get_rows("sandbox", "ack_id", "secret", "disputes", mock.MagicMock(), manager))

        token_url = mock_session.return_value.post.call_args.args[0]
        assert urlparse(token_url).netloc == "access.sandbox.checkout.com"
        api_url = mock_session.return_value.get.call_args.args[0]
        assert urlparse(api_url).netloc == "api.sandbox.checkout.com"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_empty_response_stops_without_saving_state(self, mock_session):
        mock_session.return_value.post.return_value = _token_response()
        mock_session.return_value.get.return_value = _disputes_response([], total=0)

        manager = _make_manager()
        batches = list(get_rows("production", "ack_id", "secret", "disputes", mock.MagicMock(), manager))

        assert batches == []
        manager.save_state.assert_not_called()


class TestCheckoutComSourceResponse:
    def test_response_metadata(self):
        response = checkout_com_source("production", "ack_id", "secret", "disputes", mock.MagicMock(), _make_manager())

        assert response.name == "disputes"
        assert response.primary_keys == ["id"]
        # Disputes return newest-first — watermark commits only at run end.
        assert response.sort_mode == "desc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["received_on"]
