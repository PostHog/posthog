from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.bluetally.bluetally import (
    PAGE_SIZE,
    BluetallyResumeConfig,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bluetally.settings import (
    BLUETALLY_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bluetally.source import BluetallySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    DEFAULT_RETRY_ATTEMPTS,
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bluetally import (
    BluetallySourceConfig,
)


def _driver(tenant_id: str | None = None) -> SourceDriver:
    return SourceDriver(BluetallySource(), BluetallySourceConfig(api_key="key", tenant_id=tenant_id))


def _page(rows: list[dict[str, Any]]) -> ScriptedResponse:
    return ScriptedResponse(json=rows)


class TestPagination:
    def test_paginates_until_short_page(self) -> None:
        full_page = [{"id": i} for i in range(PAGE_SIZE)]
        result = _driver().run("assets", [_page(full_page), _page([{"id": PAGE_SIZE}])])

        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE + 1
        assert result.params("offset") == ["0", str(PAGE_SIZE)]
        # State is saved after the full page (pointing at the next offset), then we stop on the short page.
        assert result.saved_states == [BluetallyResumeConfig(offset=PAGE_SIZE)]

    def test_resumes_from_saved_offset(self) -> None:
        result = _driver().run(
            "assets",
            [_page([{"id": PAGE_SIZE}])],
            resume_state=BluetallyResumeConfig(offset=PAGE_SIZE),
        )

        # Resuming at offset=PAGE_SIZE skips the already-synced first page.
        assert result.raised is None
        assert result.rows == [{"id": PAGE_SIZE}]
        assert result.params("offset") == [str(PAGE_SIZE)]


class TestErrors:
    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_statuses_exhaust_retries(self, _name: str, status: int) -> None:
        result = _driver().run("assets", always(ScriptedResponse(status=status)))

        assert isinstance(result.raised, RESTClientRetryableError)
        assert result.paths == ["/api/v1/assets"] * DEFAULT_RETRY_ATTEMPTS

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_errors_raise_http_error(self, _name: str, status: int) -> None:
        result = _driver().run("assets", [ScriptedResponse(status=status)])

        assert isinstance(result.raised, requests.HTTPError)
        # Client errors are permanent — no retries.
        assert result.paths == ["/api/v1/assets"]

    def test_non_list_payload_raises_value_error(self) -> None:
        # A non-list 200 is a permanent contract violation (wrapped payload, proxy HTML, …) — it must
        # fail loud without burning the retry budget on something retries can't fix.
        result = _driver().run("assets", [ScriptedResponse(json={"error": "unexpected"})])

        assert isinstance(result.raised, ValueError)
        assert "list" in str(result.raised)
        assert result.paths == ["/api/v1/assets"]


class TestBluetallySourceResponse:
    @parameterized.expand([(name,) for name in ENDPOINTS])
    def test_source_response_shape(self, name: str) -> None:
        config = BLUETALLY_ENDPOINTS[name]
        body: list[Any] | dict[str, list[Any]] = {"tenants": []} if name == "tenants" else []
        result = _driver().run(name, [ScriptedResponse(json=body)])

        assert result.raised is None
        response = result.response
        assert response is not None
        assert response.name == name
        assert response.primary_keys == config.primary_keys
        # An endpoint we can't sort stays unordered rather than claiming an order it never requested.
        assert response.sort_mode == ("asc" if config.sort else None)
        assert response.partition_keys == ([config.partition_key] if config.partition_key else None)
        assert response.partition_mode == ("datetime" if config.partition_key else None)

    def test_every_partition_key_is_a_creation_timestamp(self) -> None:
        # Guards against accidentally partitioning on a churning field like updated_at.
        assert {cfg.partition_key for cfg in BLUETALLY_ENDPOINTS.values()} == {"created_at", "timestamp", None}


class TestUnparameterizedEndpoints:
    def test_tenants_sends_no_query_params(self) -> None:
        # `/tenants` documents no parameters, so it must not be sent limit/offset/sort/tenant_id.
        result = _driver(tenant_id="99").run(
            "tenants", [ScriptedResponse(json={"tenants": [{"tenant_id": 1, "tenant_name": "Acme"}]})]
        )

        assert result.raised is None
        assert result.rows == [{"tenant_id": 1, "tenant_name": "Acme"}]
        assert result.queries == [{}]

    def test_tenants_fetches_a_single_page(self) -> None:
        # Without limit/offset there is no second page to ask for, even on a large response.
        tenants = [{"tenant_id": i, "tenant_name": str(i)} for i in range(PAGE_SIZE)]
        result = _driver().run("tenants", [ScriptedResponse(json={"tenants": tenants})])

        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE
        assert result.paths == ["/api/v1/tenants"]
        assert result.saved_states == []

    def test_tenants_ignores_stale_offset_resume_state(self) -> None:
        # Resume state can outlive a schema switch; a single-page endpoint must not skip its only page.
        result = _driver().run(
            "tenants",
            [ScriptedResponse(json={"tenants": [{"tenant_id": 1, "tenant_name": "Acme"}]})],
            resume_state=BluetallyResumeConfig(offset=PAGE_SIZE),
        )

        assert result.raised is None
        assert result.rows == [{"tenant_id": 1, "tenant_name": "Acme"}]
        assert result.requests[0].param("offset") is None

    def test_tenants_missing_envelope_raises(self) -> None:
        # The rows live under `tenants`; a body without it is a contract change, not an empty page.
        result = _driver().run("tenants", [ScriptedResponse(json={"unexpected": []})])

        assert isinstance(result.raised, ValueError)


class TestActivity:
    def test_activity_paginates_with_sorted_params(self) -> None:
        full_page = [{"item_id": i} for i in range(PAGE_SIZE)]
        result = _driver(tenant_id="99").run("activity", [_page(full_page), _page([{"item_id": PAGE_SIZE}])])

        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE + 1
        # The log defaults to newest-first; we ask for oldest-first so the offset walk stays stable.
        assert result.requests[0].param("sort") == "created_at"
        assert result.requests[0].param("order") == "asc"
        assert result.requests[0].param("tenant_id") == "99"
        assert result.requests[1].param("offset") == str(PAGE_SIZE)


class TestValidateCredentials:
    def test_probes_given_endpoint_with_tenant_id(self) -> None:
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_credentials("key", tenant_id="42", endpoint="employees") is True

        assert len(network.requests_log) == 1
        request = network.requests_log[0]
        assert request.origin == "https://app.bluetallyapp.com"
        assert request.path == "/api/v1/employees"
        assert request.param("limit") == "1"
        assert request.param("tenant_id") == "42"

    def test_probes_unparameterized_endpoint_without_a_query_string(self) -> None:
        # `/tenants` takes no parameters, so probing it with limit/tenant_id could be rejected.
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_credentials("key", tenant_id="42", endpoint="tenants") is True

        assert [request.url for request in network.requests_log] == ["https://app.bluetallyapp.com/api/v1/tenants"]
