from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.aiven import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.aiven.settings import AIVEN_ENDPOINTS, ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.aiven.source import AivenSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AivenSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _config() -> AivenSourceConfig:
    return AivenSourceConfig.from_dict({"api_token": "tok"})


class TestSourceConfig:
    def test_source_type(self) -> None:
        assert AivenSource().source_type == ExternalDataSourceType.AIVEN

    def test_config_shape(self) -> None:
        config = AivenSource().get_source_config
        assert config.name == "Aiven"
        assert config.releaseStatus == "alpha"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/aiven"

    def test_single_secret_token_field(self) -> None:
        fields = AivenSource().get_source_config.fields
        assert [f.name for f in fields] == ["api_token"]
        token = fields[0]
        assert isinstance(token, SourceFieldInputConfig)
        assert token.required is True
        assert token.secret is True
        assert token.type == "password"


class TestGetSchemas:
    def test_lists_all_endpoints_full_refresh_only(self) -> None:
        schemas = AivenSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # Aiven exposes no server-side timestamp filter, so nothing is incremental.
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)

    def test_clouds_off_by_default(self) -> None:
        by_name = {s.name: s for s in AivenSource().get_schemas(_config(), team_id=1)}
        assert by_name["clouds"].should_sync_default is False
        assert by_name["invoices"].should_sync_default is True

    def test_names_filter(self) -> None:
        schemas = AivenSource().get_schemas(_config(), team_id=1, names=["invoices", "invoice_lines"])
        assert {s.name for s in schemas} == {"invoices", "invoice_lines"}


class TestValidateCredentials:
    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    def test_maps_validation_result(self, _name: str, valid: bool, expected: bool) -> None:
        with patch.object(source_module, "validate_aiven_credentials", return_value=valid):
            ok, error = AivenSource().validate_credentials(_config(), team_id=1)
        assert ok is expected
        assert (error is None) is expected


class TestSourceForPipeline:
    def test_passes_token_and_schema_through(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "invoices"
        inputs.team_id = 7
        inputs.job_id = "job-1"
        with patch.object(source_module, "aiven_source", return_value=MagicMock()) as aiven_source:
            AivenSource().source_for_pipeline(_config(), inputs)
        kwargs = aiven_source.call_args.kwargs
        assert kwargs["api_token"] == "tok"
        assert kwargs["endpoint"] == "invoices"
        assert kwargs["team_id"] == 7
        assert kwargs["job_id"] == "job-1"


class TestDocsAndErrors:
    def test_documented_tables_cover_every_endpoint(self) -> None:
        # `lists_tables_without_credentials` is True, so the static catalog renders in public docs.
        tables = AivenSource().get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)

    def test_canonical_descriptions_key_on_real_endpoints(self) -> None:
        canonical = AivenSource().get_canonical_descriptions()
        assert set(canonical.keys()) <= set(AIVEN_ENDPOINTS.keys())
        assert set(canonical.keys()) == set(ENDPOINTS)

    def test_auth_errors_are_non_retryable(self) -> None:
        keys = AivenSource().get_non_retryable_errors().keys()
        assert any("401" in k for k in keys)
        assert any("403" in k for k in keys)
