from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import IntruderSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.intruder import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.intruder.intruder import IntruderResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.intruder.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.intruder.source import IntruderSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestSourceConfig:
    def test_source_type(self) -> None:
        assert IntruderSource().source_type == ExternalDataSourceType.INTRUDER

    def test_config_shape(self) -> None:
        config = IntruderSource().get_source_config
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # Kept behind the unreleased flag while the source is in alpha — hides it from the wizard.
        assert config.unreleasedSource is True
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/intruder"

    def test_single_secret_access_token_field(self) -> None:
        # A single required, secret bearer-token field is the whole auth surface — a non-secret or
        # non-required regression would leak or break the token input.
        fields = IntruderSource().get_source_config.fields
        assert len(fields) == 1
        field = fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.name == "access_token"
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.required is True


class TestGetSchemas:
    def test_all_endpoints_are_full_refresh(self) -> None:
        # Intruder exposes no verifiable server-side cursor, so every schema must ship full-refresh
        # only. A stray supports_incremental=True would advertise a cursor the transport can't honor.
        schemas = IntruderSource().get_schemas(IntruderSourceConfig(access_token="t"), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        assert all(s.supports_incremental is False and s.supports_append is False for s in schemas)

    def test_names_filter(self) -> None:
        schemas = IntruderSource().get_schemas(
            IntruderSourceConfig(access_token="t"), team_id=1, names=["targets", "tags"]
        )
        assert {s.name for s in schemas} == {"targets", "tags"}

    def test_documented_tables_match_endpoints(self) -> None:
        # lists_tables_without_credentials=True publishes the catalog to public docs with no I/O.
        tables = IntruderSource().get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)


class TestValidateCredentials:
    @parameterized.expand([("valid", True), ("invalid", False)])
    def test_delegates_to_transport(self, _name: str, transport_result: bool) -> None:
        with patch.object(source_module, "validate_intruder_credentials", return_value=transport_result) as mock:
            ok, error = IntruderSource().validate_credentials(IntruderSourceConfig(access_token="tok"), team_id=1)
        mock.assert_called_once_with("tok")
        assert ok is transport_result
        assert (error is None) is transport_result


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.intruder.io/v1/targets/"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.intruder.io/v1/issues/"),
        ]
    )
    def test_auth_errors_are_non_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = IntruderSource().get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("rate_limited", "429 Client Error: Too Many Requests for url: https://api.intruder.io/v1/targets/"),
            ("server_error", "500 Server Error: Internal Server Error for url: https://api.intruder.io/v1/scans/"),
        ]
    )
    def test_transient_errors_stay_retryable(self, _name: str, observed_error: str) -> None:
        non_retryable = IntruderSource().get_non_retryable_errors()
        assert not any(key in observed_error for key in non_retryable)


class TestPipelineWiring:
    def test_resumable_manager_bound_to_resume_config(self) -> None:
        inputs = MagicMock()
        manager = IntruderSource().get_resumable_source_manager(inputs)
        assert manager._data_class is IntruderResumeConfig

    def test_source_for_pipeline_plumbs_token_and_endpoint(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "occurrences"
        manager = MagicMock()
        with patch.object(source_module, "intruder_source") as mock_source:
            IntruderSource().source_for_pipeline(IntruderSourceConfig(access_token="tok"), manager, inputs)
        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["access_token"] == "tok"
        assert kwargs["endpoint"] == "occurrences"
        assert kwargs["resumable_source_manager"] is manager
