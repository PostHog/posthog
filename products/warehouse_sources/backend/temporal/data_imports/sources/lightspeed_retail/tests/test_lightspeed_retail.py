from typing import Any

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lightspeedretail import (
    LightspeedRetailSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lightspeed_retail.constants import (
    LIGHTSPEED_RETAIL_API_VERSION_2_0,
    LIGHTSPEED_RETAIL_API_VERSION_2026_01,
    LIGHTSPEED_RETAIL_API_VERSION_2026_07,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lightspeed_retail.lightspeed_retail import (
    LightspeedRetailResumeConfig,
    _clean_domain_prefix,
    _to_version,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lightspeed_retail.source import (
    LightspeedRetailSource,
)

SUPPORTED_API_VERSIONS = [
    LIGHTSPEED_RETAIL_API_VERSION_2_0,
    LIGHTSPEED_RETAIL_API_VERSION_2026_01,
    LIGHTSPEED_RETAIL_API_VERSION_2026_07,
]


def _driver() -> SourceDriver:
    return SourceDriver(
        LightspeedRetailSource(), LightspeedRetailSourceConfig(domain_prefix="mystore", api_token="token")
    )


def _page(items: list[dict[str, Any]], max_version: int | None = None) -> ScriptedResponse:
    body: dict[str, Any] = {"data": items}
    if max_version is not None:
        body["version"] = {"min": 0, "max": max_version}
    return ScriptedResponse(json=body)


class TestCleanDomainPrefix:
    @pytest.mark.parametrize("value", ["", "my store", "store?x=1", "../evil"])
    def test_invalid_prefixes_raise(self, value: str) -> None:
        with pytest.raises(ValueError):
            _clean_domain_prefix(value)


class TestToVersion:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (None, None),
            (12345, 12345),
            ("12345", 12345),
            (123.9, 123),
            ("not-a-number", None),
            (True, None),
        ],
    )
    def test_to_version_values(self, value: Any, expected: int | None) -> None:
        assert _to_version(value) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize("api_version", SUPPORTED_API_VERSIONS)
    def test_validate_credentials_probes_the_pinned_version(self, api_version: str) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_credentials("mystore", "token", api_version) is True

        assert len(network.requests_log) == 1
        assert network.requests_log[0].path == f"/api/{api_version}/outlets"
        assert network.requests_log[0].param("page_size") == "1"

    def test_validate_credentials_rejects_bad_prefix_without_request(self) -> None:
        with scripted_network([]) as network:
            assert validate_credentials("my store!", "token", LIGHTSPEED_RETAIL_API_VERSION_2026_01) is False

        assert network.requests_log == []


class TestGetRows:
    def test_incremental_starts_from_watermark_version(self) -> None:
        result = _driver().run(
            "sales",
            [_page([])],
            api_version=LIGHTSPEED_RETAIL_API_VERSION_2026_01,
            should_use_incremental_field=True,
            db_incremental_field_last_value=777,
        )

        assert result.raised is None
        assert result.params("after") == ["777"]

    def test_missing_version_block_falls_back_to_page_max(self) -> None:
        result = _driver().run(
            "sales",
            [_page([{"id": "1", "version": 10}]), _page([])],
            api_version=LIGHTSPEED_RETAIL_API_VERSION_2026_01,
        )

        assert result.raised is None
        assert [item["id"] for item in result.rows] == ["1"]
        assert result.params("after") == [None, "10"]

    def test_non_advancing_cursor_stops_instead_of_looping(self) -> None:
        # Page with no version block and versions <= the current cursor must
        # terminate rather than refetch the same window forever.
        result = _driver().run(
            "sales",
            [_page([{"id": "1", "version": 5}])],
            api_version=LIGHTSPEED_RETAIL_API_VERSION_2026_01,
            resume_state=LightspeedRetailResumeConfig(after=5),
        )

        assert result.raised is None
        assert [item["id"] for item in result.rows] == ["1"]
        assert result.params("after") == ["5"]

    def test_first_page_advances_when_fallback_version_is_zero(self) -> None:
        # First page (no saved cursor) with no version block and page max of 0
        # must still advance rather than treat 0 as "no cursor".
        result = _driver().run(
            "sales",
            [_page([{"id": "1", "version": 0}]), _page([])],
            api_version=LIGHTSPEED_RETAIL_API_VERSION_2026_01,
        )

        assert result.raised is None
        assert [item["id"] for item in result.rows] == ["1"]
        assert result.params("after") == [None, "0"]

    @pytest.mark.parametrize(
        "resume_state, expected_paths, expected_rows",
        [
            (
                None,
                [
                    "/consignments",
                    "/consignments/c1/products",
                    "/consignments/c1/products",
                    "/consignments/c2/products",
                    "/consignments/c2/products",
                    "/consignments",
                ],
                [("c1", "p1"), ("c2", "p1")],
            ),
            (
                LightspeedRetailResumeConfig(fanout_state={"completed": ["/consignments/c1/products"]}),
                [
                    "/consignments",
                    "/consignments/c2/products",
                    "/consignments/c2/products",
                    "/consignments",
                ],
                [("c2", "p1")],
            ),
        ],
    )
    def test_consignment_products_fan_out_over_consignments(
        self,
        resume_state: LightspeedRetailResumeConfig | None,
        expected_paths: list[str],
        expected_rows: list[tuple[str, str]],
    ) -> None:
        child_pages = {
            "c1": [_page([{"product_id": "p1", "version": 5}]), _page([])],
            "c2": [_page([{"product_id": "p1", "version": 6}]), _page([])],
        }
        responses = [_page([{"id": "c1", "version": 1}, {"id": "c2", "version": 2}], max_version=2)]
        for consignment_id in ("c1", "c2"):
            if expected_paths.count(f"/consignments/{consignment_id}/products"):
                responses.extend(child_pages[consignment_id])
        responses.append(_page([]))

        result = _driver().run(
            "consignment_products",
            responses,
            api_version=LIGHTSPEED_RETAIL_API_VERSION_2026_01,
            resume_state=resume_state,
        )

        assert result.raised is None
        assert [path.split("/api/2026-01")[1] for path in result.paths] == expected_paths
        assert [(row["consignment_id"], row["product_id"]) for row in result.rows] == expected_rows
        assert all("_consignments_id" not in row for row in result.rows)


_GIFT_CARD_PAGES: list[dict[str, Any]] = [
    {"data": [{"id": "g3", "gift_card_transactions": [{"id": "t3"}]}, {"id": "g2", "gift_card_transactions": []}]},
    {"data": [{"id": "g1", "gift_card_transactions": [{"id": "t1"}, {"id": "t2"}]}]},
    {"data": []},
]


class TestUnversionedEndpoints:
    @pytest.mark.parametrize(
        "endpoint, bodies, resume_state, expected_requests, expected_rows",
        [
            (
                "gift_cards",
                _GIFT_CARD_PAGES,
                None,
                [
                    ("/gift_cards", {"page_size": "200"}),
                    ("/gift_cards", {"page_size": "200", "before": "g2"}),
                    ("/gift_cards", {"page_size": "200", "before": "g1"}),
                ],
                [{"id": "g3"}, {"id": "g2"}, {"id": "g1"}],
            ),
            (
                "gift_card_transactions",
                _GIFT_CARD_PAGES[1:],
                LightspeedRetailResumeConfig(cursor="g2"),
                [
                    ("/gift_cards", {"page_size": "200", "before": "g2"}),
                    ("/gift_cards", {"page_size": "200", "before": "g1"}),
                ],
                [{"id": "t1", "gift_card_id": "g1"}, {"id": "t2", "gift_card_id": "g1"}],
            ),
            (
                "product_categories",
                [
                    {"data": {"categories": [{"id": "c1"}]}, "page_info": {"has_next": True, "last_seen": "c1"}},
                    {"data": {"categories": [{"id": "c2"}]}, "page_info": {"has_next": False, "last_seen": "c2"}},
                ],
                None,
                [
                    ("/product_categories", {"page_size": "200"}),
                    ("/product_categories", {"page_size": "200", "after": "c1"}),
                ],
                [{"id": "c1"}, {"id": "c2"}],
            ),
            (
                "promo_codes",
                [
                    {"data": [{"id": "pr1"}, {"id": "pr2"}]},
                    {"data": [{"id": "code1", "promotion_id": "pr1"}]},
                    {"data": [{"id": "code2", "promotion_id": "pr2"}]},
                ],
                None,
                [
                    ("/promotions", {}),
                    ("/promotions/pr1/promocodes", {}),
                    ("/promotions/pr2/promocodes", {}),
                ],
                [{"id": "code1", "promotion_id": "pr1"}, {"id": "code2", "promotion_id": "pr2"}],
            ),
            (
                "store_credit_transactions",
                [
                    {
                        "data": [
                            {
                                "id": "internal-1",
                                "customer_id": "cust-1",
                                "store_credit_transactions": [{"id": "tx1"}, {"id": "tx2"}],
                            },
                            {"id": "internal-2", "customer_id": "cust-2", "store_credit_transactions": None},
                            {"customer_id": "cust-3", "store_credit_transactions": [{"id": "tx3"}]},
                        ]
                    }
                ],
                None,
                [("/store_credits", {})],
                [
                    {"id": "tx1", "customer_id": "cust-1"},
                    {"id": "tx2", "customer_id": "cust-1"},
                    {"id": "tx3", "customer_id": "cust-3"},
                ],
            ),
        ],
    )
    def test_pages_without_record_versions(
        self,
        endpoint: str,
        bodies: list[dict[str, Any]],
        resume_state: LightspeedRetailResumeConfig | None,
        expected_requests: list[tuple[str, dict[str, str]]],
        expected_rows: list[dict[str, Any]],
    ) -> None:
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json=body) for body in bodies],
            api_version=LIGHTSPEED_RETAIL_API_VERSION_2026_01,
            resume_state=resume_state,
        )

        assert result.raised is None
        requests_seen = [
            (request.path.split("/api/2026-01")[1], {name: values[0] for name, values in request.query.items()})
            for request in result.requests
        ]
        assert requests_seen == expected_requests
        assert [{key: row.get(key) for key in expected_rows[0]} for row in result.rows] == expected_rows
