from typing import Any

import pytest
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.chargify.chargify import (
    ChargifyPaginator,
    ChargifyResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.chargify.settings import CHARGIFY_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.chargify.source import ChargifySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.chargify import (
    ChargifySourceConfig,
)


class TestChargifyPaginator:
    def test_get_resume_state_returns_none_on_terminal_page(self) -> None:
        paginator = ChargifyPaginator()
        paginator.update_state(MagicMock(), data=[])
        assert paginator.get_resume_state() is None


class TestChargifySourceResumeBehavior:
    """End-to-end resume behaviour of Chargify extraction."""

    def _driver(self) -> SourceDriver:
        return SourceDriver(ChargifySource(), ChargifySourceConfig(api_key="test-key", subdomain="acme"))

    @pytest.mark.parametrize(
        "endpoint", ["Customers", "Subscriptions", "Events", "Transactions", "Coupons", "ReasonCodes"]
    )
    def test_fresh_run_saves_page_after_each_non_terminal_page(self, endpoint: str) -> None:
        selector_key = CHARGIFY_ENDPOINTS[endpoint].data_selector.split(".")[-1]
        responses = [
            ScriptedResponse(json=[{selector_key: {"id": 1}}]),
            ScriptedResponse(json=[{selector_key: {"id": 2}}]),
            ScriptedResponse(json=[]),
        ]
        result = self._driver().run(endpoint, responses)

        assert result.raised is None
        assert result.params("page") == ["1", "2", "3"]
        assert result.saved_states == [ChargifyResumeConfig(next_page=2), ChargifyResumeConfig(next_page=3)]

    def test_resume_seeds_paginator_with_saved_page(self) -> None:
        responses = [
            ScriptedResponse(json=[{"customer": {"id": 1}}]),
            ScriptedResponse(json=[]),
        ]
        result = self._driver().run("Customers", responses, resume_state=ChargifyResumeConfig(next_page=5))

        assert result.raised is None
        assert result.params("page") == ["5", "6"]

    def test_does_not_load_state_when_cannot_resume(self) -> None:
        responses = [ScriptedResponse(json=[{"customer": {"id": 1}}]), ScriptedResponse(json=[])]
        result = self._driver().run("Customers", responses)

        assert result.raised is None
        assert result.params("page") == ["1", "2"]

    @pytest.mark.parametrize(
        ("endpoint", "first_page", "empty_page", "expected_row"),
        [
            ("Coupons", [{"coupon": {"id": 1, "code": "FREE"}}], [], {"id": 1, "code": "FREE"}),
            ("ReasonCodes", [{"reason_code": {"id": 2, "code": "LARGE"}}], [], {"id": 2, "code": "LARGE"}),
            (
                "CreditNotes",
                {"credit_notes": [{"uid": "cn_1", "total_amount": "10.0"}]},
                {"credit_notes": []},
                {"uid": "cn_1", "total_amount": "10.0"},
            ),
        ],
    )
    def test_rows_are_unwrapped_and_pagination_terminates(
        self, endpoint: str, first_page: Any, empty_page: Any, expected_row: dict[str, Any]
    ) -> None:
        # Chargify mixes bare arrays of single-key-wrapped objects with payloads nested under a
        # plural key, so the selector has to strip the right wrapper and the paginator has to
        # recognise an empty page in either shape.
        responses = [ScriptedResponse(json=first_page), ScriptedResponse(json=empty_page)]
        result = self._driver().run(endpoint, responses)

        # The resource yields one list per page.
        assert result.raised is None
        assert result.items == [[expected_row]]
        assert result.params("page") == ["1", "2"]


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status_code", "expected"),
        [
            (200, True),
        ],
    )
    def test_status_maps_to_validity(self, status_code: int, expected: bool) -> None:
        with scripted_network(always(ScriptedResponse(status=status_code))) as network:
            assert validate_credentials("api-key", "acme") is expected

        assert network.requests_log[0].path == "/customers.json"

    def test_probes_the_site_subdomain_host(self) -> None:
        with scripted_network([ScriptedResponse(json=[])]) as network:
            validate_credentials("api-key", "acme")

        assert network.requests_log[0].url.startswith("https://acme.chargify.com")
