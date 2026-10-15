import json
from datetime import UTC, date, datetime
from typing import Any

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.square import SquareSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.square.settings import SQUARE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.square.source import SquareSource
from products.warehouse_sources.backend.temporal.data_imports.sources.square.square import (
    MAX_CURSOR_RESTARTS,
    SQUARE_HOSTS,
    SquareInvalidCursorError,
    SquareResumeConfig,
    _build_initial_params,
    _format_rfc3339,
    _is_invalid_cursor_error,
    validate_credentials,
)


def _make_response(body: dict[str, Any], status_code: int = 200) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers["Content-Type"] = "application/json"
    return resp


def _page(body: dict[str, Any], status_code: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status_code, json=body)


class TestFormatRFC3339:
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
    def test_format_rfc3339(self, _name: str, value: Any, expected: str) -> None:
        assert _format_rfc3339(value) == expected


class TestBuildInitialParams:
    @parameterized.expand(
        [
            # incremental endpoint with a cursor value -> server-side begin_time filter
            (
                "incremental_endpoint_sets_begin_time",
                "payments",
                True,
                datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
                {"begin_time": "2026-03-04T02:58:14.000Z", "sort_order": "ASC", "limit": "50"},
                [],
            ),
            # incremental endpoint, full refresh -> no begin_time
            (
                "incremental_endpoint_full_refresh_omits_begin_time",
                "payments",
                False,
                None,
                {"sort_order": "ASC"},
                ["begin_time"],
            ),
            # customers has no server-side time filter, so even with an incremental
            # value selected we must not invent a begin_time param.
            (
                "full_refresh_endpoint_never_sets_begin_time",
                "customers",
                True,
                datetime(2026, 3, 4, tzinfo=UTC),
                {"sort_field": "CREATED_AT"},
                ["begin_time"],
            ),
            # non-paginated endpoint -> no limit param
            (
                "non_paginated_endpoint_omits_limit",
                "locations",
                False,
                None,
                {},
                ["limit"],
            ),
        ]
    )
    def test_build_initial_params(
        self,
        _name: str,
        endpoint: str,
        should_use_incremental_field: bool,
        last_value: Any,
        expected_present: dict[str, str],
        expected_absent: list[str],
    ) -> None:
        params = _build_initial_params(
            SQUARE_ENDPOINTS[endpoint],
            should_use_incremental_field=should_use_incremental_field,
            db_incremental_field_last_value=last_value,
        )
        for key, value in expected_present.items():
            assert params[key] == value
        for key in expected_absent:
            assert key not in params


class TestIsInvalidCursorError:
    @parameterized.expand(
        [
            ("cursor_field", 400, {"errors": [{"field": "cursor", "code": "INVALID_VALUE"}]}, True),
            ("invalid_cursor_code", 400, {"errors": [{"code": "INVALID_CURSOR"}]}, True),
            ("unrelated_400", 400, {"errors": [{"field": "sort_field", "code": "INVALID_VALUE"}]}, False),
            ("empty_400", 400, {}, False),
            ("null_errors", 400, {"errors": None}, False),
            ("not_a_400", 404, {"errors": [{"field": "cursor"}]}, False),
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
        with scripted_network(always(_page({}, status_code=status_code))):
            assert validate_credentials("token", "production") == expected

    def test_network_error_returns_invalid(self) -> None:
        with scripted_network(always(ConnectionError("boom"))):
            assert validate_credentials("token", "production") == (False, False)

    def test_schema_probes_that_endpoint(self) -> None:
        with scripted_network([_page({})]) as network:
            validate_credentials("token", "sandbox", schema_name="payments")
        assert network.requests_log[0].url.startswith(f"{SQUARE_HOSTS['sandbox']}/v2/payments")


class TestGetRowsPagination:
    def _drive(
        self, endpoint: str, script: list[ScriptedResponse], resume_state: SquareResumeConfig | None = None
    ) -> DriveResult:
        config = SquareSourceConfig(access_token="token", environment="production")
        return SourceDriver(SquareSource(), config).run(endpoint, script, resume_state=resume_state)

    def test_first_request_starts_unresumed_when_there_is_no_saved_state(self) -> None:
        result = self._drive("payments", [_page({"payments": [{"id": "a"}]})])

        assert result.requests[0].param("cursor") is None

    def test_invalid_cursor_resumes_incremental_endpoint_from_last_seen(self) -> None:
        # An endpoint with a server-side time filter (payments has begin_time) must not
        # re-scan from zero when a cursor expires mid-stream — it should re-issue the
        # query seeded with the last created_at it saw, bounding the re-scan to the tail.
        result = self._drive(
            "payments",
            [
                _page({"payments": [{"id": "p1", "created_at": "2026-03-04T02:58:14Z"}], "cursor": "cur-1"}),
                _page({"errors": [{"code": "INVALID_CURSOR"}]}, status_code=400),
                _page({"payments": [{"id": "p2", "created_at": "2026-03-05T00:00:00Z"}]}),
            ],
        )

        queries = result.queries
        assert "cursor" not in queries[0]
        assert queries[1] == {"sort_order": ("ASC",), "limit": ("50",), "cursor": ("cur-1",)}
        # The restart drops the cursor and seeds begin_time from the last seen created_at
        # rather than issuing a bare full restart.
        assert "cursor" not in queries[2]
        assert queries[2]["begin_time"] == ("2026-03-04T02:58:14Z",)

    def test_invalid_cursor_gives_up_after_restart_budget_exhausted(self) -> None:
        invalid = _page({"errors": [{"field": "cursor", "code": "INVALID_CURSOR"}]}, status_code=400)
        # Each restart re-scans one page then expires again; once the budget is spent
        # the next rejection is surfaced.
        script = [invalid]
        for _ in range(MAX_CURSOR_RESTARTS):
            script.append(_page({"customers": [{"id": "c"}], "cursor": "cur"}))
            script.append(invalid)

        result = self._drive("customers", script, resume_state=SquareResumeConfig(cursor="stale-cursor"))

        assert isinstance(result.raised, SquareInvalidCursorError)
