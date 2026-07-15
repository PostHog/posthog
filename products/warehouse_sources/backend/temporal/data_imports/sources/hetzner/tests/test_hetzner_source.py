from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HetznerSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.hetzner.hetzner import HetznerResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.hetzner.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.hetzner.source import HetznerSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestHetznerSource:
    def setup_method(self) -> None:
        self.source = HetznerSource()
        self.team_id = 1

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.HETZNER

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

    def test_all_endpoints_are_full_refresh_only(self) -> None:
        # Hetzner exposes no server-side timestamp filter, so no table may advertise incremental or
        # append — otherwise the picker offers a mode that either syncs nothing new or duplicates rows.
        schemas = self.source.get_schemas(mock.MagicMock(), self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        for schema in schemas:
            assert schema.supports_incremental is False, schema.name
            assert schema.supports_append is False, schema.name
            assert schema.incremental_fields == []

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(mock.MagicMock(), self.team_id, names=["servers", "volumes"])
        assert {s.name for s in schemas} == {"servers", "volumes"}

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

    def test_validate_credentials_delegates_to_transport(self) -> None:
        config = HetznerSourceConfig(api_token="tok")
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.hetzner.source.validate_hetzner_credentials",
            return_value=(True, None),
        ) as validate:
            result = self.source.validate_credentials(config, self.team_id)
        validate.assert_called_once_with("tok")
        assert result == (True, None)

    def test_resumable_manager_bound_to_resume_config(self) -> None:
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert manager._data_class is HetznerResumeConfig

    def test_source_for_pipeline_plumbs_schema_name(self) -> None:
        config = HetznerSourceConfig(api_token="tok")
        inputs = mock.MagicMock()
        inputs.schema_name = "servers"
        response = self.source.source_for_pipeline(config, mock.MagicMock(), inputs)
        assert response.name == "servers"
        assert response.primary_keys == ["id"]

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
