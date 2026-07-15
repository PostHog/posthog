import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ImaggaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.imagga.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.imagga.source import ImaggaSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestImaggaSource:
    def setup_method(self) -> None:
        self.source = ImaggaSource()
        self.team_id = 123
        self.config = ImaggaSourceConfig(api_key="acc_test", api_secret="secret_test")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.IMAGGA

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Imagga"
        assert config.label == "Imagga"
        assert config.category == DataWarehouseSourceCategory.ENGINEERING___MONITORING
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # Kept behind the unreleased flag until the source has been exercised end to end.
        assert config.unreleasedSource is True
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/imagga"
        assert [f.name for f in config.fields] == ["api_key", "api_secret"]

    def test_api_secret_is_a_secret_password_field(self) -> None:
        # The secret must never render as plain text or be treated as non-sensitive by the serializer.
        field = next(f for f in self.source.get_source_config.fields if f.name == "api_secret")
        assert isinstance(field, SourceFieldInputConfig)
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — safe to surface in public docs.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_covers_all_endpoints_full_refresh_only(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # /usage exposes no server-side timestamp filter, so nothing may advertise incremental/append —
        # a client-side cursor over a single snapshot request is not incremental.
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["daily_usage"])
        assert [s.name for s in schemas] == ["daily_usage"]

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    @pytest.mark.parametrize(
        "observed_error,should_match",
        [
            ("401 Client Error: Unauthorized for url: https://api.imagga.com/v2/usage?concurrency=1", True),
            ("403 Client Error: Forbidden for url: https://api.imagga.com/v2/usage", True),
            ("429 Client Error: Too Many Requests for url: https://api.imagga.com/v2/usage", False),
            ("500 Server Error for url: https://api.imagga.com/v2/usage", False),
        ],
    )
    def test_non_retryable_errors_match_only_auth_failures(self, observed_error: str, should_match: bool) -> None:
        matched = any(key in observed_error for key in self.source.get_non_retryable_errors())
        assert matched is should_match

    @pytest.mark.parametrize(
        "probe_result,expected_valid",
        [(True, True), (False, False)],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.imagga.source.validate_imagga_credentials"
    )
    def test_validate_credentials(
        self, mock_validate: mock.MagicMock, probe_result: bool, expected_valid: bool
    ) -> None:
        mock_validate.return_value = probe_result

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert (error_message is None) is expected_valid
        mock_validate.assert_called_once_with("acc_test", "secret_test")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.imagga.source.imagga_source")
    def test_source_for_pipeline_plumbs_credentials_and_endpoint(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "daily_usage"

        self.source.source_for_pipeline(self.config, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "acc_test"
        assert kwargs["api_secret"] == "secret_test"
        assert kwargs["endpoint"] == "daily_usage"

    def test_canonical_descriptions_cover_all_endpoints(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions) == set(ENDPOINTS)
