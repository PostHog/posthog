from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.schematic import (
    SchematicSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.schematic.schematic import SchematicResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.schematic.source import SchematicSource


def _driver() -> SourceDriver:
    return SourceDriver(SchematicSource(), SchematicSourceConfig(api_key="sch_test_key"))


PAGE_SIZE = 100


def _page(rows: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json={"data": rows, "params": {"limit": PAGE_SIZE}})


def _rows(prefix: str, count: int) -> list[dict[str, Any]]:
    return [{"id": f"{prefix}_{index}", "product_id": f"{prefix}_{index}"} for index in range(count)]


_COMPANIES_ORDER = {"sort_order_column": "created_at", "sort_order_direction": "asc"}

# Paths as the Schematic SDK calls them, so a typo in the endpoint table fails here.
_SINGLE_PASS = [
    ("companies", "/companies", _COMPANIES_ORDER),
    ("users", "/users", {}),
    ("company_memberships", "/company-memberships", {}),
    ("features", "/features", {}),
    ("flags", "/flags", {}),
    ("plans", "/plans", {}),
    ("plan_entitlements", "/plan-entitlements", {}),
    ("company_overrides", "/company-overrides", {}),
    ("billing_customers", "/billing/customers", {}),
    ("billing_meters", "/billing/meter", {}),
]
_TWO_PASS = [
    ("billing_products", "/billing/products"),
    ("billing_prices", "/billing/price"),
    ("billing_coupons", "/billing/coupons"),
]


class TestSchematicPagination:
    @pytest.mark.parametrize(("endpoint", "path", "order"), _SINGLE_PASS)
    def test_walks_offset_pages_until_a_short_page(self, endpoint: str, path: str, order: dict[str, str]) -> None:
        result = _driver().run(endpoint, [_page(_rows("a", PAGE_SIZE)), _page(_rows("b", 3))])

        assert result.raised is None
        assert result.paths == [path] * 2
        assert result.params("offset") == ["0", "100"]
        assert result.params("limit") == ["100", "100"]
        assert {name: result.requests[1].param(name) for name in _COMPANIES_ORDER} == {
            name: order.get(name) for name in _COMPANIES_ORDER
        }
        assert [request.headers["x-schematic-api-key"] for request in result.requests] == ["sch_test_key"] * 2
        assert result.saved_states == [SchematicResumeConfig(offset=PAGE_SIZE)]
        assert len(result.rows) == PAGE_SIZE + 3

    def test_empty_first_page_yields_nothing_and_saves_no_state(self) -> None:
        result = _driver().run("companies", [_page([])])

        assert result.raised is None
        assert result.rows == []
        assert result.saved_states == []

    def test_resume_starts_from_the_saved_offset(self) -> None:
        result = _driver().run("companies", [_page(_rows("c", 1))], resume_state=SchematicResumeConfig(offset=300))

        assert result.raised is None
        assert result.params("offset") == ["300"]

    @pytest.mark.parametrize(("endpoint", "path"), _TWO_PASS)
    def test_reads_active_then_inactive_records(self, endpoint: str, path: str) -> None:
        result = _driver().run(
            endpoint, [_page(_rows("a", PAGE_SIZE)), _page(_rows("b", 1)), _page(_rows("inactive", 2))]
        )

        assert result.raised is None
        assert result.paths == [path] * 3
        assert result.params("is_active") == ["true", "true", "false"]
        assert result.params("offset") == ["0", str(PAGE_SIZE), "0"]
        assert result.saved_states == [
            SchematicResumeConfig(offset=PAGE_SIZE, is_active=True),
            SchematicResumeConfig(offset=0, is_active=False),
        ]
        assert len(result.rows) == PAGE_SIZE + 3

    @pytest.mark.parametrize(
        ("resume", "expected_requests"),
        [
            (SchematicResumeConfig(offset=200, is_active=True), [("true", "200"), ("false", "0")]),
            (SchematicResumeConfig(offset=100, is_active=False), [("false", "100")]),
        ],
    )
    def test_resume_continues_the_pass_it_stopped_in(
        self, resume: SchematicResumeConfig, expected_requests: list[tuple[str, str]]
    ) -> None:
        result = _driver().run(
            "billing_products", [_page(_rows("r", 1)) for _ in expected_requests], resume_state=resume
        )

        assert result.raised is None
        assert [(r.param("is_active"), r.param("offset")) for r in result.requests] == expected_requests

    def test_does_not_follow_a_redirect_with_the_api_key(self) -> None:
        result = _driver().run(
            "companies", [ScriptedResponse(status=302, headers={"Location": "https://elsewhere.example.com/x"})]
        )

        assert result.raised is not None
        assert {request.origin for request in result.requests} == {"https://api.schematichq.com"}


class TestSchematicValidateCredentials:
    @pytest.mark.parametrize(
        ("status", "body", "expected_valid", "expected_fragment"),
        [
            (200, {"data": [], "params": {}}, True, None),
        ],
    )
    def test_maps_the_probe_status_to_a_message(
        self, status: int, body: dict[str, Any], expected_valid: bool, expected_fragment: str | None
    ) -> None:
        config = SchematicSourceConfig(api_key="sch_test_key")
        # `always` because the transport retries a 5xx; assert the set of URLs, not the count.
        with scripted_network(always(ScriptedResponse(status=status, json=body))) as network:
            is_valid, message = SchematicSource().validate_credentials(config, team_id=1)

        assert is_valid is expected_valid
        assert (message is None) if expected_fragment is None else (expected_fragment in (message or ""))
        assert {request.url for request in network.requests_log} == {"https://api.schematichq.com/companies?limit=1"}
        assert network.requests_log[0].headers["x-schematic-api-key"] == "sch_test_key"
