from typing import Any

import pytest
import time_machine

from products.warehouse_sources.sources.schematic._config import SchematicSourceConfig
from products.warehouse_sources.sources.schematic.schematic import SchematicResumeConfig
from products.warehouse_sources.sources.schematic.source import SchematicSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, scripted_network


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
    ("billing_credits", "/billing/credits", {}),
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


class TestSchematicFeatureUsage:
    def test_reads_each_company_and_keeps_its_id(self) -> None:
        companies = [{"id": "comp_1"}, {"id": "comp_2"}]
        result = _driver().run(
            "feature_usage",
            [
                _page(companies),
                _page([{"entitlement_id": f"ent_{index}"} for index in range(PAGE_SIZE)]),
                _page([{"entitlement_id": "ent_last"}]),
                _page([{"entitlement_id": "ent_0"}]),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/companies", "/feature-usage", "/feature-usage", "/feature-usage"]
        assert result.params("company_id") == [None, "comp_1", "comp_1", "comp_2"]
        assert result.params("offset") == ["0", "0", "100", "0"]
        assert result.requests[0].param("sort_order_column") == "created_at"
        assert len(result.rows) == PAGE_SIZE + 2
        assert {row["company_id"] for row in result.rows} == {"comp_1", "comp_2"}
        assert all("_companies_id" not in row for row in result.rows)

    def test_resume_skips_the_companies_already_read(self) -> None:
        companies = [{"id": "comp_1"}, {"id": "comp_2"}]
        first = _driver().run(
            "feature_usage",
            [_page(companies), _page([{"entitlement_id": "ent_1"}]), ScriptedResponse(status=401, json={})],
        )
        assert first.raised is not None
        assert first.final_state is not None and first.final_state.fanout_state is not None

        resumed = _driver().run(
            "feature_usage",
            [_page(companies), _page([{"entitlement_id": "ent_2"}])],
            resume_state=first.final_state,
        )

        assert resumed.raised is None
        assert resumed.params("company_id") == [None, "comp_2"]
        assert [row["company_id"] for row in resumed.rows] == ["comp_2"]


HISTORY_PAGE_SIZE = 250
_NOW = "2026-11-26T10:30:00Z"


def _history_rows(count: int) -> list[dict[str, Any]]:
    return [
        {"company_id": f"comp_{index}", "feature_id": "feat_1", "event_subtype": "api_call", "usage": 1}
        for index in range(count)
    ]


class TestSchematicFeatureUsageHistory:
    @pytest.fixture(autouse=True)
    def _freeze_time(self):
        with time_machine.travel(_NOW, tick=False):
            yield

    def test_full_refresh_walks_yearly_windows_up_to_the_current_hour(self) -> None:
        result = _driver().run(
            "feature_usage_history",
            [_page(_history_rows(HISTORY_PAGE_SIZE)), _page(_history_rows(1)), _page([]), _page([]), _page([])],
        )

        assert result.raised is None
        assert result.paths == ["/feature-usage-history"] * 5
        assert [(r.param("start_time"), r.param("end_time"), r.param("offset")) for r in result.requests] == [
            ("2023-01-01T00:00:00Z", "2024-01-01T00:00:00Z", "0"),
            ("2023-01-01T00:00:00Z", "2024-01-01T00:00:00Z", "250"),
            ("2024-01-01T00:00:00Z", "2024-12-31T00:00:00Z", "0"),
            ("2024-12-31T00:00:00Z", "2025-12-31T00:00:00Z", "0"),
            ("2025-12-31T00:00:00Z", "2026-11-26T10:00:00Z", "0"),
        ]
        assert set(result.params("granularity")) == {"daily"}
        assert set(result.params("limit")) == {"250"}
        assert len(result.rows) == HISTORY_PAGE_SIZE + 1
        assert result.saved_states == [
            SchematicResumeConfig(offset=offset, window_start=start, history_end="2026-11-26T10:00:00Z")
            for offset, start in [
                (HISTORY_PAGE_SIZE, "2023-01-01T00:00:00Z"),
                (0, "2024-01-01T00:00:00Z"),
                (0, "2024-12-31T00:00:00Z"),
                (0, "2025-12-31T00:00:00Z"),
            ]
        ]

    @pytest.mark.parametrize(
        ("last_value", "expected_start"),
        [
            ("2026-11-20T00:00:00Z", "2026-11-13T00:00:00Z"),
            ("2026-11-20T15:00:00+00:00", "2026-11-13T00:00:00Z"),
            ("2023-01-03T00:00:00Z", "2023-01-01T00:00:00Z"),
        ],
    )
    def test_incremental_starts_a_week_before_the_cursor_at_midnight(
        self, last_value: str, expected_start: str
    ) -> None:
        result = _driver().run(
            "feature_usage_history",
            [_page([])] * 4,
            incremental_field="period_start",
            db_incremental_field_last_value=last_value,
        )

        assert result.raised is None
        assert result.requests[0].param("start_time") == expected_start

    def test_incremental_from_today_reads_one_window(self) -> None:
        result = _driver().run(
            "feature_usage_history",
            [_page(_history_rows(2))],
            incremental_field="period_start",
            db_incremental_field_last_value="2026-11-26T00:00:00Z",
        )

        assert result.raised is None
        assert [(r.param("start_time"), r.param("end_time")) for r in result.requests] == [
            ("2026-11-19T00:00:00Z", "2026-11-26T10:00:00Z")
        ]
        assert len(result.rows) == 2

    @pytest.mark.parametrize(
        ("history_end", "expected_windows"),
        [
            # The saved end keeps the resumed offset on the window it was taken from.
            (
                "2026-11-25T23:00:00Z",
                [
                    ("2024-12-31T00:00:00Z", "2025-12-31T00:00:00Z", "500"),
                    ("2025-12-31T00:00:00Z", "2026-11-25T23:00:00Z", "0"),
                ],
            ),
            # A state saved before the end was kept falls back to the current hour.
            (
                None,
                [
                    ("2024-12-31T00:00:00Z", "2025-12-31T00:00:00Z", "500"),
                    ("2025-12-31T00:00:00Z", "2026-11-26T10:00:00Z", "0"),
                ],
            ),
        ],
    )
    def test_resume_continues_the_saved_window_then_the_later_ones(
        self, history_end: str | None, expected_windows: list[tuple[str, str, str]]
    ) -> None:
        result = _driver().run(
            "feature_usage_history",
            [_page(_history_rows(1)), _page([])],
            resume_state=SchematicResumeConfig(
                offset=500, window_start="2024-12-31T00:00:00Z", history_end=history_end
            ),
        )

        assert result.raised is None
        assert [(r.param("start_time"), r.param("end_time"), r.param("offset")) for r in result.requests] == (
            expected_windows
        )


class TestSchematicSchemas:
    def test_feature_usage_history_offers_merge_but_not_append(self) -> None:
        (schema,) = SchematicSource().get_schemas(
            SchematicSourceConfig(api_key="sch_test_key"), team_id=1, names=["feature_usage_history"]
        )

        assert schema.supports_incremental is True
        assert schema.supports_append is False


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
