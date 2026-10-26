import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.chargify.source import ChargifySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.chargify import (
    ChargifySourceConfig,
)


class TestChargifySource:
    def setup_method(self) -> None:
        self.source = ChargifySource()
        self.team_id = 123
        self.config = ChargifySourceConfig(api_key="test-key", subdomain="acme")

    def test_subdomain_is_a_connection_host_field(self) -> None:
        # The stored API key is sent to https://{subdomain}.chargify.com, so changing subdomain
        # must force the key to be re-entered — otherwise it could be exfiltrated to another host.
        assert self.source.connection_host_fields == ["subdomain"]

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static catalog with no I/O, so the public docs table list can render.
        assert self.source.lists_tables_without_credentials is True

    @pytest.mark.parametrize(
        ("subdomain", "creds_valid", "expected_valid", "expected_message"),
        [
            ("acme", True, True, None),
            ("acme", False, False, "Invalid Chargify credentials"),
            ("has spaces", True, False, "Chargify site subdomain is invalid"),
            ("bad/slash", True, False, "Chargify site subdomain is invalid"),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.chargify.source.validate_chargify_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        subdomain: str,
        creds_valid: bool,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        mock_validate.return_value = creds_valid
        config = ChargifySourceConfig(api_key="test-key", subdomain=subdomain)

        is_valid, error_message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message

    def test_source_for_pipeline_leaves_an_endpoint_without_a_timestamp_unpartitioned(self) -> None:
        # Credit notes expose no stable creation timestamp, so partitioning must stay off rather
        # than point at a column the rows do not carry.
        result = SourceDriver(self.source, self.config).run(
            "CreditNotes", [ScriptedResponse(json={"credit_notes": []})]
        )
        response = result.response

        assert result.raised is None
        assert response is not None
        assert response.partition_mode is None
        assert response.partition_format is None
        assert response.partition_keys is None
        assert response.primary_keys == ["uid"]
