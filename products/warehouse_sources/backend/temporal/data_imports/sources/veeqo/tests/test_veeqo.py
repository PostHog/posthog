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
    route,
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
        assert response.primary_keys == config.primary_keys
        # Veeqo documents no list ordering, so the watermark must only commit after
        # a successful sync (desc semantics) — asc would checkpoint ≈now mid-sync.
        assert response.sort_mode == "desc"
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None
            assert response.partition_keys is None


class TestNestedTables:
    @parameterized.expand(
        [
            (
                "returns_carry_their_order_id",
                "returns",
                [
                    {"id": 1, "returns": [{"id": 10, "status": "returning"}, {"id": 11, "status": "received"}]},
                    {"id": 2, "returns": []},
                    {"id": 3, "returns": None},
                    {"id": 4},
                ],
                [
                    {"id": 10, "status": "returning", "order_id": 1},
                    {"id": 11, "status": "received", "order_id": 1},
                ],
            ),
            (
                "stock_entries_flatten_every_sellable",
                "stock_entries",
                [
                    {
                        "id": 5,
                        "sellables": [
                            {
                                "id": 50,
                                "stock_entries": [
                                    {"sellable_id": 50, "warehouse_id": 1, "physical_stock_level": 3},
                                    {"sellable_id": 50, "warehouse_id": 2, "physical_stock_level": 0},
                                ],
                            },
                            {"id": 51, "stock_entries": [{"sellable_id": 51, "warehouse_id": 1}]},
                            {"id": 52, "stock_entries": None},
                        ],
                    },
                    {"id": 6, "sellables": []},
                    {"id": 7},
                ],
                [
                    {"sellable_id": 50, "warehouse_id": 1, "physical_stock_level": 3, "product_id": 5},
                    {"sellable_id": 50, "warehouse_id": 2, "physical_stock_level": 0, "product_id": 5},
                    {"sellable_id": 51, "warehouse_id": 1, "product_id": 5},
                ],
            ),
        ]
    )
    def test_rows_are_exploded_from_the_parent_list(
        self, _name: str, endpoint: str, parent_page: list[dict[str, Any]], expected_rows: list[dict[str, Any]]
    ) -> None:
        result = _run([_page(parent_page)], endpoint=endpoint)

        assert result.raised is None
        assert result.paths == [VEEQO_ENDPOINTS[endpoint].path]
        assert result.rows == expected_rows

    def test_parent_page_with_no_nested_rows_still_advances(self) -> None:
        result = _run(
            [
                _page([{"id": i, "returns": []} for i in range(100)], headers={"X-Total-Pages-Count": "2"}),
                _page([{"id": 900, "returns": [{"id": 1}]}]),
            ],
            endpoint="returns",
        )

        assert result.params("page") == ["1", "2"]
        assert result.rows == [{"id": 1, "order_id": 900}]


class TestFanoutTables:
    @parameterized.expand(
        [
            (
                "tracking_events_per_shipment",
                "shipment_tracking_events",
                {
                    "/orders": [
                        _page(
                            [
                                {
                                    "id": 1,
                                    "allocations": [
                                        {"id": 100, "shipment": {"id": 7001}},
                                        {"id": 101, "shipment": None},
                                        {"id": 103, "shipment": {"id": 7001}},
                                    ],
                                },
                                {"id": 2, "allocations": [{"id": 102, "shipment": {"id": 7002}}]},
                                {"id": 3, "allocations": []},
                                {"id": 4},
                            ]
                        )
                    ],
                    "/shipping/tracking_events/7001": [
                        _page(
                            [
                                {
                                    "timestamp": "2026-01-01T10:00:00+00:00",
                                    "status": "in_transit",
                                    "description": "In transit",
                                },
                                {
                                    "timestamp": "2026-01-02T10:00:00+00:00",
                                    "status": "delivered",
                                    "description": "Delivered",
                                },
                            ]
                        )
                    ],
                    # A shipment deleted after the orders listing must not fail the sync.
                    "/shipping/tracking_events/7002": [_page({"error": "not found"}, status=404)],
                },
                ["/orders", "/shipping/tracking_events/7001", "/shipping/tracking_events/7002"],
                [
                    {
                        "timestamp": "2026-01-01T10:00:00+00:00",
                        "status": "in_transit",
                        "description": "In transit",
                        "shipment_id": 7001,
                        "order_id": 1,
                    },
                    {
                        "timestamp": "2026-01-02T10:00:00+00:00",
                        "status": "delivered",
                        "description": "Delivered",
                        "shipment_id": 7001,
                        "order_id": 1,
                    },
                ],
            ),
            (
                "bundle_contents_only_for_kits",
                "bundle_contents",
                {
                    "/products": [
                        _page(
                            [
                                {
                                    "id": 5,
                                    "sellables": [
                                        {"id": 50, "type": "Kit"},
                                        {"id": 51, "type": "ProductVariant"},
                                    ],
                                },
                                {"id": 6, "sellables": [{"id": 60, "type": "ProductVariant"}]},
                                {"id": 8, "sellables": [{"id": 80, "type": "Kit"}]},
                            ]
                        )
                    ],
                    "/kits/50": [
                        _page(
                            {
                                "id": 50,
                                "type": "Kit",
                                "contents": [
                                    {"id": 1, "kit_id": 50, "product_variant_id": 51, "quantity": 2},
                                    {"id": 2, "kit_id": 50, "product_variant_id": 60, "quantity": 1},
                                ],
                            }
                        )
                    ],
                    "/kits/80": [_page({"id": 80, "type": "Kit", "contents": []})],
                },
                ["/products", "/kits/50", "/kits/80"],
                [
                    {"id": 1, "kit_id": 50, "product_variant_id": 51, "quantity": 2, "product_id": 5},
                    {"id": 2, "kit_id": 50, "product_variant_id": 60, "quantity": 1, "product_id": 5},
                ],
            ),
        ]
    )
    def test_fans_out_to_one_request_per_parent_id(
        self,
        _name: str,
        endpoint: str,
        responses: dict[str, list[ScriptedResponse]],
        expected_paths: list[str],
        expected_rows: list[dict[str, Any]],
    ) -> None:
        result = _run(route(responses), endpoint=endpoint)

        assert result.raised is None
        assert result.paths == expected_paths
        # The parent list is paged; the single-object child endpoints take no page params.
        assert result.queries[0]["page_size"] == ("100",)
        assert all("page_size" not in query and "page" not in query for query in result.queries[1:])
        assert result.rows == expected_rows

    def test_parent_list_paginates_before_fanning_out(self) -> None:
        full_orders_page = [{"id": i, "allocations": []} for i in range(99)] + [
            {"id": 99, "allocations": [{"id": 1, "shipment": {"id": 7001}}]}
        ]
        result = _run(
            route(
                {
                    "/orders": [
                        _page(full_orders_page, headers={"X-Total-Pages-Count": "2"}),
                        _page([{"id": 200, "allocations": [{"id": 2, "shipment": {"id": 7002}}]}]),
                    ],
                    "/shipping/tracking_events/7001": [_page([{"timestamp": "t1", "status": "delivered"}])],
                    "/shipping/tracking_events/7002": [_page([{"timestamp": "t2", "status": "delivered"}])],
                }
            ),
            endpoint="shipment_tracking_events",
        )

        assert result.raised is None
        assert [row["shipment_id"] for row in result.rows] == [7001, 7002]
        assert [query.get("page") for query in result.queries if "page_size" in query] == [("1",), ("2",)]

    def test_resume_skips_shipments_already_synced(self) -> None:
        orders = [
            {"id": 1, "allocations": [{"id": 10, "shipment": {"id": 7001}}]},
            {"id": 2, "allocations": [{"id": 20, "shipment": {"id": 7002}}]},
        ]
        result = _run(
            route(
                {
                    "/orders": [_page(orders)],
                    "/shipping/tracking_events/7002": [_page([{"timestamp": "t2", "status": "delivered"}])],
                }
            ),
            endpoint="shipment_tracking_events",
            resume_state=VeeqoResumeConfig(
                endpoint="shipment_tracking_events",
                fanout_state={"completed": ["/shipping/tracking_events/7001"], "current": None, "child_state": None},
            ),
        )

        assert result.raised is None
        assert result.paths == ["/orders", "/shipping/tracking_events/7002"]
        assert result.rows == [{"timestamp": "t2", "status": "delivered", "shipment_id": 7002, "order_id": 2}]
        assert result.saved_states[-1] == VeeqoResumeConfig(
            endpoint="shipment_tracking_events",
            fanout_state={
                "completed": ["/shipping/tracking_events/7001", "/shipping/tracking_events/7002"],
                "current": None,
                "child_state": None,
            },
        )
