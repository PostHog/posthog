from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.rollbar.rollbar import (
    KEYSET_PAGE_SIZE,
    RollbarResumeConfig,
    _extract_items,
    _to_int,
    get_rows,
    rollbar_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.rollbar.settings import (
    ENDPOINTS,
    ROLLBAR_ENDPOINTS,
)


def _make_manager(resume_state: RollbarResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _response(data_key: Optional[str], items: list[dict[str, Any]]) -> mock.MagicMock:
    resp = mock.MagicMock()
    result: Any = items if data_key is None else {data_key: items}
    resp.json.return_value = {"err": 0, "result": result}
    resp.status_code = 200
    resp.ok = True
    return resp


class TestToInt:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (123, 123),
            ("123", 123),
            (123.9, 123),
            ("nope", None),
            (True, None),
        ],
    )
    def test_to_int_values(self, value, expected):
        assert _to_int(value) == expected


class TestExtractItems:
    def test_dict_result_with_key(self):
        assert _extract_items({"err": 0, "result": {"items": [{"id": 1}]}}, "items") == [{"id": 1}]

    def test_bare_list_result(self):
        # Defensive: a `result` that is itself a list is returned as-is regardless of data_key.
        assert _extract_items({"err": 0, "result": [{"id": 1}]}, "items") == [{"id": 1}]

    @pytest.mark.parametrize(
        "body",
        [
            {},
            {"err": 1, "message": "nope"},
            {"err": 0, "result": {"items": None}},
            {"err": 0, "result": None},
            "not-a-dict",
        ],
    )
    def test_missing_or_malformed_returns_empty(self, body):
        assert _extract_items(body, "items") == []


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
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.rollbar.rollbar.make_tracked_session")
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("token") is expected

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.rollbar.rollbar.make_tracked_session")
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("token") is False


class TestGetRowsPagePagination:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.rollbar.rollbar.make_tracked_session")
    def test_pages_until_empty(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response("items", [{"id": 1}]),
            _response("items", [{"id": 2}]),
            _response("items", []),
        ]

        manager = _make_manager()
        batches = list(get_rows("token", "items", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == [1, 2]
        # Saved after each yielded page, pointing at the next page.
        assert [call.args[0].page for call in manager.save_state.call_args_list] == [2, 3]
        urls = [call.args[0] for call in mock_session.return_value.get.call_args_list]
        assert parse_qs(urlparse(urls[0]).query)["page"] == ["1"]
        assert parse_qs(urlparse(urls[2]).query)["page"] == ["3"]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.rollbar.rollbar.make_tracked_session")
    def test_resumes_from_saved_page(self, mock_session):
        mock_session.return_value.get.return_value = _response("deploys", [])

        manager = _make_manager(RollbarResumeConfig(page=7))
        list(get_rows("token", "deploys", mock.MagicMock(), manager))

        url = mock_session.return_value.get.call_args.args[0]
        assert parse_qs(urlparse(url).query)["page"] == ["7"]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.rollbar.rollbar.make_tracked_session")
    def test_environments_keyed_result(self, mock_session):
        mock_session.return_value.get.side_effect = [
            _response("environments", [{"id": 1, "environment": "production"}]),
            _response("environments", []),
        ]

        manager = _make_manager()
        batches = list(get_rows("token", "environments", mock.MagicMock(), manager))

        assert batches == [[{"id": 1, "environment": "production"}]]


class TestGetRowsKeyset:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.rollbar.rollbar.make_tracked_session")
    def test_walks_keyset_descending(self, mock_session):
        first_page = [{"id": KEYSET_PAGE_SIZE * 2 - i} for i in range(KEYSET_PAGE_SIZE)]
        second_page = [{"id": 5}]
        mock_session.return_value.get.side_effect = [
            _response("instances", first_page),
            _response("instances", second_page),
        ]

        manager = _make_manager()
        batches = list(get_rows("token", "occurrences", mock.MagicMock(), manager))

        assert len(batches) == 2
        manager.save_state.assert_called_once()
        saved = manager.save_state.call_args.args[0]
        assert saved.last_id == min(item["id"] for item in first_page)
        second_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert parse_qs(urlparse(second_url).query)["lastId"] == [str(saved.last_id)]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.rollbar.rollbar.make_tracked_session")
    def test_incremental_stops_at_watermark(self, mock_session):
        # Page contains rows above and below the watermark — only newer rows
        # are yielded and the walk stops.
        page = [{"id": 100 - i} for i in range(KEYSET_PAGE_SIZE)]
        mock_session.return_value.get.return_value = _response("instances", page)

        manager = _make_manager()
        batches = list(
            get_rows(
                "token",
                "occurrences",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=50,
            )
        )

        yielded_ids = [item["id"] for batch in batches for item in batch]
        assert yielded_ids == [100 - i for i in range(50)]
        assert mock_session.return_value.get.call_count == 1

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.rollbar.rollbar.make_tracked_session")
    def test_incremental_with_no_new_rows_yields_nothing(self, mock_session):
        page = [{"id": 50 - i} for i in range(10)]
        mock_session.return_value.get.return_value = _response("instances", page)

        manager = _make_manager()
        batches = list(
            get_rows(
                "token",
                "occurrences",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value=50,
            )
        )

        assert batches == []

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.rollbar.rollbar.make_tracked_session")
    def test_resumes_from_saved_last_id(self, mock_session):
        mock_session.return_value.get.return_value = _response("instances", [])

        manager = _make_manager(RollbarResumeConfig(last_id=12345))
        list(get_rows("token", "occurrences", mock.MagicMock(), manager))

        url = mock_session.return_value.get.call_args.args[0]
        assert parse_qs(urlparse(url).query)["lastId"] == ["12345"]


class TestRollbarSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = ROLLBAR_ENDPOINTS[endpoint]
        response = rollbar_source("token", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        if config.pagination == "keyset":
            assert response.sort_mode == "desc"
        else:
            assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(ROLLBAR_ENDPOINTS.values()))
    def test_partition_keys_are_stable_event_fields(self, config):
        if config.partition_key:
            assert config.partition_key == "timestamp"
