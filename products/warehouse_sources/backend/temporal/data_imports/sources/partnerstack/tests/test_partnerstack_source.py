from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.partnerstack import (
    PartnerStackSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.partnerstack.source import PartnerStackSource


class TestPartnerStackSource:
    def setup_method(self) -> None:
        self.source = PartnerStackSource()
        self.team_id = 123
        self.config = PartnerStackSourceConfig(public_key="pub", private_key="priv")

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["customers"])
        assert len(schemas) == 1
        assert schemas[0].name == "customers"

    @parameterized.expand(
        [
            ("401 Client Error: Unauthorized for url: https://api.partnerstack.com/api/v2/partnerships?limit=250",),
            ("403 Client Error: Forbidden for url: https://api.partnerstack.com/api/v2/customers?limit=250",),
        ]
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("500 Server Error: Internal Server Error for url: https://api.partnerstack.com/api/v2/partnerships",),
            ("429 Client Error: Too Many Requests for url: https://api.partnerstack.com/api/v2/customers",),
        ]
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    def test_validate_credentials_delegates(self) -> None:
        with scripted_network([ScriptedResponse(status=401)]) as network:
            result = self.source.validate_credentials(self.config, self.team_id)

        assert result == (False, "Invalid PartnerStack API keys")
        assert network.requests_log[0].headers["authorization"] == "Basic cHViOnByaXY="

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.partnerstack.source.partnerstack_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "partnerships"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["public_key"] == "pub"
        assert kwargs["private_key"] == "priv"
        assert kwargs["endpoint"] == "partnerships"
        assert kwargs["resumable_source_manager"] is manager

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        result = SourceDriver(self.source, self.config).run("not_a_table", [])

        assert isinstance(result.raised, ValueError)
        assert str(result.raised) == "Unknown PartnerStack schema 'not_a_table'"
        assert result.requests == []
