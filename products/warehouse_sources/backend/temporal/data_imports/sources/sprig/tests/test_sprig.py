from datetime import UTC, date, datetime
from typing import Any, cast

import pytest
from unittest.mock import MagicMock

from parameterized import parameterized
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.paginators import (
    JSONResponseCursorPaginator,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sprig import SprigSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sprig.settings import (
    ENDPOINTS,
    SPRIG_API_BASE_URL,
    SPRIG_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sprig.source import SprigSource
from products.warehouse_sources.backend.temporal.data_imports.sources.sprig.sprig import (
    SprigRedirectError,
    SprigResumeConfig,
    _format_incremental_value,
    get_resource,
    validate_credentials,
)


def _response(body: dict[str, Any]) -> MagicMock:
    response = MagicMock()
    response.json.return_value = body
    return response


def _run(
    script: list[ScriptedResponse], resume_state: SprigResumeConfig | None = None, endpoint: str = "Surveys"
) -> DriveResult:
    return SourceDriver(SprigSource(), SprigSourceConfig(api_key="key")).run(
        endpoint, script, resume_state=resume_state
    )


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("none_passthrough", None, None),
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), 1772593094000),
            ("naive_datetime_assumed_utc", datetime(2026, 3, 4, 2, 58, 14), 1772593094000),
            ("date_value", date(2026, 3, 4), 1772582400000),
            ("int_passthrough", 1772582400000, 1772582400000),
            ("float_truncated", 1772582400000.9, 1772582400000),
            ("iso_string", "2026-03-04T02:58:14+00:00", 1772593094000),
            ("garbage_string", "not-a-date", None),
        ]
    )
    def test_format(self, _label: str, value: Any, expected: Any) -> None:
        assert _format_incremental_value(value) == expected


class TestGetResource:
    @staticmethod
    def _params(resource: Any) -> dict[str, Any]:
        endpoint = cast(dict[str, Any], resource["endpoint"])
        return cast(dict[str, Any], endpoint["params"])

    @parameterized.expand(
        [
            ("Surveys", 1000),
            ("Responses", 1000),
            # The themes spec takes no `limit` param.
            ("Themes", None),
        ]
    )
    def test_resource_shape(self, endpoint: str, expected_limit: int | None) -> None:
        cfg = SPRIG_ENDPOINTS[endpoint]
        resource = get_resource(endpoint, should_use_incremental_field=False)
        endpoint_config = cast(dict[str, Any], resource["endpoint"])
        params = self._params(resource)

        assert resource["name"] == cfg.name
        assert resource["table_name"] == cfg.table_name
        assert resource["table_format"] == "delta"
        assert endpoint_config["path"] == cfg.path
        assert endpoint_config["data_selector"] == "data"
        assert params.get("limit") == expected_limit
        assert "start" not in params
        assert resource["write_disposition"] == "replace"

    @parameterized.expand([name for name in ENDPOINTS if SPRIG_ENDPOINTS[name].supports_incremental])
    def test_incremental_resource_sets_filter_and_merges(self, endpoint: str) -> None:
        resource = get_resource(endpoint, should_use_incremental_field=True)

        assert resource["write_disposition"] == {"disposition": "merge", "strategy": "upsert"}
        param = cast(dict[str, Any], self._params(resource)["start"])
        assert param["type"] == "incremental"
        assert param["cursor_path"] == "createdAt"
        assert param["convert"] is _format_incremental_value

    def test_full_refresh_only_endpoint_ignores_incremental_flag(self) -> None:
        resource = get_resource("Themes", should_use_incremental_field=True)

        assert resource["write_disposition"] == "replace"
        assert "start" not in self._params(resource)


class TestSprigCursorPaginator:
    def _paginator(self) -> JSONResponseCursorPaginator:
        return JSONResponseCursorPaginator(cursor_path="cursor", cursor_param="cursor")

    @parameterized.expand([("null_cursor", None), ("missing_cursor_key", "missing")])
    def test_update_state_terminal_page(self, _label: str, cursor_value: str | None) -> None:
        paginator = self._paginator()
        body: dict[str, Any] = {"data": [{"id": 1}]}
        if cursor_value != "missing":
            body["cursor"] = cursor_value
        paginator.update_state(_response(body))
        assert paginator.has_next_page is False


class TestSprigSource:
    def test_seeds_initial_paginator_state_from_saved_cursor(self) -> None:
        result = _run(
            [ScriptedResponse(json={"data": [{"id": 1}], "cursor": None})],
            resume_state=SprigResumeConfig(next_cursor="saved-cursor"),
        )

        assert result.requests[0].param("cursor") == "saved-cursor"

    @parameterized.expand([("Surveys", "/v1/surveys", "1000"), ("Themes", "/v1/themes", None)])
    def test_resume_hook_saves_state_after_batch(self, endpoint: str, path: str, limit: str | None) -> None:
        result = _run(
            [
                ScriptedResponse(json={"data": [{"id": 1}], "cursor": "next-1"}),
                ScriptedResponse(json={"data": [{"id": 2}], "cursor": None}),
            ],
            endpoint=endpoint,
        )

        assert result.paths == [path, path]
        assert result.params("limit") == [limit, limit]
        assert result.params("cursor") == [None, "next-1"]
        assert result.rows == [{"id": 1}, {"id": 2}]
        # The terminal page has no cursor, so nothing is saved for it.
        assert result.saved_states == [SprigResumeConfig(next_cursor="next-1")]


class TestValidateCredentials:
    @parameterized.expand([("rate_limited", 429), ("server_error", 503)])
    def test_transient_errors_raise(self, _label: str, status_code: int) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))):
            with pytest.raises(HTTPError):
                validate_credentials("key")


class TestRedirectsRefused:
    # A redirected request lands on a host that answers 403 with a bot challenge, which must not
    # be read as an auth failure. Redirects are refused so the token never leaves the API host.
    API_URL = f"{SPRIG_API_BASE_URL}/v1/surveys"
    TARGET_URL = "https://sprig.com/v1/surveys"

    @parameterized.expand([("moved_permanently", 301), ("found", 302)])
    def test_sync_refuses_redirect_and_keeps_token_on_api_host(self, _label: str, status: int) -> None:
        result = _run(
            [
                ScriptedResponse(status=status, headers={"Location": self.TARGET_URL}),
                ScriptedResponse(status=403),
            ]
        )

        assert isinstance(result.raised, ValueError)
        assert "Unexpected redirect" in str(result.raised) and "refusing to follow" in str(result.raised)
        assert [request.origin for request in result.requests] == [SPRIG_API_BASE_URL]
        assert result.requests[0].headers["authorization"] == "Bearer key"

    def test_validate_credentials_refuses_redirect_instead_of_reporting_a_valid_key(self) -> None:
        script = [
            ScriptedResponse(status=302, headers={"Location": self.TARGET_URL}),
            ScriptedResponse(status=403),
        ]
        with scripted_network(script) as network:
            with pytest.raises(SprigRedirectError, match="redirected the API request to sprig.com"):
                validate_credentials("key")

        assert [request.origin for request in network.requests_log] == [SPRIG_API_BASE_URL]
