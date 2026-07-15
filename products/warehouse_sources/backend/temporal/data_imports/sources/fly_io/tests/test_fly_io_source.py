from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.fly_io import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.fly_io.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.fly_io.source import FlyIoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FlyIoSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> FlyIoSourceConfig:
    return FlyIoSourceConfig(api_token="FlyV1 secret", organization_slug="acme")


class TestSourceConfig:
    def test_source_type(self) -> None:
        assert FlyIoSource().source_type == ExternalDataSourceType.FLYIO

    def test_config_metadata(self) -> None:
        config = FlyIoSource().get_source_config
        assert config.label == "Fly.io"
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # docsUrl filename must match the posthog.com doc (fly-io).
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/fly-io"

    def test_org_slug_requires_credential_reentry(self) -> None:
        # Changing which org the token points at must re-require the token, so a preserved token
        # can't be retargeted at another org it happens to reach.
        assert FlyIoSource().connection_host_fields == ["organization_slug"]

    def test_config_fields(self) -> None:
        fields = {f.name: f for f in FlyIoSource().get_source_config.fields}
        assert set(fields) == {"api_token", "organization_slug"}
        token = fields["api_token"]
        assert isinstance(token, SourceFieldInputConfig)
        # The token is a secret — rendering it as plaintext would leak it in the form.
        assert token.type == SourceFieldInputConfigType.PASSWORD
        assert token.secret is True
        assert fields["organization_slug"].type == SourceFieldInputConfigType.TEXT


class TestGetSchemas:
    def test_returns_all_endpoints_full_refresh(self) -> None:
        schemas = {s.name: s for s in FlyIoSource().get_schemas(_config(), team_id=1)}
        assert set(schemas) == set(ENDPOINTS) == {"apps", "machines", "volumes"}
        # No verified server-side time filter, so every stream is full refresh only.
        for schema in schemas.values():
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.detected_primary_keys == ["id"]

    def test_names_filter(self) -> None:
        schemas = FlyIoSource().get_schemas(_config(), team_id=1, names=["machines"])
        assert [s.name for s in schemas] == ["machines"]


class TestValidateCredentials:
    @parameterized.expand([(True, None), (False, "bad token")])
    def test_delegates_to_transport(self, valid: bool, error: str | None) -> None:
        with patch.object(source_module, "validate_fly_io_credentials", return_value=(valid, error)) as mock_validate:
            result = FlyIoSource().validate_credentials(_config(), team_id=1)
        assert result == (valid, error)
        mock_validate.assert_called_once_with("FlyV1 secret", "acme")


class TestSourceForPipeline:
    def test_plumbs_config_and_schema_into_transport(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "machines"
        with patch.object(source_module, "fly_io_source") as mock_source:
            FlyIoSource().source_for_pipeline(_config(), inputs)
        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_token"] == "FlyV1 secret"
        assert kwargs["org_slug"] == "acme"
        assert kwargs["endpoint"] == "machines"


class TestCanonicalDescriptionsAndDocs:
    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        # A stream missing a canonical entry silently falls back to LLM enrichment; keep them aligned.
        descriptions = FlyIoSource().get_canonical_descriptions()
        assert set(descriptions) == set(ENDPOINTS)

    def test_documented_tables_render_without_credentials(self) -> None:
        # lists_tables_without_credentials=True is what makes the posthog.com Supported tables section
        # render; if get_schemas ever needed I/O this would hang the public docs endpoint.
        assert FlyIoSource().lists_tables_without_credentials is True
        tables = FlyIoSource().get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.machines.dev/v1/orgs/acme/machines"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.machines.dev/v1/apps?org_slug=acme"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = FlyIoSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='api.machines.dev', port=443): Read timed out."),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.machines.dev/v1/apps"),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        non_retryable = FlyIoSource().get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable)
