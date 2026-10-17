import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kommo import KommoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kommo.settings import (
    ENDPOINT_CONFIG,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kommo.source import KommoSource

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.kommo.source"


class TestKommoSource:
    def setup_method(self) -> None:
        self.source = KommoSource()
        self.team_id = 123
        self.config = KommoSourceConfig(subdomain="acme", api_key="test-token")

    def test_subdomain_is_declared_as_a_connection_host_field(self) -> None:
        # The token is sent to https://<subdomain>.kommo.com, so editing the subdomain must
        # force the token to be re-entered instead of reusing the stored one.
        assert self.source.connection_host_fields == ["subdomain"]

    def test_incremental_fields_only_declared_where_a_server_side_filter_exists(self) -> None:
        assert set(INCREMENTAL_FIELDS) == {
            name for name, endpoint in ENDPOINT_CONFIG.items() if endpoint.incremental_param is not None
        }

    @pytest.mark.parametrize("subdomain", ["acme.amocrm.ru", "evil.example.com/acme", "", "acme_corp"])
    def test_validate_credentials_rejects_a_bad_subdomain_without_calling_kommo(self, subdomain: str) -> None:
        config = KommoSourceConfig(subdomain=subdomain, api_key="test-token")

        with scripted_network([]) as network:
            is_valid, message = self.source.validate_credentials(config, self.team_id)

        assert is_valid is False
        assert message is not None and "subdomain" in message
        assert network.requests_log == []

    @pytest.mark.parametrize("raw_subdomain", ["acme", "https://acme.kommo.com/"])
    def test_validate_credentials_probes_the_normalized_account(self, raw_subdomain: str) -> None:
        config = KommoSourceConfig(subdomain=raw_subdomain, api_key="test-token")

        with scripted_network([ScriptedResponse(status=200, json={})]) as network:
            assert self.source.validate_credentials(config, self.team_id) == (True, None)

        assert len(network.requests_log) == 1
        assert network.requests_log[0].url == "https://acme.kommo.com/api/v4/account"
        assert network.requests_log[0].headers["authorization"] == "Bearer test-token"

    @mock.patch(f"{_MODULE}.kommo_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "Leads"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1700000000
        manager = mock.MagicMock()
        config = KommoSourceConfig(subdomain="https://acme.kommo.com", api_key="test-token")

        response = self.source.source_for_pipeline(config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "test-token"
        assert kwargs["subdomain"] == "acme"
        assert kwargs["endpoint"] == "Leads"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == 1700000000
        assert kwargs["resumable_source_manager"] is manager
        assert response.primary_keys == ["id"]
        assert response.sort_mode == "asc"

    @pytest.mark.parametrize("schema_name", ["Tasks", "Events", "Pipelines"])
    @mock.patch(f"{_MODULE}.kommo_source")
    def test_source_for_pipeline_forces_full_refresh_on_unordered_endpoints(
        self, mock_source: mock.MagicMock, schema_name: str
    ) -> None:
        # A schema row can carry should_use_incremental_field from an older config; the source
        # must not honour it for an endpoint with no server-side filter.
        inputs = mock.MagicMock()
        inputs.schema_name = schema_name
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1700000000

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["should_use_incremental_field"] is False
        assert kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_a_bad_subdomain(self) -> None:
        config = KommoSourceConfig(subdomain="evil.example.com", api_key="test-token")

        result = SourceDriver(self.source, config).run("Leads", [])

        assert isinstance(result.raised, ValueError)
        assert result.requests == []
