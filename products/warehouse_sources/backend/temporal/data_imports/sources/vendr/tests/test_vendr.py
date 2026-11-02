from typing import Any, cast

import pytest

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.vendr import VendrSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.vendr.settings import VENDR_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.vendr.source import VendrSource
from products.warehouse_sources.backend.temporal.data_imports.sources.vendr.vendr import (
    VendrResumeConfig,
    _get_resource,
    validate_credentials,
)


def _driver() -> SourceDriver:
    return SourceDriver(VendrSource(), VendrSourceConfig(api_key="key"))


class TestVendrTransport:
    @parameterized.expand(
        [
            ("Companies", "/v1/catalog/companies", {"sortBy": "name", "sortOrder": "asc"}),
            ("Categories", "/v1/catalog/categories", {"sortBy": "name", "sortOrder": "asc"}),
        ]
    )
    def test_get_resource_top_level_endpoints(self, endpoint, expected_path, expected_params) -> None:
        resource = cast(dict[str, Any], _get_resource(VENDR_ENDPOINTS[endpoint]))

        assert resource["name"] == endpoint
        assert resource["write_disposition"] == "replace"
        assert resource["table_format"] == "delta"
        assert resource["endpoint"]["path"] == expected_path
        assert resource["endpoint"]["params"] == expected_params
        assert resource["endpoint"]["data_selector"] == "data"
        assert resource["endpoint"]["paginator"] == {"type": "offset", "limit": 100, "total_path": None}

    @parameterized.expand([("ProductFamilies",), ("Products",)])
    def test_get_resource_rejects_fanout_endpoints(self, endpoint) -> None:
        with pytest.raises(ValueError, match="Fan-out endpoint"):
            _get_resource(VENDR_ENDPOINTS[endpoint])

    @parameterized.expand(
        [
            (429, False, 429),
        ]
    )
    def test_validate_credentials_status_mapping(self, status, expected_ok, expected_status) -> None:
        with scripted_network(always(ScriptedResponse(status=status, json={}))) as network:
            result = validate_credentials("secret-key")

        assert result == (expected_ok, expected_status)
        request = network.requests_log[0]
        assert request.url == "https://api.vendr.com/v1/catalog/companies?limit=1"
        assert request.headers["x-api-key"] == "secret-key"

    def test_validate_credentials_does_not_follow_redirects(self) -> None:
        with scripted_network(
            [ScriptedResponse(status=302, headers={"Location": "https://evil.example.com/"}), ScriptedResponse()]
        ) as network:
            result = validate_credentials("secret-key")

        assert result == (False, 302)
        assert len(network.requests_log) == 1

    def test_top_level_source_resumes_from_saved_state(self) -> None:
        result = _driver().run(
            "Companies",
            [ScriptedResponse(json={"data": []})],
            resume_state=VendrResumeConfig(paginator_state={"offset": 200}),
        )

        assert result.params("offset") == ["200"]

    def test_a_run_with_no_saved_state_starts_from_the_first_page(self) -> None:
        result = _driver().run("Companies", [ScriptedResponse(json={"data": []})])

        assert result.params("offset") == ["0"]

    def test_top_level_source_saves_checkpoints_after_batches(self) -> None:
        full_page = [{"id": str(i)} for i in range(100)]

        result = _driver().run(
            "Companies",
            [ScriptedResponse(json={"data": full_page}), ScriptedResponse(json={"data": [{"id": "last"}]})],
        )

        assert result.params("offset") == ["0", "100"]
        # A terminal (falsy) checkpoint is not persisted - the Redis TTL handles cleanup.
        assert result.saved_states == [VendrResumeConfig(paginator_state={"offset": 100})]

    @parameterized.expand([("ProductFamilies", "product-families"), ("Products", "products")])
    def test_fanout_wiring(self, endpoint, path_segment) -> None:
        result = _driver().run(
            endpoint,
            [
                ScriptedResponse(json={"data": [{"id": "c1"}, {"id": "c2"}]}),
                ScriptedResponse(json={"data": [{"id": "a"}]}),
                ScriptedResponse(json={"data": [{"id": "b"}]}),
            ],
        )

        assert result.raised is None
        assert result.paths == [
            "/v1/catalog/companies",
            f"/v1/catalog/companies/c1/{path_segment}",
            f"/v1/catalog/companies/c2/{path_segment}",
        ]
        # The parent list is sorted by name, the company-scoped children by sortOrder.
        assert [request.param("sortBy") for request in result.requests] == ["name", "sortOrder", "sortOrder"]
        assert result.params("sortOrder") == ["asc"] * 3
        assert result.params("limit") == ["100"] * 3
        assert [(row["id"], row["company_id"]) for row in result.rows] == [("a", "c1"), ("b", "c2")]
        assert result.response is not None
        assert result.response.primary_keys == ["id"]
