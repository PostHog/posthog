from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.pandadoc.pandadoc import (
    PAGE_SIZE,
    PandaDocResumeConfig,
    _build_params,
    _build_url,
    _format_date_filter,
    get_rows,
    pandadoc_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pandadoc.settings import (
    ENDPOINTS,
    PANDADOC_ENDPOINTS,
)


def _make_manager(resume_state: PandaDocResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(items: list[dict[str, Any]]) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = {"results": items}
    resp.status_code = 200
    resp.ok = True
    return resp


class TestFormatDateFilter:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05.000000Z"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05.000000Z"),
            (date(2024, 1, 2), "2024-01-02T00:00:00.000000Z"),
            ("2024-01-02T03:04:05.000000Z", "2024-01-02T03:04:05.000000Z"),
        ],
    )
    def test_format_values(self, value, expected):
        assert _format_date_filter(value) == expected


class TestBuildParams:
    def test_incremental_documents_uses_modified_from_filter(self):
        params = _build_params(
            PANDADOC_ENDPOINTS["documents"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field="date_modified",
            page=1,
        )

        assert params["modified_from"] == "2024-01-01T00:00:00.000000Z"
        assert params["order_by"] == "date_modified"
        assert params["count"] == PAGE_SIZE
        assert params["page"] == 1

    def test_incremental_documents_honors_date_created_cursor(self):
        params = _build_params(
            PANDADOC_ENDPOINTS["documents"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field="date_created",
            page=2,
        )

        assert params["created_from"] == "2024-01-01T00:00:00.000000Z"
        assert params["order_by"] == "date_created"
        assert params["page"] == 2

    def test_incremental_without_last_value_falls_back_to_full_refresh_sort(self):
        params = _build_params(
            PANDADOC_ENDPOINTS["documents"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="date_modified",
            page=1,
        )

        assert "modified_from" not in params
        assert params["order_by"] == "date_created"

    def test_unknown_cursor_field_falls_back_to_full_refresh_sort(self):
        params = _build_params(
            PANDADOC_ENDPOINTS["documents"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field="nope",
            page=1,
        )

        assert params["order_by"] == "date_created"
        assert "modified_from" not in params

    @pytest.mark.parametrize("endpoint", ["templates", "forms", "document_folders", "template_folders"])
    def test_paginated_non_incremental_endpoints_only_page(self, endpoint):
        params = _build_params(
            PANDADOC_ENDPOINTS[endpoint],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
            page=3,
        )

        assert params == {"count": PAGE_SIZE, "page": 3}

    @pytest.mark.parametrize("endpoint", ["contacts", "members"])
    def test_unpaginated_endpoints_have_no_params(self, endpoint):
        params = _build_params(
            PANDADOC_ENDPOINTS[endpoint],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
            page=1,
        )

        assert params == {}


class TestBuildUrl:
    def test_no_params(self):
        assert _build_url("/contacts", {}) == "https://api.pandadoc.com/public/v1/contacts"

    def test_with_params(self):
        url = _build_url("/documents", {"count": 100, "page": 1})
        assert url == "https://api.pandadoc.com/public/v1/documents?count=100&page=1"


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
        "products.warehouse_sources.backend.temporal.data_imports.sources.pandadoc.pandadoc.make_tracked_session"
    )
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("key") is expected

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pandadoc.pandadoc.make_tracked_session"
    )
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key") is False


class TestGetRows:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pandadoc.pandadoc.make_tracked_session"
    )
    def test_paginates_until_short_page(self, mock_session):
        full_page = [{"id": str(i)} for i in range(PAGE_SIZE)]
        mock_session.return_value.get.side_effect = [
            _response(full_page),
            _response([{"id": "last"}]),
        ]

        manager = _make_manager()
        batches = list(get_rows("key", "documents", mock.MagicMock(), manager))

        assert len(batches) == 2
        assert batches[1] == [{"id": "last"}]
        # State saved once, after the first (full) page, pointing at page 2.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].page == 2
        second_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert parse_qs(urlparse(second_url).query)["page"] == ["2"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pandadoc.pandadoc.make_tracked_session"
    )
    def test_resumes_from_saved_page(self, mock_session):
        mock_session.return_value.get.return_value = _response([{"id": "9"}])

        manager = _make_manager(PandaDocResumeConfig(page=5))
        list(get_rows("key", "documents", mock.MagicMock(), manager))

        url = mock_session.return_value.get.call_args.args[0]
        assert parse_qs(urlparse(url).query)["page"] == ["5"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pandadoc.pandadoc.make_tracked_session"
    )
    def test_unpaginated_endpoint_fetches_once(self, mock_session):
        full_page = [{"user_id": str(i)} for i in range(PAGE_SIZE)]
        mock_session.return_value.get.return_value = _response(full_page)

        manager = _make_manager()
        batches = list(get_rows("key", "members", mock.MagicMock(), manager))

        assert len(batches) == 1
        assert mock_session.return_value.get.call_count == 1
        manager.save_state.assert_not_called()

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pandadoc.pandadoc.make_tracked_session"
    )
    def test_incremental_request_includes_filter(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        manager = _make_manager()
        list(
            get_rows(
                "key",
                "documents",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
                incremental_field="date_modified",
            )
        )

        url = mock_session.return_value.get.call_args.args[0]
        query = parse_qs(urlparse(url).query)
        assert query["modified_from"] == ["2024-01-01T00:00:00.000000Z"]
        assert query["order_by"] == ["date_modified"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.pandadoc.pandadoc.make_tracked_session"
    )
    def test_empty_response_stops_without_saving_state(self, mock_session):
        mock_session.return_value.get.return_value = _response([])

        manager = _make_manager()
        batches = list(get_rows("key", "documents", mock.MagicMock(), manager))

        assert batches == []
        manager.save_state.assert_not_called()


class TestPandaDocSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = PANDADOC_ENDPOINTS[endpoint]
        response = pandadoc_source("key", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(PANDADOC_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key == "date_created"
