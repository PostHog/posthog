from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.vantage.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.vantage.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.vantage.source import VantageSource
from products.warehouse_sources.backend.temporal.data_imports.sources.vantage.vantage import VantageResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestVantageSourceConfig:
    def test_source_type(self) -> None:
        assert VantageSource().source_type == ExternalDataSourceType.VANTAGE

    def test_config_has_single_secret_api_key_field(self) -> None:
        # The token is a credential; a non-secret/non-password field would leak it in the UI and API.
        config = VantageSource().get_source_config
        fields = config.fields
        assert len(fields) == 1
        field = fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.name == "api_key"
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.required is True
        assert field.secret is True

    def test_config_is_alpha_and_unreleased(self) -> None:
        config = VantageSource().get_source_config
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/vantage"


class TestGetSchemas:
    def test_lists_every_endpoint_as_full_refresh(self) -> None:
        # Vantage exposes no server-side updated_after cursor, so every table is full refresh only;
        # advertising incremental/append here would let the pipeline skip rows on later syncs.
        schemas = VantageSource().get_schemas(MagicMock(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        assert all(not s.supports_incremental for s in schemas)
        assert all(not s.supports_append for s in schemas)

    def test_names_filter_restricts_output(self) -> None:
        schemas = VantageSource().get_schemas(MagicMock(), team_id=1, names=["budgets", "folders"])
        assert {s.name for s in schemas} == {"budgets", "folders"}


class TestValidateCredentials:
    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    def test_delegates_to_transport(self, _name: str, transport_result: bool, expected_ok: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.vantage.source.validate_vantage_credentials",
            return_value=transport_result,
        ):
            ok, error = VantageSource().validate_credentials(MagicMock(), team_id=1)
        assert ok is expected_ok
        assert (error is None) is expected_ok


class TestResumableWiring:
    def test_manager_bound_to_resume_config(self) -> None:
        manager = VantageSource().get_resumable_source_manager(MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is VantageResumeConfig

    def test_source_for_pipeline_plumbs_schema_name(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "cost_reports"
        config = MagicMock()
        config.api_key = "tok"
        response = VantageSource().source_for_pipeline(config, MagicMock(), inputs)
        assert response.name == "cost_reports"
        assert response.primary_keys == ["token"]


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.vantage.sh/v2/cost_reports?page=2"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.vantage.sh/v2/budgets"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed: str) -> None:
        non_retryable = VantageSource().get_non_retryable_errors()
        assert any(key in observed for key in non_retryable)

    @parameterized.expand(
        [
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.vantage.sh/v2/cost_reports"),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.vantage.sh/v2/budgets"),
            ("timeout", "HTTPSConnectionPool(host='api.vantage.sh', port=443): Read timed out."),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, observed: str) -> None:
        non_retryable = VantageSource().get_non_retryable_errors()
        assert not any(key in observed for key in non_retryable)


class TestPublicDocsCatalog:
    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O - the public docs Supported tables section depends on this.
        assert VantageSource.lists_tables_without_credentials is True
        tables = VantageSource().get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)

    def test_canonical_description_keys_are_real_endpoints(self) -> None:
        # A key that doesn't match an endpoint name would silently never apply to any synced table.
        assert set(CANONICAL_DESCRIPTIONS).issubset(set(ENDPOINTS))
