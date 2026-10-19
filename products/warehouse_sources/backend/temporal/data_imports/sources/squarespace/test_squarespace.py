import json
from datetime import UTC, date, datetime
from typing import Any

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.squarespace import (
    SquarespaceSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.squarespace.settings import SQUARESPACE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.squarespace.source import SquarespaceSource
from products.warehouse_sources.backend.temporal.data_imports.sources.squarespace.squarespace import (
    MAX_CURSOR_RESTARTS,
    SQUARESPACE_BASE_URL,
    SquarespaceInvalidCursorError,
    SquarespaceResumeConfig,
    _build_initial_params,
    _format_datetime_z,
    _is_invalid_cursor_error,
    validate_credentials,
)


def _make_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _page(data_key: str, items: list[dict[str, Any]], next_cursor: str | None = None) -> ScriptedResponse:
    pagination = {"hasNextPage": next_cursor is not None, "nextPageCursor": next_cursor, "nextPageUrl": None}
    return ScriptedResponse(json={data_key: items, "pagination": pagination})


class TestFormatDatetimeZ:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            (
                "microseconds_truncated",
                datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC),
                "2026-01-15T10:30:45.123Z",
            ),
            ("naive_assumed_utc", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("string_passthrough", "2026-03-04T02:58:14.000Z", "2026-03-04T02:58:14.000Z"),
        ]
    )
    def test_format(self, _name: str, value: Any, expected: str) -> None:
        assert _format_datetime_z(value) == expected


class TestBuildInitialParams:
    MODIFIED_BEFORE = datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC)

    def test_full_refresh_endpoint_never_sets_window(self) -> None:
        # inventory has no server-side time filter, so even with an incremental value
        # selected we must not invent a window param.
        params = _build_initial_params(
            SQUARESPACE_ENDPOINTS["inventory"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 5, 1, tzinfo=UTC),
            modified_before=self.MODIFIED_BEFORE,
        )
        assert "modifiedAfter" not in params
        assert "modifiedBefore" not in params

    def test_future_last_value_clamped_into_window(self) -> None:
        params = _build_initial_params(
            SQUARESPACE_ENDPOINTS["orders"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2099, 1, 1, tzinfo=UTC),
            modified_before=self.MODIFIED_BEFORE,
        )
        # modifiedAfter must not exceed modifiedBefore, or Squarespace 400s on an inverted window.
        assert params["modifiedAfter"] == params["modifiedBefore"]


class TestIsInvalidCursorError:
    @parameterized.expand(
        [
            ("cursor_in_message", 400, {"message": "The cursor parameter contains an invalid value"}, True),
            ("cursor_in_subtype", 400, {"subtype": "INVALID_CURSOR", "message": "bad"}, True),
            ("unrelated_400", 400, {"message": "modifiedAfter is not a valid ISO 8601 string"}, False),
            ("empty_400", 400, {}, False),
            ("not_a_400", 404, {"message": "cursor"}, False),
        ]
    )
    def test_detection(self, _name: str, status_code: int, body: dict[str, Any], expected: bool) -> None:
        assert _is_invalid_cursor_error(_make_response(body, status_code=status_code)) is expected

    def test_non_json_body_is_not_invalid_cursor(self) -> None:
        resp = Response()
        resp.status_code = 400
        resp._content = b"<html>Bad Request</html>"
        assert _is_invalid_cursor_error(resp) is False


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, (True, False)),
            ("unauthorized", 401, (False, False)),
            ("forbidden", 403, (False, True)),
            ("server_error", 500, (False, False)),
        ]
    )
    def test_status_code_mapping(self, _name: str, status_code: int, expected: tuple[bool, bool]) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))):
            assert validate_credentials("token") == expected

    def test_network_error_returns_invalid(self) -> None:
        with scripted_network(always(ConnectionError("boom"))):
            assert validate_credentials("token") == (False, False)

    def test_schema_probes_that_endpoint_with_its_version(self) -> None:
        with scripted_network([ScriptedResponse(json={})]) as network:
            validate_credentials("token", schema_name="products")
        # products is served from the v2 API.
        assert network.requests_log[0].url == f"{SQUARESPACE_BASE_URL}/v2/commerce/products"


class TestGetRowsPagination:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(SquarespaceSource(), SquarespaceSourceConfig(api_key="token"))

    def test_a_run_with_no_saved_state_starts_without_a_cursor(self) -> None:
        result = self._driver().run("orders", [_page("result", [{"id": "a"}])])

        assert result.params("cursor") == [None]

    @parameterized.expand(
        [
            ("orders", "result"),
            ("products", "products"),
            ("transactions", "documents"),
            ("inventory", "inventory"),
            ("store_pages", "storePages"),
            ("profiles", "profiles"),
            # Unpaginated: the response carries no `pagination` object.
            ("fulfillment_options", "fulfillmentOptions", False),
        ]
    )
    def test_yields_rows_using_endpoint_data_key(self, endpoint: str, data_key: str, paginated: bool = True) -> None:
        rows = [{"id": "a"}, {"id": "b"}]
        response = _page(data_key, rows) if paginated else ScriptedResponse(json={data_key: rows})

        result = self._driver().run(endpoint, [response])

        assert result.items == [[{"id": "a"}, {"id": "b"}]]

    def test_invalid_cursor_on_initial_request_is_surfaced(self) -> None:
        # A cursor-less initial request can't trigger cursor expiry, so a cursor-rejection
        # there is a malformed query — surface it rather than looping forever.
        result = self._driver().run("orders", [ScriptedResponse(status=400, json={"message": "cursor invalid"})])

        assert isinstance(result.raised, SquarespaceInvalidCursorError)

    def test_invalid_cursor_gives_up_after_restart_budget_exhausted(self) -> None:
        invalid = ScriptedResponse(status=400, json={"message": "cursor invalid"})
        script = [invalid]
        for _ in range(MAX_CURSOR_RESTARTS):
            script.append(_page("result", [{"id": "o"}], next_cursor="cur"))
            script.append(invalid)

        result = self._driver().run("orders", script, resume_state=SquarespaceResumeConfig(cursor="stale-cursor"))

        assert isinstance(result.raised, SquarespaceInvalidCursorError)
