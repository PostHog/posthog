import json
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

from parameterized import parameterized
from requests import Response

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.veeqo import VeeqoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.veeqo.settings import VEEQO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.veeqo.source import VeeqoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.veeqo.veeqo import (
    VeeqoPaginator,
    VeeqoResumeConfig,
    _build_initial_params,
    _format_incremental_value,
    validate_credentials,
)


def _response(body: Any, status_code: int = 200, headers: dict[str, str] | None = None) -> Response:
    resp = Response()
    resp.status_code = status_code
    resp._content = json.dumps(body).encode()
    resp.headers.update(headers or {})
    return resp


def _page(body: Any, status: int = 200, headers: dict[str, str] | None = None) -> ScriptedResponse:
    return ScriptedResponse(status=status, json=body, headers=headers or {})


def _run(script: Script, endpoint: str = "orders", api_key: str = "key", **kwargs: Any) -> DriveResult:
    driver = SourceDriver(VeeqoSource(), VeeqoSourceConfig(api_key=api_key))
    return driver.run(endpoint, script, **kwargs)


def _full_page(page_size: int = 100) -> list[dict[str, Any]]:
    return [{"id": i} for i in range(page_size)]


class TestVeeqoPaginator:
    def test_empty_page_stops(self) -> None:
        paginator = VeeqoPaginator(page_size=100)
        paginator.update_state(_response([]), [])
        assert paginator.has_next_page is False

    def test_malformed_total_pages_header_falls_back_to_page_size_check(self) -> None:
        paginator = VeeqoPaginator(page_size=100)
        paginator.update_state(_response(_full_page(), headers={"X-Total-Pages-Count": "unknown"}), _full_page())
        # A full page with an unparseable header keeps paginating rather than crashing.
        assert paginator.has_next_page is True


class TestFormatIncrementalValue:
    @parameterized.expand(
        [
            ("utc_datetime", "updated_at", datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04 02:58:14"),
            ("naive_datetime", "updated_at", datetime(2026, 3, 4, 2, 58, 14), "2026-03-04 02:58:14"),
            (
                "non_utc_datetime_normalized",
                "created_at",
                datetime(2026, 3, 4, 4, 58, 14, tzinfo=timezone(timedelta(hours=2))),
                "2026-03-04 02:58:14",
            ),
            ("date_value", "created_at", date(2026, 3, 4), "2026-03-04 00:00:00"),
            ("string_passthrough", "updated_at", "2026-03-04 00:00:00", "2026-03-04 00:00:00"),
            ("id_as_int", "id", 12345, 12345),
            ("id_string_coerced", "id", "12345", 12345),
        ]
    )
    def test_format_incremental_value(self, _name: str, field: str, value: object, expected: object) -> None:
        assert _format_incremental_value(field, value) == expected


class TestBuildInitialParams:
    @parameterized.expand(
        [
            ("updated_at", "updated_at_min", "2026-03-04 02:58:14"),
            ("created_at", "created_at_min", "2026-03-04 02:58:14"),
        ]
    )
    def test_incremental_maps_user_field_to_documented_param(
        self, incremental_field: str, expected_param: str, expected_value: str
    ) -> None:
        params = _build_initial_params(
            VEEQO_ENDPOINTS["orders"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC),
            incremental_field=incremental_field,
        )
        assert params[expected_param] == expected_value
        assert params["page_size"] == 100


class TestValidateCredentials:
    @parameterized.expand(
        [
            ("ok", 200, True),
            ("unauthorized", 401, False),
            ("forbidden", 403, False),
            ("server_error", 500, False),
        ]
    )
    def test_status_mapping(self, _name: str, status_code: int, expected_ok: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code, json=[]))):
            ok, error = validate_credentials("key")

        assert ok is expected_ok
        if not expected_ok:
            assert error is not None

    def test_network_error_returns_false(self) -> None:
        with scripted_network(always(ConnectionError("boom"))):
            ok, error = validate_credentials("key")

        assert ok is False
        assert error is not None

    def test_key_is_redacted_from_captured_samples(self) -> None:
        # `x-api-key` isn't in the shared auth-header denylist, so the key must be
        # passed as a `redact_values` literal to keep it out of captured HTTP samples.
        with scripted_network([ScriptedResponse(json=[])]) as network:
            validate_credentials("secret-key")

        assert network.session_options[0]["redact_values"] == ("secret-key",)
        assert network.requests_log[0].headers["x-api-key"] == "secret-key"


class TestPagination:
    def test_paginates_and_saves_state_after_each_non_terminal_page(self) -> None:
        result = _run(
            [
                _page(_full_page(), headers={"X-Total-Pages-Count": "2"}),
                _page([{"id": 900}], headers={"X-Total-Pages-Count": "2"}),
            ]
        )

        assert len(result.rows) == 101
        assert result.params("page") == ["1", "2"]
        assert result.params("page_size")[0] == "100"
        # State saved once, only while a next page remains to resume from.
        assert result.saved_states == [VeeqoResumeConfig(endpoint="orders", page=2)]

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = _run([_page([{"id": 1}])])

        assert result.params("page") == ["1"]

    def test_resumes_from_saved_page_when_endpoint_matches(self) -> None:
        result = _run([_page([{"id": 1}])], resume_state=VeeqoResumeConfig(endpoint="orders", page=7))

        assert result.params("page") == ["7"]

    def test_ignores_saved_page_of_another_endpoint(self) -> None:
        result = _run([_page([{"id": 1}])], resume_state=VeeqoResumeConfig(endpoint="products", page=7))

        assert result.params("page") == ["1"]

    def test_incremental_first_page_sends_min_filter_on_every_page(self) -> None:
        result = _run(
            [
                _page(_full_page(), headers={"X-Total-Pages-Count": "2"}),
                _page([{"id": 900}]),
            ],
            incremental_field="updated_at",
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        )

        # The filter must stay on every page — the paginator only advances `page`.
        assert result.params("updated_at_min") == ["2026-01-01 00:00:00"] * 2

    def test_redirects_are_refused(self) -> None:
        # requests preserves the custom x-api-key header across redirects, so a
        # redirect response could replay the full-account key to another host —
        # every sync request must be sent with redirects disabled.
        result = _run(
            [
                _page([], status=302, headers={"Location": "https://evil.example.com/steal"}),
                _page([{"id": 1}]),
            ]
        )

        assert len(result.requests) == 1
        assert {request.origin for request in result.requests} == {"https://api.veeqo.com"}

    def test_non_list_body_fails_loud(self) -> None:
        # Veeqo list responses are documented as bare arrays; a wrapper object on a
        # 200 means the response shape changed and must not sync as a single row.
        result = _run([_page({"orders": [{"id": 1}]})])

        assert isinstance(result.raised, ValueError)
        assert "list" in str(result.raised)

    def test_api_key_is_redacted_from_captured_samples(self) -> None:
        result = _run([_page([{"id": 1}])], api_key="secret-key")

        # The framework api_key auth exposes the key via secret_values(), which the
        # tracked session receives as redact_values.
        assert any("secret-key" in options.get("redact_values", ()) for options in result.session_options)
        assert result.requests[0].headers["x-api-key"] == "secret-key"


class TestVeeqoSourceResponse:
    @parameterized.expand([(name,) for name in VEEQO_ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        response = _run([_page([])], endpoint=endpoint).response

        config = VEEQO_ENDPOINTS[endpoint]
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        # Veeqo documents no list ordering, so the watermark must only commit after
        # a successful sync (desc semantics) — asc would checkpoint ≈now mid-sync.
        assert response.sort_mode == "desc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None
