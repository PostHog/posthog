from typing import Any, Optional

from parameterized import parameterized
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.stigg import StiggSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.stigg.settings import ENDPOINTS, STIGG_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.stigg.source import StiggSource
from products.warehouse_sources.backend.temporal.data_imports.sources.stigg.stigg import (
    PAGE_SIZE,
    StiggResumeConfig,
    validate_credentials,
)


def _response(
    items: Optional[list[dict[str, Any]]], next_cursor: Optional[str] = None, *, raw_body: Any = None
) -> ScriptedResponse:
    """Build a Stigg list-endpoint response: ``{"data": [...], "pagination": {"next": ...}}``.

    ``raw_body`` overrides the whole body for malformed-shape cases (a bare array, or a dict
    without ``data``).
    """
    if raw_body is not None:
        body: Any = raw_body
    else:
        body = {"data": items or [], "pagination": {"next": next_cursor, "prev": None}}
    return ScriptedResponse(json=body)


def _driver() -> SourceDriver:
    return SourceDriver(StiggSource(), StiggSourceConfig(api_key="stigg-key"))


class TestPagination:
    def test_follows_next_cursor_until_null(self) -> None:
        result = _driver().run(
            "customers",
            [
                _response([{"id": "1"}, {"id": "2"}], next_cursor="cursor-page-2"),
                _response([{"id": "3"}], next_cursor=None),
            ],
        )

        assert result.rows == [{"id": "1"}, {"id": "2"}, {"id": "3"}]
        # First page carries only `limit`; the second sends the `after` cursor.
        assert result.queries[0] == {"limit": (str(PAGE_SIZE),)}
        assert result.queries[1] == {"limit": (str(PAGE_SIZE),), "after": ("cursor-page-2",)}
        # State is saved after the first page (cursor advances to pagination.next), then we stop.
        assert result.saved_states == [StiggResumeConfig(cursor="cursor-page-2")]

    def test_resumes_from_saved_cursor(self) -> None:
        result = _driver().run(
            "customers",
            [_response([{"id": "5"}], next_cursor=None)],
            resume_state=StiggResumeConfig(cursor="cur-99"),
        )

        assert result.rows == [{"id": "5"}]
        # The initial (cursorless) page is never fetched on resume — the first request carries `after`.
        assert len(result.requests) == 1
        assert result.queries[0] == {"limit": (str(PAGE_SIZE),), "after": ("cur-99",)}

    def test_empty_first_page_yields_nothing(self) -> None:
        result = _driver().run("customers", [_response([], next_cursor=None)])

        assert result.rows == []
        assert result.saved_states == []

    def test_empty_page_with_cursor_stops_without_saving(self) -> None:
        # Defensive: an empty page terminates even if the API still returns a next cursor,
        # so a buggy upstream cursor can't loop us forever.
        result = _driver().run("customers", [_response([], next_cursor="phantom-cursor")])

        assert result.rows == []
        assert len(result.requests) == 1
        assert result.saved_states == []


class TestErrorHandling:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_retry_then_raise(self, _name: str, status: int) -> None:
        result = _driver().run("customers", always(ScriptedResponse(status=status)))

        assert isinstance(result.raised, RESTClientRetryableError)
        # 429/5xx are retried up to the client's attempt cap.
        assert len(result.requests) == 5

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_for_status(self, _name: str, status: int) -> None:
        result = _driver().run("customers", [ScriptedResponse(status=status)])

        # 4xx (other than 429) is a permanent failure — surfaced immediately, not retried.
        assert isinstance(result.raised, HTTPError)
        assert len(result.requests) == 1

    @parameterized.expand(
        [
            ("bare_array", [{"id": "1"}]),
            ("missing_data_key", {"pagination": {"next": None}}),
            ("data_not_a_list", {"data": {"id": "1"}, "pagination": {"next": None}}),
        ]
    )
    def test_malformed_body_shape_is_retryable(self, _name: str, raw_body: Any) -> None:
        result = _driver().run("customers", always(ScriptedResponse(json=raw_body)))

        # A 200 whose body isn't `{"data": [...]}` is transient — retried, then reraised.
        assert isinstance(result.raised, RESTClientRetryableError)
        assert len(result.requests) == 5


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True, None),
            (
                "unauthorized",
                401,
                False,
                "Invalid Stigg API key. Use a server API key from Settings → Integrations → API keys.",
            ),
            (
                "forbidden",
                403,
                False,
                "Invalid Stigg API key. Use a server API key from Settings → Integrations → API keys.",
            ),
            ("server_error", 500, False, "Stigg returned HTTP 500"),
        ]
    )
    def test_status_mapping(
        self, _name: str, status: int, expected_valid: bool, expected_message: Optional[str]
    ) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))):
            assert validate_credentials("stigg-key") == (expected_valid, expected_message)

    def test_connection_error_maps_to_generic_message(self) -> None:
        # validate_via_probe swallows transport errors and returns (False, None).
        with scripted_network(always(ConnectionError("boom"))):
            assert validate_credentials("stigg-key") == (False, "Could not validate Stigg API key")


class TestSourceResponseShape:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _driver().run(endpoint, []).response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == STIGG_ENDPOINTS[endpoint].primary_keys
        # createdAt is required on every list DTO and never changes, so it's a stable partition key.
        assert response.partition_mode == "datetime"
        assert response.partition_format == "month"
        assert response.partition_keys == ["createdAt"]

    @parameterized.expand([("plans",), ("addons",)])
    def test_versioned_packages_use_composite_primary_key(self, endpoint: str) -> None:
        # Plans and addons share their `id` slug across versions; dropping `versionNumber` from
        # the key would seed duplicate rows and multi-match every later merge.
        assert STIGG_ENDPOINTS[endpoint].primary_keys == ["id", "versionNumber"]
