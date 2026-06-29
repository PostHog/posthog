from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.productboard.productboard import (
    ProductboardResumeConfig,
    _build_initial_params,
    _build_url,
    _format_incremental_value,
    get_rows,
    productboard_source,
    validate_credentials,
)


def _make_response(json_body: Any, status_code: int = 200) -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = status_code < 400
    response.json.return_value = json_body
    response.text = ""
    return response


def _session_returning(responses: list[mock.MagicMock]) -> mock.MagicMock:
    session = mock.MagicMock()
    session.get.side_effect = responses
    return session


class _FakeBatcher:
    """Yields every batched item immediately so each page boundary exercises the
    save_state-after-yield path that the real (5000-row) batcher only hits at scale."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._items: list[Any] = []

    def batch(self, item: Any) -> None:
        self._items.append(item)

    def should_yield(self, include_incomplete_chunk: bool = False) -> bool:
        return len(self._items) > 0

    def get_table(self) -> list[Any]:
        items = self._items
        self._items = []
        return items


class TestFormatIncrementalValue:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2023, 10, 1, 10, 0, 0, tzinfo=UTC), "2023-10-01T10:00:00Z"),
            (datetime(2023, 10, 1, 10, 0, 0), "2023-10-01T10:00:00Z"),
            (date(2023, 10, 1), "2023-10-01T00:00:00Z"),
            ("2023-10-01T10:00:00Z", "2023-10-01T10:00:00Z"),
            (123, "123"),
        ],
    )
    def test_format(self, value, expected):
        assert _format_incremental_value(value) == expected

    def test_naive_local_offset_is_normalised_to_utc(self):
        # An aware non-UTC datetime is converted to UTC before formatting.
        value = datetime(2023, 10, 1, 12, 0, 0, tzinfo=timezone(timedelta(hours=2)))
        assert _format_incremental_value(value) == "2023-10-01T10:00:00Z"


class TestBuildUrl:
    @pytest.mark.parametrize(
        "base_url, params, expected",
        [
            # No params returns the bare URL.
            ("https://api.productboard.com/v2/notes", {}, "https://api.productboard.com/v2/notes"),
            # The bracket entity-filter key is kept literal.
            (
                "https://api.productboard.com/v2/entities",
                {"type[]": "feature"},
                "https://api.productboard.com/v2/entities?type[]=feature",
            ),
            # Values (e.g. ISO timestamps) are percent-encoded.
            (
                "https://api.productboard.com/v2/notes",
                {"updatedFrom": "2023-10-01T10:00:00Z"},
                "https://api.productboard.com/v2/notes?updatedFrom=2023-10-01T10%3A00%3A00Z",
            ),
        ],
    )
    def test_build_url(self, base_url, params, expected):
        assert _build_url(base_url, params) == expected


class TestBuildInitialParams:
    def test_entity_endpoint_adds_type_filter(self):
        assert _build_initial_params("features", False, None, None) == {"type[]": "feature"}

    def test_entity_endpoint_ignores_incremental(self):
        # Entities have no server-side timestamp filter, so a last value never becomes a param.
        params = _build_initial_params("features", True, datetime(2023, 1, 1, tzinfo=UTC), "createdAt")
        assert params == {"type[]": "feature"}

    @pytest.mark.parametrize(
        "incremental_field, expected_param",
        [
            ("updatedAt", "updatedFrom"),
            ("createdAt", "createdFrom"),
        ],
    )
    def test_notes_incremental_maps_to_server_filter(self, incremental_field, expected_param):
        params = _build_initial_params("notes", True, datetime(2023, 10, 1, 10, 0, 0, tzinfo=UTC), incremental_field)
        assert params == {expected_param: "2023-10-01T10:00:00Z"}

    def test_notes_default_incremental_field(self):
        params = _build_initial_params("notes", True, datetime(2023, 10, 1, 10, 0, 0, tzinfo=UTC), None)
        assert params == {"updatedFrom": "2023-10-01T10:00:00Z"}

    def test_notes_full_refresh_has_no_filter(self):
        assert _build_initial_params("notes", False, None, None) == {}

    def test_notes_incremental_without_last_value_has_no_filter(self):
        assert _build_initial_params("notes", True, None, "updatedAt") == {}


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, json_body, expected",
        [
            (200, {"data": []}, (True, 200, None)),
            (401, {"message": "Unauthorized"}, (False, 401, "Unauthorized")),
            (403, {"message": "Forbidden"}, (False, 403, "Forbidden")),
            (500, {"message": "Server error"}, (False, 500, "Server error")),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.productboard.productboard.make_tracked_session"
    )
    def test_status_mapping(self, mock_session, status_code, json_body, expected):
        mock_session.return_value.get.return_value = _make_response(json_body, status_code)
        assert validate_credentials("token", "/notes") == expected

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.productboard.productboard.make_tracked_session"
    )
    def test_request_exception_returns_message(self, mock_session):
        mock_session.return_value.get.side_effect = requests.exceptions.ConnectionError("boom")
        ok, status, message = validate_credentials("token", "/notes")
        assert ok is False
        assert status is None
        assert "boom" in (message or "")


class TestGetRows:
    def _collect(self, iterator: Iterable[Any]) -> list[Any]:
        return list(iterator)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.productboard.productboard.make_tracked_session"
    )
    def test_paginates_until_no_next_link(self, mock_session):
        page1 = _make_response(
            {
                "data": [{"id": "1"}, {"id": "2"}],
                "links": {"next": "https://api.productboard.com/v2/notes?pageCursor=c2"},
            }
        )
        page2 = _make_response({"data": [{"id": "3"}], "links": {}})
        mock_session.return_value = _session_returning([page1, page2])

        manager = mock.MagicMock()
        manager.can_resume.return_value = False

        rows: list[dict] = []
        for table in get_rows("token", "notes", mock.MagicMock(), manager):
            rows.extend(table.to_pylist())

        assert [r["id"] for r in rows] == ["1", "2", "3"]
        # First page uses the constructed URL, second follows links.next verbatim.
        assert (
            mock_session.return_value.get.call_args_list[0].args[0].startswith("https://api.productboard.com/v2/notes")
        )
        assert mock_session.return_value.get.call_args_list[1].args[0].endswith("pageCursor=c2")

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.productboard.productboard.Batcher",
        _FakeBatcher,
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.productboard.productboard.make_tracked_session"
    )
    def test_checkpoints_current_page_not_next(self, mock_session):
        # The checkpoint must be the page we just processed, so resume re-fetches it and
        # merge-dedupes — never the next page (which would strand still-buffered rows).
        page1_url = "https://api.productboard.com/v2/notes"
        page2_url = "https://api.productboard.com/v2/notes?pageCursor=c2"
        page1 = _make_response({"data": [{"id": "1"}], "links": {"next": page2_url}})
        page2 = _make_response({"data": [{"id": "2"}], "links": {}})
        mock_session.return_value = _session_returning([page1, page2])

        manager = mock.MagicMock()
        manager.can_resume.return_value = False

        list(get_rows("token", "notes", mock.MagicMock(), manager))

        saved = [call.args[0] for call in manager.save_state.call_args_list]
        assert all(isinstance(s, ProductboardResumeConfig) for s in saved)
        # First page's yield checkpoints the first page URL (not page2_url), second the second.
        assert [s.next_url for s in saved] == [page1_url, page2_url]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.productboard.productboard.make_tracked_session"
    )
    def test_resumes_from_saved_state(self, mock_session):
        resume_url = "https://api.productboard.com/v2/notes?pageCursor=resume"
        page = _make_response({"data": [{"id": "9"}], "links": {}})
        mock_session.return_value = _session_returning([page])

        manager = mock.MagicMock()
        manager.can_resume.return_value = True
        manager.load_state.return_value = ProductboardResumeConfig(next_url=resume_url)

        list(get_rows("token", "notes", mock.MagicMock(), manager))

        assert mock_session.return_value.get.call_args_list[0].args[0] == resume_url

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.productboard.productboard.make_tracked_session"
    )
    def test_empty_first_page_yields_nothing(self, mock_session):
        mock_session.return_value = _session_returning([_make_response({"data": [], "links": {}})])
        manager = mock.MagicMock()
        manager.can_resume.return_value = False

        assert list(get_rows("token", "notes", mock.MagicMock(), manager)) == []


class TestProductboardSourceResponse:
    @pytest.mark.parametrize(
        "endpoint, expected_sort, expected_partition_keys",
        [
            ("features", "asc", ["createdAt"]),
            ("notes", "desc", ["createdAt"]),
            ("teams", "asc", ["createdAt"]),
            ("members", "asc", None),
        ],
    )
    def test_source_response_metadata(self, endpoint, expected_sort, expected_partition_keys):
        response = productboard_source("token", endpoint, mock.MagicMock(), mock.MagicMock())

        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == expected_sort
        assert response.partition_keys == expected_partition_keys
        if expected_partition_keys is None:
            assert response.partition_mode is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_format == "week"
