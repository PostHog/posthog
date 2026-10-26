from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock

from parameterized import parameterized
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.orb import OrbSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.orb.orb import (
    OrbCursorPaginator,
    OrbResumeConfig,
    _format_incremental_value,
    get_resource,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.orb.settings import ENDPOINTS, ORB_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.orb.source import OrbSource


def _response(body: dict[str, Any]) -> MagicMock:
    response = MagicMock()
    response.json.return_value = body
    return response


class TestOrbCursorPaginator:
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


class TestOrbSource:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(OrbSource(), OrbSourceConfig(api_key="key"))

    @staticmethod
    def _page(rows: list[dict[str, Any]], next_cursor: str | None = None) -> ScriptedResponse:
        return ScriptedResponse(
            json={
                "data": rows,
                "pagination_metadata": {"has_more": next_cursor is not None, "next_cursor": next_cursor},
            }
        )

    def test_seeds_initial_paginator_state_from_saved_cursor(self) -> None:
        result = self._driver().run(
            "Customers",
            [self._page([{"id": "customer-2"}])],
            resume_state=OrbResumeConfig(next_cursor="saved-cursor"),
        )

        assert result.raised is None
        assert result.params("cursor") == ["saved-cursor"]
        assert result.rows == [{"id": "customer-2"}]

    def test_resume_hook_saves_state_after_batch(self) -> None:
        result = self._driver().run(
            "Customers",
            [
                self._page([{"id": "customer-1"}], next_cursor="next-1"),
                self._page([{"id": "customer-2"}]),
            ],
        )

        # A page with a next cursor persists; a terminal page (no cursor) saves nothing.
        assert result.raised is None
        assert result.params("cursor") == [None, "next-1"]
        assert result.rows == [{"id": "customer-1"}, {"id": "customer-2"}]
        assert result.saved_states == [OrbResumeConfig(next_cursor="next-1")]
        assert result.committed_states == [OrbResumeConfig(next_cursor="next-1")]


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_status_mapping(self, _label: str, status_code: int, expected: bool) -> None:
        with scripted_network([ScriptedResponse(status=status_code)]) as network:
            assert validate_credentials("key") is expected

        assert len(network.requests_log) == 1
        assert network.requests_log[0].path == "/v1/customers"
        assert network.requests_log[0].param("limit") == "1"
        assert network.requests_log[0].headers["authorization"] == "Bearer key"

    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_transient_errors_raise(self, _label: str, status_code: int) -> None:
        # Transient/unexpected statuses must not be reported as an invalid API key — they raise.
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            with pytest.raises(HTTPError):
                validate_credentials("key")

        assert {request.path for request in network.requests_log} == {"/v1/customers"}
