import pytest
from unittest import mock

from posthog.schema import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.smartengage import (
    SmartEngageSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartengage.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.smartengage.source import SmartEngageSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestSmartEngageSource:
    def setup_method(self) -> None:
        self.source = SmartEngageSource()
        self.team_id = 123
        self.config = SmartEngageSourceConfig(api_key="se_test_key")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.SMARTENGAGE

    def test_get_source_config_is_released(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "SmartEngage"
        assert config.category == DataWarehouseSourceCategory.MARKETING___EMAIL
        # The source must stay visible: unreleasedSource hides it from every user.
        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/smartengage"

    def test_api_key_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        assert [f.name for f in config.fields] == ["api_key"]
        field = config.fields[0]
        assert isinstance(field, SourceFieldInputConfig)
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_get_schemas_are_full_refresh_only(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        # SmartEngage has no server-side timestamp filters, so no endpoint may advertise
        # incremental sync — a client-side "incremental" would silently miss nothing but
        # cost the same as full refresh and corrupt sync-type expectations.
        for schema in schemas:
            assert schema.supports_incremental is False
            assert schema.supports_append is False
            assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["tags"])
        assert [s.name for s in schemas] == ["tags"]

    @pytest.mark.parametrize(
        "observed_error,expected_non_retryable",
        [
            ("401 Client Error: Unauthorized for url: https://api.smartengage.com/avatars/list", True),
            ("403 Client Error: Forbidden for url: https://api.smartengage.com/tags/list", True),
            ("500 Server Error: Internal Server Error for url: https://api.smartengage.com/avatars/list", False),
        ],
    )
    def test_non_retryable_errors(self, observed_error: str, expected_non_retryable: bool) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable) is expected_non_retryable

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.smartengage.source.validate_smartengage_credentials"
    )
    def test_validate_credentials_plumbs_api_key(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = (True, None)
        assert self.source.validate_credentials(self.config, self.team_id) == (True, None)
        assert mock_validate.call_args.args == ("se_test_key",)

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.smartengage.source.smartengage_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_smartengage_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "tags"
        inputs.team_id = self.team_id
        inputs.job_id = "job-1"

        self.source.source_for_pipeline(self.config, inputs)

        kwargs = mock_smartengage_source.call_args.kwargs
        assert kwargs == {
            "api_key": "se_test_key",
            "endpoint": "tags",
            "team_id": self.team_id,
            "job_id": "job-1",
        }

    def test_canonical_descriptions_cover_endpoints(self) -> None:
        assert set(self.source.get_canonical_descriptions().keys()) == set(ENDPOINTS)
