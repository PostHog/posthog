from typing import Any

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.inflowinventory import (
    InflowinventorySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.inflowinventory.inflowinventory import (
    INFLOWINVENTORY_API_VERSION_2023_04_01,
    INFLOWINVENTORY_API_VERSION_2026_07_10,
    INFLOWINVENTORY_API_VERSION_2026_09_29,
    PAGE_SIZE,
    InflowInventoryResumeConfig,
    check_access,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.inflowinventory.settings import (
    ENDPOINTS,
    INFLOWINVENTORY_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.inflowinventory.source import (
    InflowinventorySource,
)


def _driver() -> SourceDriver:
    return SourceDriver(InflowinventorySource(), InflowinventorySourceConfig(company_id="co-123", api_key="inflow-key"))


def _full_page(start_id: int, id_field: str = "productId") -> list[dict[str, Any]]:
    return [{id_field: str(start_id + i)} for i in range(PAGE_SIZE)]


class TestPagination:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_cursor_uses_per_endpoint_id_field(self, endpoint: str) -> None:
        config = INFLOWINVENTORY_ENDPOINTS[endpoint]
        last_id = str(PAGE_SIZE - 1)
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(json=_full_page(0, id_field=config.id_field)),
                ScriptedResponse(json=[{config.id_field: "9999"}]),
            ],
        )

        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE + 1
        assert result.params("after") == [None, last_id]
        assert result.paths == [f"/co-123/{config.path}"] * 2

    def test_resumes_from_saved_cursor(self) -> None:
        # The unpaginated first page (after absent) must never be fetched on resume.
        result = _driver().run(
            "products",
            [ScriptedResponse(json=[{"productId": "5"}])],
            resume_state=InflowInventoryResumeConfig(after="42"),
        )

        assert result.raised is None
        assert result.rows == [{"productId": "5"}]
        assert len(result.requests) == 1
        assert result.params("after") == ["42"]

    def test_full_page_missing_id_field_stops(self) -> None:
        # A full page whose last row lacks the cursor field can't be paginated past — stop instead
        # of looping forever on the same cursor.
        page = _full_page(0)
        page[-1] = {"name": "no id here"}
        result = _driver().run("products", [ScriptedResponse(json=page)])

        assert result.raised is None
        assert len(result.rows) == PAGE_SIZE
        assert len(result.requests) == 1
        assert result.saved_states == []

    @parameterized.expand(
        [
            ("legacy", INFLOWINVENTORY_API_VERSION_2023_04_01),
            ("previous", INFLOWINVENTORY_API_VERSION_2026_07_10),
            ("current", INFLOWINVENTORY_API_VERSION_2026_09_29),
        ]
    )
    def test_resolved_version_reaches_session_header(self, _name: str, api_version: str) -> None:
        result = _driver().run("products", [ScriptedResponse(json=[])], api_version=api_version)

        assert result.raised is None
        assert result.requests[0].headers["accept"] == f"application/json;version={api_version}"

    @parameterized.expand([("rate_limited", 429), ("server_error", 500), ("bad_gateway", 503)])
    def test_retryable_status_is_reissued(self, _name: str, status: int) -> None:
        result = _driver().run("products", [ScriptedResponse(status=status, json=[]), ScriptedResponse(json=[])])

        # A 429/5xx is retried (not permanently failed): the second attempt succeeds with an empty page.
        assert result.raised is None
        assert result.rows == []
        assert len(result.requests) == 2

    @parameterized.expand([("unauthorized", 401), ("forbidden", 403), ("not_found", 404)])
    def test_client_error_raises(self, _name: str, status: int) -> None:
        result = _driver().run("products", [ScriptedResponse(status=status, json=[])])

        assert isinstance(result.raised, requests.HTTPError)

    def test_non_list_body_raises_value_error(self) -> None:
        # A 200 whose body isn't the expected bare array is a permanent contract violation.
        result = _driver().run("products", [ScriptedResponse(json={"error": "nope"})])

        assert isinstance(result.raised, ValueError)


class TestCheckAccess:
    @parameterized.expand(
        [
            ("ok", 200, 200, None),
        ]
    )
    def test_status_mapping(self, _name: str, status: int, expected_status: int, expected_message: str | None) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            actual = check_access("inflow-key", "co-123", INFLOWINVENTORY_API_VERSION_2026_07_10)

        assert actual == (expected_status, expected_message)
        assert network.requests_log[0].path == "/co-123/products"
        assert network.requests_log[0].param("count") == "1"

    @parameterized.expand(
        [
            ("legacy", INFLOWINVENTORY_API_VERSION_2023_04_01),
            ("previous", INFLOWINVENTORY_API_VERSION_2026_07_10),
            ("current", INFLOWINVENTORY_API_VERSION_2026_09_29),
        ]
    )
    def test_probe_session_carries_resolved_version(self, _name: str, api_version: str) -> None:
        with scripted_network([ScriptedResponse()]) as network:
            check_access("inflow-key", "co-123", api_version)

        assert network.session_options[0]["headers"]["Accept"] == f"application/json;version={api_version}"

    def test_malformed_company_id_short_circuits(self) -> None:
        # A bad company ID never reaches the network — no session is created.
        with scripted_network([]) as network:
            status, message = check_access("inflow-key", "bad id/../evil", INFLOWINVENTORY_API_VERSION_2026_07_10)

        assert status == 400
        assert message is not None
        assert network.requests_log == []
        assert network.session_options == []


class TestInflowInventorySourceResponse:
    @parameterized.expand([(e,) for e in ENDPOINTS])
    def test_source_response_shape(self, endpoint: str) -> None:
        result = _driver().run(endpoint, [ScriptedResponse(json=[])])

        assert result.raised is None
        assert result.response is not None
        assert result.response.name == endpoint
        assert result.response.primary_keys == INFLOWINVENTORY_ENDPOINTS[endpoint].primary_keys
        # No stable creation timestamp is guaranteed across every object, so we don't partition.
        assert result.response.partition_mode is None
