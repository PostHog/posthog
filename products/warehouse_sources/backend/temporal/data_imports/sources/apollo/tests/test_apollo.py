from datetime import UTC, datetime
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.apollo.apollo import (
    MAX_PAGES,
    PAGE_SIZE,
    ApolloResumeConfig,
    _parse_timestamp,
    apollo_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.apollo.settings import APOLLO_ENDPOINTS, ENDPOINTS

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.apollo.apollo"


def _make_manager(resume_state: ApolloResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(data_key: str, items: list[dict[str, Any]], total_pages: int = 1) -> mock.MagicMock:
    resp = mock.MagicMock()
    resp.json.return_value = {
        data_key: items,
        "pagination": {"page": 1, "per_page": PAGE_SIZE, "total_pages": total_pages},
    }
    resp.status_code = 200
    resp.ok = True
    return resp


class TestParseTimestamp:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("2024-01-02T03:04:05Z", datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)),
            ("2024-01-02T03:04:05+00:00", datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)),
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)),
            ("not-a-date", None),
            (None, None),
        ],
    )
    def test_parse_values(self, value, expected):
        assert _parse_timestamp(value) == expected


class TestValidateCredentials:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_valid_when_logged_in(self, mock_session):
        resp = mock.MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"is_logged_in": True}
        mock_session.return_value.get.return_value = resp

        assert validate_credentials("key") is True

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_when_not_logged_in(self, mock_session):
        resp = mock.MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"is_logged_in": False}
        mock_session.return_value.get.return_value = resp

        assert validate_credentials("key") is False

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_on_error_status(self, mock_session):
        resp = mock.MagicMock()
        resp.status_code = 401
        mock_session.return_value.get.return_value = resp

        assert validate_credentials("key") is False


class TestGetRows:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_paginates_until_total_pages(self, mock_session):
        mock_session.return_value.post.side_effect = [
            _response("contacts", [{"id": "c1", "updated_at": "2024-01-02T00:00:00Z"}], total_pages=2),
            _response("contacts", [{"id": "c2", "updated_at": "2024-01-01T00:00:00Z"}], total_pages=2),
        ]

        manager = _make_manager()
        batches = list(get_rows("key", "contacts", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == ["c1", "c2"]
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].page == 2
        bodies = [call.kwargs["json"] for call in mock_session.return_value.post.call_args_list]
        assert bodies[0]["page"] == 1
        assert bodies[1]["page"] == 2

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_incremental_sorts_desc_and_stops_at_watermark(self, mock_session):
        page = [
            {"id": "new", "updated_at": "2024-06-01T00:00:00Z"},
            {"id": "old", "updated_at": "2024-01-01T00:00:00Z"},
        ]
        mock_session.return_value.post.return_value = _response("contacts", page, total_pages=5)

        manager = _make_manager()
        batches = list(
            get_rows(
                "key",
                "contacts",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 3, 1, tzinfo=UTC),
            )
        )

        # Only the newer row is yielded and the walk stops on crossing.
        assert [item["id"] for batch in batches for item in batch] == ["new"]
        assert mock_session.return_value.post.call_count == 1
        body = mock_session.return_value.post.call_args.kwargs["json"]
        assert body["sort_by_field"] == "contact_updated_at"
        assert body["sort_ascending"] is False

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_opportunities_have_no_sort_fields(self, mock_session):
        mock_session.return_value.post.return_value = _response("opportunities", [])

        manager = _make_manager()
        list(get_rows("key", "opportunities", mock.MagicMock(), manager))

        body = mock_session.return_value.post.call_args.kwargs["json"]
        assert "sort_by_field" not in body

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_from_saved_page(self, mock_session):
        mock_session.return_value.post.return_value = _response("contacts", [])

        manager = _make_manager(ApolloResumeConfig(page=7))
        list(get_rows("key", "contacts", mock.MagicMock(), manager))

        body = mock_session.return_value.post.call_args.kwargs["json"]
        assert body["page"] == 7

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_search_cap_is_logged(self, mock_session):
        mock_session.return_value.post.return_value = _response(
            "contacts", [{"id": "c", "updated_at": "2024-01-01T00:00:00Z"}], total_pages=MAX_PAGES + 10
        )

        manager = _make_manager(ApolloResumeConfig(page=MAX_PAGES))
        logger = mock.MagicMock()
        batches = list(get_rows("key", "contacts", logger, manager))

        assert len(batches) == 1
        logger.error.assert_called_once()

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_search_cap_is_logged_when_total_pages_equals_cap(self, mock_session):
        # Exactly at the cap: the final reachable page coincides with total_pages,
        # so the cap must still be logged rather than swallowed by the total_pages break.
        mock_session.return_value.post.return_value = _response(
            "contacts", [{"id": "c", "updated_at": "2024-01-01T00:00:00Z"}], total_pages=MAX_PAGES
        )

        manager = _make_manager(ApolloResumeConfig(page=MAX_PAGES))
        logger = mock.MagicMock()
        batches = list(get_rows("key", "contacts", logger, manager))

        assert len(batches) == 1
        logger.error.assert_called_once()

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_incremental_keeps_records_without_parseable_updated_at(self, mock_session):
        # A record with a missing updated_at must not be dropped, and must not stop
        # the walk before a genuinely older record is reached.
        page = [
            {"id": "new", "updated_at": "2024-06-01T00:00:00Z"},
            {"id": "no-ts"},
            {"id": "old", "updated_at": "2024-01-01T00:00:00Z"},
        ]
        mock_session.return_value.post.return_value = _response("contacts", page, total_pages=5)

        manager = _make_manager()
        batches = list(
            get_rows(
                "key",
                "contacts",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 3, 1, tzinfo=UTC),
            )
        )

        assert [item["id"] for batch in batches for item in batch] == ["new", "no-ts"]
        assert mock_session.return_value.post.call_count == 1

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_empty_response_stops_without_saving_state(self, mock_session):
        mock_session.return_value.post.return_value = _response("contacts", [])

        manager = _make_manager()
        batches = list(get_rows("key", "contacts", mock.MagicMock(), manager))

        assert batches == []
        manager.save_state.assert_not_called()


class TestApolloSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = APOLLO_ENDPOINTS[endpoint]
        response = apollo_source("key", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == ("desc" if config.sort_by_field else "asc")
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None

    @pytest.mark.parametrize("config", list(APOLLO_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key == "created_at"
