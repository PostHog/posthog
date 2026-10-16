from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.wufoo import WufooSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.wufoo.settings import ENDPOINTS, WUFOO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.wufoo.source import WufooSource
from products.warehouse_sources.backend.temporal.data_imports.sources.wufoo.wufoo import (
    PAGE_SIZE,
    WufooResumeConfig,
    validate_credentials,
)


def _response(count: int, *, data_key: str = "Forms", status: int = 200, drop_key: bool = False) -> ScriptedResponse:
    body: dict[str, Any] = {}
    if not drop_key:
        body[data_key] = [{"Hash": f"h{i}"} for i in range(count)]
    return ScriptedResponse(status=status, json=body)


def _driver() -> SourceDriver:
    return SourceDriver(WufooSource(), WufooSourceConfig(subdomain="acme", api_key="wufoo-key"))


class TestPagination:
    def test_follows_offset_until_short_page(self) -> None:
        result = _driver().run("forms", [_response(PAGE_SIZE), _response(PAGE_SIZE), _response(3)])

        assert len(result.rows) == 2 * PAGE_SIZE + 3
        # pageStart advances by PAGE_SIZE per page; pageSize is pinned on every request.
        assert result.params("pageStart") == ["0", str(PAGE_SIZE), str(2 * PAGE_SIZE)]
        assert all(size == str(PAGE_SIZE) for size in result.params("pageSize"))
        # State is checkpointed after each full page (points at the next offset), never for the short one.
        assert [s.page_start for s in result.saved_states] == [PAGE_SIZE, 2 * PAGE_SIZE]

    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run("forms", [_response(2)], resume_state=WufooResumeConfig(page_start=PAGE_SIZE))

        # Offset 0 is never fetched on resume — the first request targets the saved offset.
        assert result.requests[0].param("pageStart") == str(PAGE_SIZE)
        assert len(result.rows) == 2

    def test_missing_data_key_raises_loudly(self) -> None:
        result = _driver().run("forms", [_response(0, drop_key=True)])

        # A 200 body without the expected list key means the shape changed — fail loud, not 0 rows.
        assert isinstance(result.raised, ValueError)
        assert "matched nothing" in str(result.raised)


class TestRetryClassification:
    @parameterized.expand([("server_error", 500), ("bad_gateway", 503), ("rate_limited", 429)])
    def test_transient_statuses_are_retried(self, _name: str, status: int) -> None:
        result = _driver().run("forms", [_response(0, status=status), _response(1)])

        # The transient status is retried and the sync completes on the follow-up 200.
        assert len(result.requests) == 2
        assert len(result.rows) == 1

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_fail_loud(self, _name: str, status: int) -> None:
        result = _driver().run("forms", [_response(0, status=status)])

        # 4xx (other than 429) is a permanent error: it is not retried and surfaces as an HTTPError.
        assert isinstance(result.raised, requests.HTTPError)
        assert len(result.requests) == 1


class TestValidateCredentials:
    def test_invalid_subdomain_short_circuits_without_request(self) -> None:
        with scripted_network([]) as network:
            assert validate_credentials("wufoo-key", "bad subdomain!") is None
        assert network.requests_log == []

    def test_connection_error_maps_to_none(self) -> None:
        with scripted_network(always(requests.ConnectionError("boom"))):
            assert validate_credentials("wufoo-key", "acme") is None


class TestWufooSourceResponse:
    @parameterized.expand([("forms",), ("reports",), ("users",)])
    def test_uses_hash_primary_key(self, endpoint: str) -> None:
        response = _driver().run(endpoint, []).response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == ["Hash"]

    def test_every_endpoint_uses_hash_primary_key(self) -> None:
        assert all(config.primary_keys == ["Hash"] for config in WUFOO_ENDPOINTS.values())
        assert set(WUFOO_ENDPOINTS) == set(ENDPOINTS)
