from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.smartsheet.settings import (
    ENDPOINTS,
    SMARTSHEET_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartsheet.smartsheet import (
    PAGE_SIZE,
    SmartsheetResumeConfig,
    _build_url,
    get_rows,
    smartsheet_source,
    validate_credentials,
)


def _make_manager(resume_state: SmartsheetResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _page(items: list[dict[str, Any]], total_pages: int) -> dict[str, Any]:
    return {"pageNumber": 1, "pageSize": PAGE_SIZE, "totalPages": total_pages, "data": items}


def _ok_response(payload: dict[str, Any]) -> mock.MagicMock:
    resp = mock.MagicMock(status_code=200, ok=True)
    resp.json.return_value = payload
    return resp


class TestBuildUrl:
    def test_includes_pagination_params(self):
        url = _build_url("/sheets", page=1)
        assert url == f"https://api.smartsheet.com/2.0/sheets?page=1&pageSize={PAGE_SIZE}"

    def test_uses_requested_page(self):
        assert "page=4" in _build_url("/reports", page=4)


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected",
        [
            (200, True),
            (401, False),
            (403, False),
            (500, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.smartsheet.smartsheet.make_tracked_session"
    )
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("token") is expected

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.smartsheet.smartsheet.make_tracked_session"
    )
    def test_validate_credentials_probes_users_me(self, mock_session):
        response = mock.MagicMock(status_code=200)
        mock_session.return_value.get.return_value = response

        validate_credentials("token")

        assert mock_session.return_value.get.call_args.args[0] == "https://api.smartsheet.com/2.0/users/me"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.smartsheet.smartsheet.make_tracked_session"
    )
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("token") is False


class TestGetRows:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.smartsheet.smartsheet.make_tracked_session"
    )
    def test_paginates_through_total_pages(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _ok_response(_page([{"id": 1}, {"id": 2}], total_pages=2)),
            _ok_response(_page([{"id": 3}], total_pages=2)),
        ]

        manager = _make_manager()
        batches = list(get_rows("token", "sheets", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == [1, 2, 3]
        # Each request asks for an explicit ascending page number.
        assert "page=1" in mock_session.return_value.get.call_args_list[0].args[0]
        assert "page=2" in mock_session.return_value.get.call_args_list[1].args[0]
        # State is saved once — only while a further page remains.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].next_page == 2

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.smartsheet.smartsheet.make_tracked_session"
    )
    def test_single_page_does_not_save_state(self, mock_session):
        mock_session.return_value.get.return_value = _ok_response(_page([{"id": 1}], total_pages=1))

        manager = _make_manager()
        batches = list(get_rows("token", "sheets", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == [1]
        assert mock_session.return_value.get.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.smartsheet.smartsheet.make_tracked_session"
    )
    def test_empty_response_stops_without_saving(self, mock_session):
        mock_session.return_value.get.return_value = _ok_response(_page([], total_pages=0))

        manager = _make_manager()
        batches = list(get_rows("token", "sheets", mock.MagicMock(), manager))

        assert batches == []
        manager.save_state.assert_not_called()

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.smartsheet.smartsheet.make_tracked_session"
    )
    def test_resumes_from_saved_page(self, mock_session):
        mock_session.return_value.get.return_value = _ok_response(_page([{"id": 9}], total_pages=3))

        manager = _make_manager(SmartsheetResumeConfig(next_page=3))
        list(get_rows("token", "sheets", mock.MagicMock(), manager))

        assert "page=3" in mock_session.return_value.get.call_args_list[0].args[0]


class TestSmartsheetSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = SMARTSHEET_ENDPOINTS[endpoint]
        response = smartsheet_source("token", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(SMARTSHEET_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        # Never partition on a mutable field like modifiedAt.
        if config.partition_key:
            assert config.partition_key == "createdAt"
