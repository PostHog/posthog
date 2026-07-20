from datetime import date, datetime
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.justcall.justcall import (
    JustCallResumeConfig,
    _build_params,
    _build_url,
    _format_cursor,
    get_rows,
    justcall_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.justcall.settings import (
    ENDPOINTS,
    JUSTCALL_ENDPOINTS,
)

MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.justcall.justcall"


def _make_manager(resume_state: JustCallResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _page(items: list[dict[str, Any]]) -> dict[str, Any]:
    return {"data": items, "next_page_link": None}


def _responses(pages: list[dict[str, Any]]) -> list[mock.MagicMock]:
    out = []
    for page in pages:
        resp = mock.MagicMock(status_code=200, ok=True)
        resp.json.return_value = page
        out.append(resp)
    return out


class TestFormatCursor:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            ("", None),
            ("   ", None),
            ("2021-08-25", "2021-08-25"),
            ("2021-08-25 10:30:00", "2021-08-25"),
            ("2021-08-25T10:30:00", "2021-08-25"),
            (date(2021, 8, 25), "2021-08-25"),
            (datetime(2021, 8, 25, 10, 30, 0), "2021-08-25"),
        ],
    )
    def test_format_cursor(self, value, expected):
        assert _format_cursor(value) == expected


class TestBuildParams:
    def test_incremental_endpoint_sorts_by_datetime_ascending(self):
        params = _build_params(JUSTCALL_ENDPOINTS["calls"], page=0, from_value=None)
        assert params["sort"] == "datetime"
        assert params["order"] == "asc"
        assert params["per_page"] == 100
        assert params["page"] == 0
        assert "from_datetime" not in params

    def test_incremental_endpoint_includes_from_datetime_when_set(self):
        params = _build_params(JUSTCALL_ENDPOINTS["calls"], page=2, from_value="2021-08-25")
        assert params["from_datetime"] == "2021-08-25"
        assert params["page"] == 2

    def test_full_refresh_endpoint_has_no_sort_or_filter(self):
        params = _build_params(JUSTCALL_ENDPOINTS["users"], page=0, from_value="2021-08-25")
        assert "sort" not in params
        # A full-refresh endpoint never carries a time filter, even if a value is passed in.
        assert "from_datetime" not in params

    def test_phone_numbers_uses_uppercase_order(self):
        params = _build_params(JUSTCALL_ENDPOINTS["phone_numbers"], page=0, from_value=None)
        assert params["order"] == "ASC"


class TestBuildUrl:
    def test_no_params(self):
        assert _build_url("/calls", {}) == "https://api.justcall.io/v2.1/calls"

    def test_drops_none_and_encodes(self):
        url = _build_url("/calls", {"page": 0, "per_page": 100, "from_datetime": None})
        assert url == "https://api.justcall.io/v2.1/calls?page=0&per_page=100"


class TestValidateCredentials:
    @pytest.mark.parametrize("status_code, expected", [(200, True), (401, False), (403, False), (500, False)])
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock(status_code=status_code)
        mock_session.return_value.get.return_value = response
        assert validate_credentials("key", "secret") is expected

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("key", "secret") is False


class TestGetRows:
    @mock.patch(f"{MODULE}.PAGE_SIZE", 2)
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_paginates_until_short_page(self, mock_session):
        # Full page (== PAGE_SIZE) continues; a short page ends pagination.
        mock_session.return_value.get.side_effect = _responses([_page([{"id": 1}, {"id": 2}]), _page([{"id": 3}])])

        manager = _make_manager()
        batches = list(get_rows("key", "secret", "users", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == [1, 2, 3]
        assert mock_session.return_value.get.call_count == 2
        # Each yielded page is checkpointed after it is yielded, by its own page number.
        assert manager.save_state.call_args_list == [
            mock.call(JustCallResumeConfig(page=0)),
            mock.call(JustCallResumeConfig(page=1)),
        ]

    @mock.patch(f"{MODULE}.PAGE_SIZE", 2)
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_empty_first_page_stops_without_saving(self, mock_session):
        mock_session.return_value.get.side_effect = _responses([_page([])])

        manager = _make_manager()
        batches = list(get_rows("key", "secret", "calls", mock.MagicMock(), manager))

        assert batches == []
        manager.save_state.assert_not_called()

    @mock.patch(f"{MODULE}.PAGE_SIZE", 2)
    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_resumes_from_saved_page(self, mock_session):
        mock_session.return_value.get.side_effect = _responses([_page([{"id": 9}])])

        manager = _make_manager(JustCallResumeConfig(page=5))
        list(get_rows("key", "secret", "calls", mock.MagicMock(), manager))

        requested_url = mock_session.return_value.get.call_args_list[0].args[0]
        assert "page=5" in requested_url

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_incremental_request_carries_from_datetime(self, mock_session):
        mock_session.return_value.get.side_effect = _responses([_page([{"id": 1, "call_user_date": "2021-08-25"}])])

        manager = _make_manager()
        list(
            get_rows(
                "key",
                "secret",
                "calls",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value="2021-08-25",
            )
        )

        url = mock_session.return_value.get.call_args_list[0].args[0]
        assert "from_datetime=2021-08-25" in url
        assert "sort=datetime" in url

    @mock.patch(f"{MODULE}.make_tracked_session")
    def test_full_refresh_endpoint_ignores_incremental_value(self, mock_session):
        # `users` has no server-side time filter, so an incremental value must not leak into the request.
        mock_session.return_value.get.side_effect = _responses([_page([{"id": 1}])])

        manager = _make_manager()
        list(
            get_rows(
                "key",
                "secret",
                "users",
                mock.MagicMock(),
                manager,
                should_use_incremental_field=True,
                db_incremental_field_last_value="2021-08-25",
            )
        )

        url = mock_session.return_value.get.call_args_list[0].args[0]
        assert "from_datetime" not in url


class TestJustCallSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = JUSTCALL_ENDPOINTS[endpoint]
        response = justcall_source("key", "secret", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        if config.incremental_cursor:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.incremental_cursor]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(JUSTCALL_ENDPOINTS.values()))
    def test_partition_keys_are_stable_user_date_fields(self, config):
        if config.incremental_cursor:
            assert config.incremental_cursor in {"call_user_date", "sms_user_date"}
