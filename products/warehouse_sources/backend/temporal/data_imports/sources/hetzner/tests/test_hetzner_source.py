from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.facade.source_config import (
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.hetzner import (
    HetznerSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hetzner.settings import (
    ENDPOINTS,
    HETZNER_METRICS_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hetzner.source import HetznerSource


class TestHetznerSource:
    def setup_method(self) -> None:
        self.source = HetznerSource()
        self.team_id = 1

    def test_config_has_single_secret_token_field(self) -> None:
        # The token is a credential — it must render as a masked password input and be marked secret,
        # or it would be stored/echoed in plaintext.
        config = self.source.get_source_config
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/hetzner"
        fields = config.fields
        assert len(fields) == 1
        field = fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.name == "api_token"
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.required is True
        assert field.secret is True

    def test_only_metrics_endpoints_are_incremental(self) -> None:
        # List endpoints have no server-side timestamp filter, so they must not advertise incremental
        # or append. Metrics take a start/end window, but re-read their newest sample each run, so
        # they are merge-only: append would duplicate that sample.
        schemas = self.source.get_schemas(mock.MagicMock(), self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        for schema in schemas:
            is_metrics = schema.name in HETZNER_METRICS_ENDPOINTS
            assert schema.supports_incremental is is_metrics, schema.name
            assert schema.supports_append is False, schema.name
            assert [f["field"] for f in schema.incremental_fields] == (["timestamp"] if is_metrics else [])

    @parameterized.expand(
        [
            (
                "unauthorized",
                "401 Client Error: Unauthorized for url: https://api.hetzner.cloud/v1/servers?page=1",
            ),
            (
                "forbidden",
                "403 Client Error: Forbidden for url: https://api.hetzner.cloud/v1/volumes",
            ),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.hetzner.cloud/v1/servers"),
            ("server_error", "503 Server Error for url: https://api.hetzner.cloud/v1/servers"),
        ]
    )
    def test_transient_errors_stay_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("list", "servers", ["id"]),
            ("server_metrics", "server_metrics", ["server_id", "metric", "timestamp"]),
            ("load_balancer_metrics", "load_balancer_metrics", ["load_balancer_id", "metric", "timestamp"]),
            ("network_members", "network_members", ["network_id", "type", "id"]),
        ]
    )
    def test_source_for_pipeline_routes_schema(self, _name: str, schema_name: str, primary_keys: list[str]) -> None:
        config = HetznerSourceConfig(api_token="tok")
        inputs = mock.MagicMock()
        inputs.schema_name = schema_name
        response = self.source.source_for_pipeline(config, mock.MagicMock(), inputs)
        assert response.name == schema_name
        assert response.primary_keys == primary_keys

    def test_documented_tables_published_for_docs(self) -> None:
        # lists_tables_without_credentials must stay on so the public docs render the table catalog.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        names = {t["name"] for t in tables}
        assert set(ENDPOINTS).issubset(names)

    def test_canonical_descriptions_key_on_real_endpoints(self) -> None:
        # A description keyed on a name that isn't an endpoint never reaches enrichment (silent typo).
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions).issubset(set(ENDPOINTS))
        assert "servers" in descriptions
