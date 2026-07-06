from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.plaid.plaid import (
    DEFAULT_START_DATE,
    PAGE_SIZE,
    PlaidResumeConfig,
    _base_url,
    _format_date,
    get_rows,
    plaid_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.plaid.settings import ENDPOINTS, PLAID_ENDPOINTS

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.plaid.plaid"


def _make_manager(resume_state: PlaidResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(body: dict[str, Any], status: int = 200) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = body
    resp.status_code = status
    resp.ok = status < 400
    return resp


@pytest.fixture(autouse=True)
def _no_sleep():
    with mock.patch(f"{_MODULE}.time.sleep"):
        yield


class TestBaseUrl:
    @pytest.mark.parametrize(
        "environment, expected",
        [
            ("production", "https://production.plaid.com"),
            ("sandbox", "https://sandbox.plaid.com"),
        ],
    )
    def test_known_environments_return_correct_host(self, environment, expected):
        assert _base_url(environment) == expected

    def test_invalid_environment_raises(self):
        with pytest.raises(ValueError):
            _base_url("evil")


class TestFormatDate:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02"),
            (date(2024, 1, 2), "2024-01-02"),
            ("2024-01-02", "2024-01-02"),
            ("2024-01-02T03:04:05Z", "2024-01-02"),
        ],
    )
    def test_format_values(self, value, expected):
        assert _format_date(value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            (400, False),
            (401, False),
        ],
    )
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        mock_session.return_value.post.return_value = _response({}, status=status_code)

        assert validate_credentials("production", "cid", "sec", "tok") is expected

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_validate_posts_credentials_to_item_get(self, mock_session):
        mock_session.return_value.post.return_value = _response({})

        validate_credentials("production", "cid", "sec", "tok")

        call = mock_session.return_value.post.call_args
        assert call.args[0] == "https://production.plaid.com/item/get"
        assert call.kwargs["json"] == {"client_id": "cid", "secret": "sec", "access_token": "tok"}

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.post.side_effect = Exception("boom")
        assert validate_credentials("production", "cid", "sec", "tok") is False


class TestGetRowsAccounts:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_accounts_single_fetch(self, mock_session):
        mock_session.return_value.post.return_value = _response({"accounts": [{"account_id": "a1"}]})

        manager = _make_manager()
        batches = list(get_rows("production", "cid", "sec", "tok", "accounts", mock.MagicMock(), manager))

        assert batches == [[{"account_id": "a1"}]]
        call = mock_session.return_value.post.call_args
        assert call.args[0].endswith("/accounts/get")


class TestGetRowsTransactions:
    @mock.patch(f"{_MODULE}._today")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_paginates_via_offset_until_total(self, mock_session, mock_today):
        mock_today.return_value = "2024-06-01"
        full_page = [{"transaction_id": str(i), "date": "2024-01-01"} for i in range(PAGE_SIZE)]
        mock_session.return_value.post.side_effect = [
            _response({"transactions": full_page, "total_transactions": PAGE_SIZE + 1}),
            _response(
                {
                    "transactions": [{"transaction_id": "last", "date": "2024-01-02"}],
                    "total_transactions": PAGE_SIZE + 1,
                }
            ),
        ]

        manager = _make_manager()
        batches = list(get_rows("production", "cid", "sec", "tok", "transactions", mock.MagicMock(), manager))

        assert len(batches) == 2
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].offset == PAGE_SIZE
        bodies = [call.kwargs["json"] for call in mock_session.return_value.post.call_args_list]
        assert bodies[0]["options"] == {"count": PAGE_SIZE, "offset": 0}
        assert bodies[1]["options"] == {"count": PAGE_SIZE, "offset": PAGE_SIZE}
        assert bodies[0]["start_date"] == DEFAULT_START_DATE
        assert bodies[0]["end_date"] == "2024-06-01"

    @mock.patch(f"{_MODULE}._today")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_incremental_uses_watermark_as_start_date(self, mock_session, mock_today):
        mock_today.return_value = "2024-06-01"
        mock_session.return_value.post.return_value = _response({"transactions": [], "total_transactions": 0})

        manager = _make_manager()
        list(
            get_rows(
                "production",
                "cid",
                "sec",
                "tok",
                "transactions",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=date(2024, 5, 1),
            )
        )

        body = mock_session.return_value.post.call_args.kwargs["json"]
        assert body["start_date"] == "2024-05-01"

    @mock.patch(f"{_MODULE}._today")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_from_saved_offset(self, mock_session, mock_today):
        mock_today.return_value = "2024-06-01"
        mock_session.return_value.post.return_value = _response({"transactions": [], "total_transactions": 0})

        manager = _make_manager(PlaidResumeConfig(offset=1500))
        list(get_rows("production", "cid", "sec", "tok", "transactions", mock.MagicMock(), manager))

        body = mock_session.return_value.post.call_args.kwargs["json"]
        assert body["options"]["offset"] == 1500

    @mock.patch(f"{_MODULE}._today")
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_empty_response_stops_without_saving_state(self, mock_session, mock_today):
        mock_today.return_value = "2024-06-01"
        mock_session.return_value.post.return_value = _response({"transactions": [], "total_transactions": 0})

        manager = _make_manager()
        batches = list(get_rows("production", "cid", "sec", "tok", "transactions", mock.MagicMock(), manager))

        assert batches == []
        manager.save_state.assert_not_called()


class TestPlaidSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = PLAID_ENDPOINTS[endpoint]
        response = plaid_source("production", "cid", "sec", "tok", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        if endpoint == "transactions":
            # Newest-first ordering — watermark commits only at run end.
            assert response.sort_mode == "desc"
            assert response.partition_mode == "datetime"
            assert response.partition_keys == ["date"]
        else:
            assert response.sort_mode == "asc"
            assert response.partition_mode is None
