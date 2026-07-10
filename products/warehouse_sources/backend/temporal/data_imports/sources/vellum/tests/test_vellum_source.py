from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.vellum.source import VellumSource
from products.warehouse_sources.backend.temporal.data_imports.sources.vellum.vellum import VellumResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestVellumSourceConfig:
    def test_source_type(self) -> None:
        assert VellumSource().source_type == ExternalDataSourceType.VELLUM

    def test_source_config_shape(self) -> None:
        config = VellumSource().get_source_config
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/vellum"
        assert config.releaseStatus == ReleaseStatus.ALPHA

    def test_single_password_api_key_field(self) -> None:
        # The only credential is an environment-scoped API key; it must be a masked secret so the
        # serializer classifies it as sensitive and never echoes it back.
        fields = VellumSource().get_source_config.fields
        assert len(fields) == 1
        api_key = fields[0]
        assert isinstance(api_key, SourceFieldInputConfig)
        assert api_key.name == "api_key"
        assert api_key.type == SourceFieldInputConfigType.PASSWORD
        assert api_key.required is True
        assert api_key.secret is True


class TestVellumSchemas:
    def test_returns_all_endpoints_full_refresh(self) -> None:
        # Vellum exposes no server-side timestamp filter, so every table is full-refresh only.
        # supports_incremental leaking to True would let a sync silently drop rows.
        schemas = {s.name: s for s in VellumSource().get_schemas(MagicMock(), team_id=1)}
        assert set(schemas) == {
            "workflow_deployments",
            "prompt_deployments",
            "document_indexes",
            "documents",
            "workflow_execution_events",
        }
        for schema in schemas.values():
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_execution_events_is_opt_in(self) -> None:
        # The fan-out multiplies API calls by the deployment count, so it must be off by default.
        schemas = {s.name: s for s in VellumSource().get_schemas(MagicMock(), team_id=1)}
        assert schemas["workflow_execution_events"].should_sync_default is False
        assert schemas["workflow_deployments"].should_sync_default is True

    def test_names_filter(self) -> None:
        schemas = VellumSource().get_schemas(MagicMock(), team_id=1, names=["documents"])
        assert [s.name for s in schemas] == ["documents"]

    def test_lists_tables_without_credentials(self) -> None:
        # The catalog is static (no I/O), so public docs can render the table list. If get_schemas ever
        # starts hitting the network this flag must flip off or the docs endpoint would hang.
        assert VellumSource().lists_tables_without_credentials is True
        tables = {t["name"] for t in VellumSource().get_documented_tables()}
        assert "workflow_deployments" in tables


class TestVellumValidateCredentials:
    @parameterized.expand(
        [
            ("valid", (True, 200), True, None),
            ("bad_key_403", (False, 403), False, "Invalid Vellum API key"),
            ("unauthorized_401", (False, 401), False, "Invalid Vellum API key"),
            ("network_error", (False, None), False, "Could not connect to Vellum. Please try again later."),
        ]
    )
    def test_validate_credentials(
        self, _name: str, probe_result: tuple[bool, int | None], expected_ok: bool, expected_msg: str | None
    ) -> None:
        source = VellumSource()
        config = MagicMock(api_key="test-key")
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.vellum.source.check_credentials",
            return_value=probe_result,
        ):
            ok, msg = source.validate_credentials(config, team_id=1)
        assert ok is expected_ok
        assert msg == expected_msg


class TestVellumNonRetryableErrors:
    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.vellum.ai/v1/documents?limit=100"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.vellum.ai/v1/document-indexes"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        assert any(key in observed_error for key in VellumSource().get_non_retryable_errors())

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='api.vellum.ai', port=443): Read timed out."),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.vellum.ai/v1/documents"),
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.vellum.ai/v1/documents"),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, other_error: str) -> None:
        assert not any(key in other_error for key in VellumSource().get_non_retryable_errors())


class TestVellumResumableManager:
    def test_manager_bound_to_resume_config(self) -> None:
        inputs = MagicMock()
        manager = VellumSource().get_resumable_source_manager(inputs)
        assert manager._data_class is VellumResumeConfig

    def test_source_for_pipeline_plumbs_endpoint_and_key(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "documents"
        inputs.logger = MagicMock()
        manager = MagicMock()
        config = MagicMock(api_key="test-key")
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.vellum.source.vellum_source"
        ) as mock_source:
            VellumSource().source_for_pipeline(config, manager, inputs)
        _, kwargs = mock_source.call_args
        assert kwargs["endpoint"] == "documents"
        assert kwargs["api_key"] == "test-key"
        assert kwargs["resumable_source_manager"] is manager


def _canonical_descriptions() -> dict[str, Any]:
    return VellumSource().get_canonical_descriptions()


class TestVellumCanonicalDescriptions:
    def test_execution_events_parent_id_documented(self) -> None:
        # The injected parent id is part of the composite primary key; documenting it keeps the
        # AI-facing schema honest about a column the API itself never returns.
        columns = _canonical_descriptions()["workflow_execution_events"]["columns"]
        assert "workflow_deployment_id" in columns
        assert "span_id" in columns
