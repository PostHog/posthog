from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock, patch

from parameterized import parameterized
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.orb.orb import (
    OrbCursorPaginator,
    OrbResumeConfig,
    _format_incremental_value,
    get_resource,
    orb_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.orb.settings import ENDPOINTS, ORB_ENDPOINTS


def _response(body: dict[str, Any]) -> MagicMock:
    response = MagicMock()
    response.json.return_value = body
    return response


class TestOrbCursorPaginator:
    def test_initial_state(self) -> None:
        paginator = OrbCursorPaginator()
        # BasePaginator starts has_next_page=True so the first request always runs.
        assert paginator.has_next_page is True
        assert paginator._cursor_value is None
        assert paginator.cursor_param == "cursor"

    def test_update_state_has_more(self) -> None:
        paginator = OrbCursorPaginator()
        paginator.update_state(
            _response({"data": [{"id": "c1"}], "pagination_metadata": {"has_more": True, "next_cursor": "cursor-1"}})
        )
        assert paginator._cursor_value == "cursor-1"
        assert paginator.has_next_page is True

    def test_update_state_terminal_page(self) -> None:
        paginator = OrbCursorPaginator()
        paginator.update_state(
            _response({"data": [{"id": "c1"}], "pagination_metadata": {"has_more": False, "next_cursor": None}})
        )
        assert paginator.has_next_page is False

    def test_update_request_adds_cursor_param(self) -> None:
        paginator = OrbCursorPaginator()
        paginator.update_state(
            _response({"data": [], "pagination_metadata": {"has_more": True, "next_cursor": "cursor-2"}})
        )
        request = MagicMock()
        request.params = {"limit": 100}
        paginator.update_request(request)
        assert request.params["cursor"] == "cursor-2"

    @parameterized.expand([("fresh", None), ("resumed", "cursor-99")])
    def test_init_request_honours_seeded_cursor(self, _label: str, seeded_cursor: str | None) -> None:
        paginator = OrbCursorPaginator()
        if seeded_cursor is not None:
            paginator.set_resume_state({"next_cursor": seeded_cursor})

        request = MagicMock()
        request.params = {"limit": 100}
        paginator.init_request(request)

        if seeded_cursor is None:
            assert "cursor" not in request.params
        else:
            assert request.params["cursor"] == seeded_cursor
            assert paginator.has_next_page is True

    def test_resume_state_round_trip(self) -> None:
        paginator = OrbCursorPaginator()
        paginator.update_state(
            _response({"data": [], "pagination_metadata": {"has_more": True, "next_cursor": "cursor-3"}})
        )
        assert paginator.get_resume_state() == {"next_cursor": "cursor-3"}

    def test_no_resume_state_on_terminal_page(self) -> None:
        paginator = OrbCursorPaginator()
        paginator.update_state(_response({"data": [], "pagination_metadata": {"has_more": False, "next_cursor": None}}))
        # No next page => nothing to resume to.
        assert paginator.get_resume_state() is None


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("none_passthrough", None, None),
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14+00:00"),
            ("naive_datetime_assumed_utc", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14+00:00"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00+00:00"),
            ("string_passthrough", "some-cursor", "some-cursor"),
        ]
    )
    def test_format(self, _label: str, value: object, expected: object) -> None:
        assert _format_incremental_value(value) == expected


class TestGetResource:
    @staticmethod
    def _params(resource: Any) -> dict[str, Any]:
        endpoint = cast(dict[str, Any], resource["endpoint"])
        return cast(dict[str, Any], endpoint["params"])

    @parameterized.expand(list(ENDPOINTS))
    def test_resource_shape(self, endpoint: str) -> None:
        cfg = ORB_ENDPOINTS[endpoint]
        resource = get_resource(endpoint, should_use_incremental_field=False)
        endpoint_config = cast(dict[str, Any], resource["endpoint"])
        params = self._params(resource)

        assert resource["name"] == cfg.name
        assert resource["table_name"] == cfg.table_name
        assert resource["table_format"] == "delta"
        assert endpoint_config["path"] == cfg.path
        assert endpoint_config["data_selector"] == "data"
        assert params["limit"] == 100
        # Non-incremental call never sets a timestamp filter and replaces the table.
        assert resource["write_disposition"] == "replace"
        if cfg.incremental_param is not None:
            assert cfg.incremental_param not in params

    @parameterized.expand([e for e in ENDPOINTS if ORB_ENDPOINTS[e].incremental_param is not None])
    def test_incremental_resource_sets_filter_and_merges(self, endpoint: str) -> None:
        cfg = ORB_ENDPOINTS[endpoint]
        assert cfg.incremental_param is not None
        resource = get_resource(endpoint, should_use_incremental_field=True)

        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        param = cast(dict[str, Any], self._params(resource)[cfg.incremental_param])
        assert param["type"] == "incremental"
        assert param["cursor_path"] == cfg.incremental_field
        assert param["convert"] is _format_incremental_value

    @parameterized.expand([e for e in ENDPOINTS if ORB_ENDPOINTS[e].incremental_param is None])
    def test_full_refresh_endpoint_ignores_incremental_flag(self, endpoint: str) -> None:
        # Items / Coupons have no server-side time filter: even with incremental requested they
        # stay full-refresh (replace) so we never silently emit a bogus filter param.
        resource = get_resource(endpoint, should_use_incremental_field=True)
        assert resource["write_disposition"] == "replace"
        assert set(self._params(resource).keys()) == {"limit"}

    def test_invoices_uses_invoice_date_filter(self) -> None:
        resource = get_resource("Invoices", should_use_incremental_field=True)
        params = self._params(resource)
        assert "invoice_date[gt]" in params
        assert "created_at[gt]" not in params


class TestOrbSource:
    def _manager(self, *, can_resume: bool, state: OrbResumeConfig | None = None) -> MagicMock:
        manager = MagicMock(spec=ResumableSourceManager)
        manager.can_resume.return_value = can_resume
        manager.load_state.return_value = state
        return manager

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.orb.orb.rest_api_resource")
    def test_source_response_fields(self, mock_rest: MagicMock) -> None:
        mock_resource = MagicMock()
        mock_resource.name = "Customers"
        mock_resource.column_hints = None
        mock_rest.return_value = mock_resource

        response = orb_source(
            api_key="key",
            endpoint="Customers",
            team_id=1,
            job_id="job",
            resumable_source_manager=self._manager(can_resume=False),
            db_incremental_field_last_value=None,
            should_use_incremental_field=False,
        )

        assert response.name == "Customers"
        assert response.primary_keys == ["id"]
        # Orb always returns newest-first.
        assert response.sort_mode == "desc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.orb.orb.rest_api_resource")
    def test_coupons_has_no_partitioning(self, mock_rest: MagicMock) -> None:
        mock_resource = MagicMock()
        mock_resource.name = "Coupons"
        mock_resource.column_hints = None
        mock_rest.return_value = mock_resource

        response = orb_source(
            api_key="key",
            endpoint="Coupons",
            team_id=1,
            job_id="job",
            resumable_source_manager=self._manager(can_resume=False),
            db_incremental_field_last_value=None,
        )
        # Coupons exposes no stable created_at field, so it can't be partitioned.
        assert response.partition_mode is None
        assert response.partition_keys is None

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.orb.orb.rest_api_resource")
    def test_seeds_initial_paginator_state_from_saved_cursor(self, mock_rest: MagicMock) -> None:
        mock_rest.return_value = MagicMock(name="Customers", column_hints=None)
        manager = self._manager(can_resume=True, state=OrbResumeConfig(next_cursor="saved-cursor"))

        orb_source(
            api_key="key",
            endpoint="Customers",
            team_id=1,
            job_id="job",
            resumable_source_manager=manager,
            db_incremental_field_last_value=None,
        )

        _, kwargs = mock_rest.call_args
        assert kwargs["initial_paginator_state"] == {"next_cursor": "saved-cursor"}

    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.orb.orb.rest_api_resource")
    def test_resume_hook_saves_state_after_batch(self, mock_rest: MagicMock) -> None:
        mock_rest.return_value = MagicMock(name="Customers", column_hints=None)
        manager = self._manager(can_resume=False)

        orb_source(
            api_key="key",
            endpoint="Customers",
            team_id=1,
            job_id="job",
            resumable_source_manager=manager,
            db_incremental_field_last_value=None,
        )

        _, kwargs = mock_rest.call_args
        resume_hook = kwargs["resume_hook"]

        # A page with a next cursor persists; a terminal page (no cursor) saves nothing.
        resume_hook({"next_cursor": "next-1"})
        manager.save_state.assert_called_once_with(OrbResumeConfig(next_cursor="next-1"))

        manager.save_state.reset_mock()
        resume_hook(None)
        manager.save_state.assert_not_called()


class TestValidateCredentials:
    @parameterized.expand([("ok", 200, True), ("unauthorized", 401, False), ("forbidden", 403, False)])
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.orb.orb.make_tracked_session")
    def test_status_mapping(self, _label: str, status_code: int, expected: bool, mock_session: MagicMock) -> None:
        response = MagicMock()
        response.status_code = status_code
        mock_session.return_value.get.return_value = response

        assert validate_credentials("key") is expected

    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    @patch("products.warehouse_sources.backend.temporal.data_imports.sources.orb.orb.make_tracked_session")
    def test_transient_errors_raise(self, _label: str, status_code: int, mock_session: MagicMock) -> None:
        # Transient/unexpected statuses must not be reported as an invalid API key — they raise.
        response = MagicMock()
        response.status_code = status_code
        response.raise_for_status.side_effect = HTTPError
        mock_session.return_value.get.return_value = response

        with pytest.raises(HTTPError):
            validate_credentials("key")
