from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.aircall.aircall import (
    AircallResumeConfig,
    _build_params,
    _build_url,
    _to_epoch,
    aircall_source,
    get_rows,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aircall.settings import (
    AIRCALL_ENDPOINTS,
    ENDPOINTS,
)


def _make_manager(resume_state: AircallResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _page(items_key: str, items: list[dict[str, Any]], next_link: str | None) -> dict[str, Any]:
    return {"meta": {"next_page_link": next_link}, items_key: items}


class TestToEpoch:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (1700000000, 1700000000),
            (1700000000.9, 1700000000),
            ("1700000000", 1700000000),
            (datetime(2023, 11, 14, 22, 13, 20, tzinfo=UTC), 1700000000),
            (date(2023, 11, 15), int(datetime(2023, 11, 15, tzinfo=UTC).timestamp())),
            ("not-a-number", None),
            (True, None),
        ],
    )
    def test_to_epoch_values(self, value, expected):
        assert _to_epoch(value) == expected


class TestBuildParams:
    def test_incremental_endpoint_requests_ascending_order(self):
        params = _build_params(AIRCALL_ENDPOINTS["calls"], from_value=None)
        assert params["order"] == "asc"
        assert params["per_page"] == 50
        assert "from" not in params

    def test_from_value_included_when_set(self):
        params = _build_params(AIRCALL_ENDPOINTS["calls"], from_value=1700000000)
        assert params["from"] == 1700000000

    def test_full_refresh_endpoint_without_cursor_has_no_order(self):
        params = _build_params(AIRCALL_ENDPOINTS["teams"], from_value=None)
        assert "order" not in params
        assert "from" not in params


class TestBuildUrl:
    def test_no_params(self):
        assert _build_url("/calls", {}) == "https://api.aircall.io/v1/calls"

    def test_drops_none_values_and_encodes(self):
        url = _build_url("/calls", {"per_page": 50, "from": None, "order": "asc"})
        assert url == "https://api.aircall.io/v1/calls?per_page=50&order=asc"


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
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.aircall.aircall.make_tracked_session")
    def test_validate_credentials_status_mapping(self, mock_session, status_code, expected):
        response = mock.MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("id", "token") is expected

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.aircall.aircall.make_tracked_session")
    def test_validate_credentials_swallows_exceptions(self, mock_session):
        mock_session.return_value.get.side_effect = Exception("boom")
        assert validate_credentials("id", "token") is False


class TestGetRows:
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.aircall.aircall.make_tracked_session")
    def test_paginates_via_next_page_link(self, mock_session):
        pages = [
            _page("users", [{"id": 1}, {"id": 2}], "https://api.aircall.io/v1/users?page=2"),
            _page("users", [{"id": 3}], None),
        ]
        responses = []
        for page in pages:
            resp = mock.MagicMock()
            resp.json.return_value = page
            resp.status_code = 200
            resp.ok = True
            responses.append(resp)
        mock_session.return_value.get.side_effect = responses

        manager = _make_manager()
        batches = list(get_rows("id", "token", "users", mock.MagicMock(), manager))

        assert [item["id"] for batch in batches for item in batch] == [1, 2, 3]
        # State is saved only while a next page exists.
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].next_url == "https://api.aircall.io/v1/users?page=2"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.aircall.aircall.make_tracked_session")
    def test_resumes_from_saved_state(self, mock_session):
        resp = mock.MagicMock()
        resp.json.return_value = _page("users", [{"id": 9}], None)
        resp.status_code = 200
        resp.ok = True
        mock_session.return_value.get.return_value = resp

        resume_url = "https://api.aircall.io/v1/users?page=5"
        manager = _make_manager(AircallResumeConfig(next_url=resume_url))

        list(get_rows("id", "token", "users", mock.MagicMock(), manager))

        assert mock_session.return_value.get.call_args_list[0].args[0] == resume_url

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.aircall.aircall.make_tracked_session")
    def test_reanchors_from_cursor_to_page_around_cap(self, mock_session):
        # First window ends without a next link; the latest started_at is used to issue a
        # fresh `from`-anchored request, then that window ends with no new advancement.
        first_window = _page("calls", [{"id": 1, "started_at": 100}, {"id": 2, "started_at": 200}], None)
        second_window = _page("calls", [{"id": 2, "started_at": 200}], None)

        resp1 = mock.MagicMock(status_code=200, ok=True)
        resp1.json.return_value = first_window
        resp2 = mock.MagicMock(status_code=200, ok=True)
        resp2.json.return_value = second_window
        mock_session.return_value.get.side_effect = [resp1, resp2]

        manager = _make_manager()
        batches = list(get_rows("id", "token", "calls", mock.MagicMock(), manager))

        # Two requests: original window + one re-anchored window.
        assert mock_session.return_value.get.call_count == 2
        second_url = mock_session.return_value.get.call_args_list[1].args[0]
        assert "from=200" in second_url
        # Boundary row re-emitted; merge on primary key dedupes downstream.
        assert [item["id"] for batch in batches for item in batch] == [1, 2, 2]

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.aircall.aircall.make_tracked_session")
    def test_no_reanchor_for_full_refresh_endpoint(self, mock_session):
        resp = mock.MagicMock(status_code=200, ok=True)
        resp.json.return_value = _page("teams", [{"id": 1}], None)
        mock_session.return_value.get.return_value = resp

        manager = _make_manager()
        list(get_rows("id", "token", "teams", mock.MagicMock(), manager))

        assert mock_session.return_value.get.call_count == 1

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.aircall.aircall.make_tracked_session")
    def test_empty_response_stops(self, mock_session):
        resp = mock.MagicMock(status_code=200, ok=True)
        resp.json.return_value = _page("calls", [], None)
        mock_session.return_value.get.return_value = resp

        manager = _make_manager()
        batches = list(get_rows("id", "token", "calls", mock.MagicMock(), manager))

        assert batches == []
        manager.save_state.assert_not_called()


class TestAircallSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        config = AIRCALL_ENDPOINTS[endpoint]
        response = aircall_source("id", "token", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == [config.primary_key]
        assert response.sort_mode == "asc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None

    @pytest.mark.parametrize("config", list(AIRCALL_ENDPOINTS.values()))
    def test_partition_keys_are_stable_creation_fields(self, config):
        if config.partition_key:
            assert config.partition_key in {"started_at", "created_at"}
