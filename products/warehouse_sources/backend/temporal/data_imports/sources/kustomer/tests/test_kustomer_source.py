import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kustomer import (
    KustomerSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kustomer.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.kustomer.source import KustomerSource

EXPECTED_PATHS = {
    "customers": "/v1/customers",
    "conversations": "/v1/conversations",
    "users": "/v1/users",
    "teams": "/v1/teams",
    "tags": "/v1/tags",
    "brands": "/v1/brands",
    "companies": "/v1/companies",
    "sub_statuses": "/v1/sub-statuses",
    "satisfaction_forms": "/v1/satisfaction",
    "messages": "/v1/messages",
    "notes": "/v1/notes",
    "queues": "/v1/routing/queues",
    "work_items": "/v1/routing/work-items",
    "work_sessions": "/v1/routing/work-sessions",
}


class TestKustomerSource:
    def setup_method(self):
        self.source = KustomerSource()
        self.team_id = 123
        self.config = KustomerSourceConfig(org_name="myorg", api_key="api-key")

    def test_org_name_is_a_connection_host_field(self):
        # The stored API key is sent to the host derived from org_name, so
        # retargeting it must force re-entry of the secret.
        assert self.source.connection_host_fields == ["org_name"]

    @pytest.mark.parametrize(
        "mock_return, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid Kustomer API credentials"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.kustomer.source.validate_kustomer_credentials"
    )
    def test_validate_credentials(self, mock_validate, mock_return, expected_valid, expected_message):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with(self.config.org_name, self.config.api_key)

    def test_version_declaration_defaults_to_v2_with_v1_supported(self):
        # Both labels resolve to the same /v1/ requests, so the default tracks the newest label.
        assert self.source.supported_versions == ("v1", "v2")
        assert self.source.default_version == "v2"
        assert self.source.deprecated_versions == ()

    @pytest.mark.parametrize("pinned_version", [None, "v1", "v2"])
    @pytest.mark.parametrize("endpoint", ENDPOINTS)
    def test_source_requests_v1_rest_paths_for_every_version(self, endpoint: str, pinned_version: str | None) -> None:
        # Every list resource is served at /v1/ for both vendor versions; a v2 pin
        # must not switch to /v2/, which would 404 the stream. Covering every endpoint
        # also guards against a per-resource /v2/ typo in the endpoint catalog.
        result = SourceDriver(self.source, self.config).run(
            endpoint, [ScriptedResponse(json={"data": [], "links": {}})], api_version=pinned_version
        )

        assert result.raised is None
        assert result.paths == [EXPECTED_PATHS[endpoint]]
