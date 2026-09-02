import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mightynetworks import (
    MightyNetworksSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mighty_networks.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.mighty_networks.source import MightyNetworksSource


class TestMightyNetworksSource:
    def setup_method(self):
        self.source = MightyNetworksSource()
        self.team_id = 123
        self.config = MightyNetworksSourceConfig(network_id="1234", api_key="key")

    def test_connection_host_fields_cover_network_id(self):
        # network_id is where the stored api_key is sent; retargeting it must re-require the key.
        assert self.source.connection_host_fields == ["network_id"]

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.mn.co/admin/v1/networks/1234/members?page=1",
            "403 Client Error: Forbidden for url: https://api.mn.co/admin/v1/networks/1234/members?page=1",
            "404 Client Error: Not Found for url: https://api.mn.co/admin/v1/networks/1234/members?page=1",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.mn.co/admin/v1/networks/1234/members",
            "500 Server Error: Internal Server Error for url: https://api.mn.co/admin/v1/networks/1234/members",
            "HTTPSConnectionPool(host='api.mn.co', port=443): Read timed out.",
        ],
    )
    def test_non_retryable_errors_do_not_match_transient(self, other_error):
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_are_all_full_refresh(self):
        # No list endpoint exposes a server-side updated_since/created_since filter.
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for schema in schemas.values():
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_lists_tables_without_credentials_publishes_catalog(self):
        # Static endpoint catalog (no I/O) — the public docs table list should render.
        assert self.source.lists_tables_without_credentials is True
        documented = self.source.get_documented_tables()
        assert {table["name"] for table in documented} == set(ENDPOINTS)

    @parameterized.expand(
        [
            ("valid", (True, 200), None, True, None),
            ("bad_token", (False, 401), None, False, "Invalid credentials"),
            (
                "missing_scope_at_create",
                (False, 403),
                None,
                True,
                None,
            ),
            (
                "missing_scope_for_schema",
                (False, 403),
                "Members",
                False,
                "Your Mighty Networks API key doesn't have permission to read this table.",
            ),
            (
                "wrong_network_id",
                (False, 404),
                None,
                False,
                "Mighty Networks couldn't find that network ID. Check the network ID and try again.",
            ),
            ("transport_error", (False, None), None, False, "Invalid credentials"),
        ]
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.mighty_networks.source.validate_mighty_networks_credentials"
    )
    def test_validate_credentials(
        self, _name, mock_return, schema_name, expected_valid, expected_message, mock_validate
    ):
        mock_validate.return_value = mock_return

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("key", "1234")

    @parameterized.expand([("letters", "abc"), ("empty", ""), ("path_injection", "1234/../evil"), ("float", "12.34")])
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.mighty_networks.source.validate_mighty_networks_credentials"
    )
    def test_validate_credentials_rejects_malformed_network_id(self, _name, network_id, mock_validate):
        config = MightyNetworksSourceConfig(network_id=network_id, api_key="key")

        is_valid, error_message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert "network ID" in (error_message or "")
        mock_validate.assert_not_called()

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.mighty_networks.source.check_endpoint_access"
    )
    def test_get_endpoint_permissions_probes_every_requested_endpoint(self, mock_check_access):
        mock_check_access.side_effect = lambda api_key, network_id, endpoint: (
            "missing scope" if endpoint == "Purchases" else None
        )

        permissions = self.source.get_endpoint_permissions(self.config, self.team_id, ["Members", "Purchases"])

        assert permissions == {"Members": None, "Purchases": "missing scope"}
        assert mock_check_access.call_count == 2
