from datetime import UTC, date, datetime
from typing import Any

from parameterized import parameterized

from products.warehouse_sources.sources.recharge._config import RechargeSourceConfig
from products.warehouse_sources.sources.recharge.recharge import (
    RechargeResumeConfig,
    _build_initial_params,
    _format_incremental_value,
    validate_credentials,
)
from products.warehouse_sources.sources.recharge.settings import METAFIELD_OWNER_RESOURCES, RECHARGE_ENDPOINTS
from products.warehouse_sources.sources.recharge.source import RechargeSource
from products.warehouse_sources.sources.sdk.testing import (
    DriveResult,
    Script,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)


def _page(endpoint: str, items: list[dict[str, Any]], next_cursor: str | None) -> ScriptedResponse:
    return ScriptedResponse(json={endpoint: items, "next_cursor": next_cursor})


def _first_owner_query(owner_resource: str) -> dict[str, tuple[str, ...]]:
    return {"limit": ("250",), "sort_by": ("id-asc",), "owner_resource": (owner_resource,)}


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
            ("plans", "updated_at"),
            ("events", "created_at"),
            ("credit_adjustments", "updated_at"),
            ("credit_adjustments", "created_at"),
        ]
    )
    def test_incremental_on_unsortable_endpoint_omits_sort_by(self, endpoint: str, incremental_field: str) -> None:
        params = _build_initial_params(
            RECHARGE_ENDPOINTS[endpoint],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
            incremental_field=incremental_field,
        )
        assert params == {"limit": 250, f"{incremental_field}_min": "2026-01-01T00:00:00"}

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
        response = _drive(endpoint, always(_page(endpoint, [], None)), api_key="token").response

        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["id"]
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["created_at"]

    @parameterized.expand(
        [
            ("sorted_endpoint", "customers", "asc"),
            ("unsorted_endpoint", "events", None),
            ("owner_walk_restarts_the_order_per_owner_type", "metafields", None),
        ]
    )
    def test_sort_mode_is_asc_only_when_the_request_sorts(
        self, _name: str, endpoint: str, expected_sort_mode: str | None
    ) -> None:
        response = _drive(
            endpoint,
            always(_page(endpoint, [], None)),
            should_use_incremental_field=True,
            incremental_field="created_at",
            db_incremental_field_last_value=datetime(2026, 1, 1, tzinfo=UTC),
        ).response

        assert response is not None
        assert response.sort_mode == expected_sort_mode


class TestCustomerEntitlements:
    @parameterized.expand(
        [
            ("envelope", {"customer_entitlements": [{"id": 7}], "next_cursor": None}, [7]),
            ("empty_envelope", {"customer_entitlements": [], "next_cursor": None}, []),
            ("bare_array", [{"id": 7}, {"id": 8}], [7, 8]),
            ("empty_bare_array", [], []),
        ]
    )
    def test_reads_rows_from_either_response_shape(self, _name: str, body: Any, expected_ids: list[int]) -> None:
        result = _drive("customer_entitlements", [ScriptedResponse(json=body)])

        assert result.raised is None
        assert [row["id"] for row in result.rows] == expected_ids

    def test_follows_the_envelope_cursor(self) -> None:
        result = _drive(
            "customer_entitlements",
            [
                _page("customer_entitlements", [{"id": 9}], "entitlements-2"),
                _page("customer_entitlements", [{"id": 8}], None),
            ],
        )

        assert [row["id"] for row in result.rows] == [9, 8]
        assert result.queries == [{"limit": ("250",)}, {"cursor": ("entitlements-2",), "limit": ("250",)}]

    @parameterized.expand(
        [
            ("full_bare_page_cannot_be_paged", [{"id": i} for i in range(250)]),
            ("object_without_rows", {"error": "unexpected"}),
        ]
    )
    def test_fails_instead_of_dropping_rows(self, _name: str, body: Any) -> None:
        result = _drive("customer_entitlements", [ScriptedResponse(json=body)])

        assert isinstance(result.raised, ValueError)
        assert result.rows == []


class TestMetafieldsOwnerWalk:
    def test_walks_every_owner_type_and_stages_each_owner_start(self) -> None:
        result = _drive(
            "metafields",
            [
                _page("metafields", [{"id": 1}], "address-2"),
                _page("metafields", [{"id": 2}], None),
                _page("metafields", [{"id": 3}], None),
                *[_page("metafields", [], None) for _ in range(4)],
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == [1, 2, 3]
        assert result.queries[0] == {"limit": ("250",), "sort_by": ("id-asc",), "owner_resource": ("address",)}
        assert result.queries[1] == {"cursor": ("address-2",), "limit": ("250",)}
        assert result.params("owner_resource") == [
            "address",
            None,
            "store",
            "customer",
            "subscription",
            "order",
            "charge",
        ]
        assert result.saved_states == [
            RechargeResumeConfig(endpoint="metafields", cursor="address-2", owner_resource="address"),
            *[
                RechargeResumeConfig(endpoint="metafields", owner_resource=owner)
                for owner in ("store", "customer", "subscription", "order", "charge")
            ],
        ]

    def test_resume_after_the_last_page_of_an_owner_type_starts_the_next_one(self) -> None:
        result = _drive(
            "metafields",
            [
                _page("metafields", [{"id": 1}], "address-2"),
                _page("metafields", [{"id": 2}], None),
                ScriptedResponse(status=403, json={"errors": "forbidden"}),
            ],
        )

        assert result.raised is not None
        assert [row["id"] for row in result.rows] == [1, 2]
        assert result.final_state == RechargeResumeConfig(endpoint="metafields", owner_resource="store")

    @parameterized.expand(
        [
            (
                "cursor_inside_an_owner_type",
                RechargeResumeConfig(endpoint="metafields", cursor="order-3", owner_resource="order"),
                [{"cursor": ("order-3",), "limit": ("250",)}, _first_owner_query("charge")],
            ),
            (
                "start_of_an_owner_type",
                RechargeResumeConfig(endpoint="metafields", owner_resource="order"),
                [_first_owner_query("order"), _first_owner_query("charge")],
            ),
            (
                "cursor_without_an_owner_type",
                RechargeResumeConfig(endpoint="metafields", cursor="unknown-owner"),
                [_first_owner_query(owner) for owner in METAFIELD_OWNER_RESOURCES],
            ),
            (
                "state_of_another_endpoint",
                RechargeResumeConfig(endpoint="customers", cursor="customers-2", owner_resource="order"),
                [_first_owner_query(owner) for owner in METAFIELD_OWNER_RESOURCES],
            ),
        ]
    )
    def test_resume(
        self, _name: str, resume_state: RechargeResumeConfig, expected_queries: list[dict[str, tuple[str, ...]]]
    ) -> None:
        result = _drive("metafields", always(_page("metafields", [], None)), resume_state=resume_state)

        assert result.raised is None
        assert result.queries == expected_queries
