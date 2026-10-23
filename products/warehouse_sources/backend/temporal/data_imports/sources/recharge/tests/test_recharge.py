from datetime import UTC, date, datetime
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.recharge import (
    RechargeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recharge.recharge import (
    RechargeResumeConfig,
    _build_initial_params,
    _format_incremental_value,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.recharge.settings import RECHARGE_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.recharge.source import RechargeSource


def _page(endpoint: str, items: list[dict[str, Any]], next_cursor: str | None) -> ScriptedResponse:
    return ScriptedResponse(json={endpoint: items, "next_cursor": next_cursor})


def _drive(endpoint: str, script: Script, api_key: str = "t", **inputs: Any) -> DriveResult:
    return SourceDriver(RechargeSource(), RechargeSourceConfig(api_key=api_key)).run(endpoint, script, **inputs)


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14"),
            ("naive_datetime", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14"),
            ("date_value", date(2026, 3, 4), "2026-03-04T00:00:00"),
            ("string_passthrough", "2026-03-04T00:00:00", "2026-03-04T00:00:00"),
        ]
    )
    def test_format_incremental_value(self, _name: str, value: object, expected: str) -> None:
        assert _format_incremental_value(value) == expected


class TestBuildInitialParams:
    def test_incremental_on_created_at_uses_created_field(self) -> None:
        params = _build_initial_params(
            RECHARGE_ENDPOINTS["orders"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            incremental_field="created_at",
        )
        assert params["created_at_min"] == "2026-01-01T00:00:00"
        assert params["sort_by"] == "created_at-asc"
        assert "updated_at_min" not in params

    @parameterized.expand(
        [
            ("default_endpoint_uses_max_page_size", "customers", 250),
            ("payment_methods_uses_smaller_page_size", "payment_methods", 50),
        ]
    )
    def test_page_size_is_per_endpoint(self, _name: str, endpoint: str, expected_limit: int) -> None:
        # `payment_methods` pages are too slow to generate within the read timeout
        # at the 250 max, so it requests smaller pages.
        params = _build_initial_params(
            RECHARGE_ENDPOINTS[endpoint],
            should_use_incremental_field=False,
            db_incremental_field_last_value=None,
            incremental_field=None,
        )
        assert params["limit"] == expected_limit

    @parameterized.expand(
        [
            # `collections` is full-refresh but still sortable -> keeps `id-asc`.
            ("collections", {"limit": 250, "sort_by": "id-asc"}),
            # `/products` on the 2021-11 API rejects `sort_by` outright -> limit only.
            ("products", {"limit": 250}),
        ]
    )
    def test_full_refresh_endpoint_ignores_incremental_inputs(self, endpoint: str, expected: dict) -> None:
        # Full-refresh endpoints must never emit a `*_min` filter even when the user
        # supplies incremental inputs; products additionally omits `sort_by`.
        params = _build_initial_params(
            RECHARGE_ENDPOINTS[endpoint],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            incremental_field="updated_at",
        )
        assert params == expected
        assert not any(k.endswith("_min") for k in params)


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected_ok: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json={}))) as network:
            ok, error = validate_credentials("token")

        assert ok is expected_ok
        if not expected_ok:
            assert error is not None
        assert network.requests_log[0].path == "/token_information"
        assert network.requests_log[0].headers["x-recharge-access-token"] == "token"

    def test_token_is_redacted_from_captured_samples(self) -> None:
        # The `X-Recharge-Access-Token` header isn't in the shared auth-header
        # denylist, so the token must be passed as a `redact_values` literal to
        # keep it out of captured HTTP samples.
        with scripted_network([ScriptedResponse(json={})]) as network:
            validate_credentials("secret-token")

        assert network.session_options[0]["redact_values"] == ("secret-token",)


class TestPagination:
    def test_token_is_redacted_from_captured_samples(self) -> None:
        result = _drive("customers", [_page("customers", [{"id": 1}], None)], api_key="secret-token")

        assert result.session_options
        assert all(option["redact_values"] == ("secret-token",) for option in result.session_options)

    @parameterized.expand(
        [
            ("payment_methods_uses_smaller_limit", "payment_methods", 50),
            ("customers_use_default_limit", "customers", 250),
        ]
    )
    def test_cursor_pages_use_per_endpoint_limit_and_drop_filters(
        self, _name: str, endpoint: str, expected_limit: int
    ) -> None:
        # Both the first page and cursor pages carry the per-endpoint limit; the
        # cursor page sends ONLY cursor + limit (Recharge 422s if the original
        # sort/filter params are re-sent alongside a cursor).
        result = _drive(endpoint, [_page(endpoint, [{"id": 1}], "cursor-2"), _page(endpoint, [{"id": 2}], None)])

        assert result.requests[0].param("limit") == str(expected_limit)
        assert result.requests[0].param("sort_by") == "id-asc"
        assert result.queries[1] == {"cursor": ("cursor-2",), "limit": (str(expected_limit),)}

    def test_resumes_from_saved_cursor_when_endpoint_matches(self) -> None:
        result = _drive(
            "customers",
            [_page("customers", [{"id": 9}], None)],
            resume_state=RechargeResumeConfig(endpoint="customers", cursor="saved-cursor"),
        )

        # When following a cursor we only send cursor + limit, no sort/filters.
        assert result.queries[0] == {"cursor": ("saved-cursor",), "limit": ("250",)}

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = _drive("customers", [_page("customers", [{"id": 9}], None)])

        assert result.params("cursor") == [None]
        assert result.params("sort_by") == ["id-asc"]


class TestRechargeSource:
    @parameterized.expand([(name,) for name in RECHARGE_ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _drive(endpoint, [_page(endpoint, [], None)], api_key="token").response

        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]
