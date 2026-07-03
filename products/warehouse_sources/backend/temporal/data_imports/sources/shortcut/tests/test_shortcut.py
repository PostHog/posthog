from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.shortcut.settings import (
    ENDPOINTS,
    SHORTCUT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.shortcut.shortcut import (
    SHORTCUT_BASE_URL,
    ShortcutRetryableError,
    _build_search_body,
    _format_incremental_value,
    _parse_response,
    get_rows,
    shortcut_source,
    validate_credentials,
)


def _make_response(json_data: Any = None, status_code: int = 200) -> mock.Mock:
    response = mock.Mock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 300
    response.json.return_value = json_data
    response.text = str(json_data)
    error_response = Response()
    error_response.status_code = status_code
    response.raise_for_status = mock.Mock(side_effect=HTTPError(f"{status_code} Client Error", response=error_response))
    return response


class TestFormatIncrementalValue:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14Z"),
            (date(2026, 3, 4), "2026-03-04"),
            ("2026-03-04T00:00:00Z", "2026-03-04T00:00:00Z"),
        ],
    )
    def test_format(self, value: Any, expected: str) -> None:
        result = _format_incremental_value(value)
        assert result == expected
        assert "+00:00" not in result


class TestBuildSearchBody:
    def test_no_incremental_returns_empty_body(self) -> None:
        body = _build_search_body(SHORTCUT_ENDPOINTS["stories"], False, None, None)
        assert body == {}

    def test_incremental_without_last_value_returns_empty_body(self) -> None:
        body = _build_search_body(SHORTCUT_ENDPOINTS["stories"], True, None, "updated_at")
        assert body == {}

    @pytest.mark.parametrize(
        "incremental_field, expected_param",
        [
            ("updated_at", "updated_at_start"),
            ("created_at", "created_at_start"),
            (None, "updated_at_start"),
        ],
    )
    def test_maps_field_to_server_side_filter(self, incremental_field: str | None, expected_param: str) -> None:
        body = _build_search_body(
            SHORTCUT_ENDPOINTS["stories"], True, datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC), incremental_field
        )
        assert body == {expected_param: "2026-01-02T03:04:05Z"}

    def test_full_refresh_endpoint_has_no_filter_params(self) -> None:
        # Flat list endpoints expose no incremental params, so even with a cursor we send nothing.
        body = _build_search_body(SHORTCUT_ENDPOINTS["members"], True, datetime(2026, 1, 1, tzinfo=UTC), "updated_at")
        assert body == {}


class TestParseResponse:
    @pytest.mark.parametrize("status_code", [429, 500, 502, 503])
    def test_retryable_statuses_raise(self, status_code: int) -> None:
        with pytest.raises(ShortcutRetryableError):
            _parse_response(_make_response(status_code=status_code), "url", mock.Mock())

    @pytest.mark.parametrize("status_code", [400, 401, 403, 404])
    def test_client_errors_raise_for_status(self, status_code: int) -> None:
        with pytest.raises(HTTPError):
            _parse_response(_make_response(status_code=status_code), "url", mock.Mock())

    def test_success_returns_json(self) -> None:
        result = _parse_response(_make_response(json_data=[{"id": 1}]), "url", mock.Mock())
        assert result == [{"id": 1}]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        "status_code, expected_valid",
        [
            (200, True),
            (401, False),
            (403, False),
            (418, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shortcut.shortcut.make_tracked_session"
    )
    def test_status_mapping(self, mock_session_factory, status_code: int, expected_valid: bool) -> None:
        session = mock.Mock()
        session.get.return_value = _make_response(json_data={"id": "x"}, status_code=status_code)
        mock_session_factory.return_value.__enter__.return_value = session

        is_valid, error = validate_credentials("token")

        assert is_valid is expected_valid
        if expected_valid:
            assert error is None
        else:
            assert error is not None
        session.get.assert_called_once()
        assert session.get.call_args[0][0] == f"{SHORTCUT_BASE_URL}/member"


class TestGetRows:
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shortcut.shortcut.make_tracked_session"
    )
    def test_get_endpoint_yields_full_list(self, mock_session_factory) -> None:
        session = mock.Mock()
        rows = [{"id": 1}, {"id": 2}]
        session.request.return_value = _make_response(json_data=rows)
        mock_session_factory.return_value.__enter__.return_value = session

        batches = list(get_rows("token", "members", mock.Mock()))

        assert batches == [rows]
        method, url = session.request.call_args[0]
        assert method == "GET"
        assert url == f"{SHORTCUT_BASE_URL}/members"
        assert session.request.call_args.kwargs["json"] is None

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shortcut.shortcut.make_tracked_session"
    )
    def test_stories_uses_post_with_incremental_body(self, mock_session_factory) -> None:
        session = mock.Mock()
        session.request.return_value = _make_response(json_data=[{"id": 10}])
        mock_session_factory.return_value.__enter__.return_value = session

        batches = list(
            get_rows(
                "token",
                "stories",
                mock.Mock(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
                incremental_field="updated_at",
            )
        )

        assert batches == [[{"id": 10}]]
        method, url = session.request.call_args[0]
        assert method == "POST"
        assert url == f"{SHORTCUT_BASE_URL}/stories/search"
        assert session.request.call_args.kwargs["json"] == {"updated_at_start": "2026-01-02T03:04:05Z"}

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shortcut.shortcut.make_tracked_session"
    )
    def test_empty_list_yields_nothing(self, mock_session_factory) -> None:
        session = mock.Mock()
        session.request.return_value = _make_response(json_data=[])
        mock_session_factory.return_value.__enter__.return_value = session

        assert list(get_rows("token", "epics", mock.Mock())) == []

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shortcut.shortcut.make_tracked_session"
    )
    def test_non_list_response_yields_nothing(self, mock_session_factory) -> None:
        session = mock.Mock()
        session.request.return_value = _make_response(json_data={"unexpected": "shape"})
        mock_session_factory.return_value.__enter__.return_value = session
        logger = mock.Mock()

        assert list(get_rows("token", "epics", logger)) == []
        logger.warning.assert_called_once()


class TestShortcutSource:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_source_response_shape(self, endpoint: str) -> None:
        response = shortcut_source("token", endpoint, mock.Mock())

        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Every endpoint partitions on the stable created_at field.
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]
        assert response.partition_format == "month"

    def test_stories_is_the_only_incremental_endpoint(self) -> None:
        # Sanity check that mirrors the schema-level contract in the settings catalog.
        incremental = {name for name, cfg in SHORTCUT_ENDPOINTS.items() if cfg.incremental_params}
        assert incremental == {"stories"}
