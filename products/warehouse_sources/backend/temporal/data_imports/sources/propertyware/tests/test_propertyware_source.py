import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.propertyware import (
    PropertywareSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.propertyware.propertyware import (
    PropertywareResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.propertyware.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.propertyware.source import PropertywareSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestPropertywareSource:
    def setup_method(self) -> None:
        self.source = PropertywareSource()
        self.team_id = 123
        self.config = PropertywareSourceConfig(client_id="cid", client_secret="secret", system_id="org-1")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.PROPERTYWARE

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Propertyware"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/propertyware"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["client_id", "client_secret", "system_id"]

    def test_client_secret_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "client_secret")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    @pytest.mark.parametrize("name", ["client_id", "system_id"])
    def test_non_secret_identifier_fields_are_plain_text(self, name: str) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == name)
        assert field.type == SourceFieldInputConfigType.TEXT
        assert field.secret is False
        assert field.required is True

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.propertyware.com/pw/api/rest/v1/portfolios",
            "403 Client Error: Forbidden for url: https://api.propertyware.com/pw/api/rest/v1/bills",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable_errors)

    @pytest.mark.parametrize(
        "other_error",
        [
            "429 Client Error: Too Many Requests for url: https://api.propertyware.com/pw/api/rest/v1/portfolios",
            "500 Server Error for url: https://api.propertyware.com/pw/api/rest/v1/leases",
        ],
    )
    def test_transient_errors_are_not_marked_non_retryable(self, other_error: str) -> None:
        non_retryable_errors = self.source.get_non_retryable_errors()
        assert not any(key in other_error for key in non_retryable_errors)

    def test_get_schemas_lists_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

    def test_get_schemas_names_filter(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["Portfolios"])
        assert [s.name for s in schemas] == ["Portfolios"]

    @pytest.mark.parametrize("endpoint", sorted(ENDPOINTS))
    def test_every_endpoint_is_incremental_on_last_modified(self, endpoint: str) -> None:
        schema = next(s for s in self.source.get_schemas(self.config, self.team_id, names=[endpoint]))
        assert schema.supports_incremental is True
        assert [f["field"] for f in schema.incremental_fields] == ["lastModifiedDateTime"]
        assert schema.detected_primary_keys == ["id"]

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O — safe for public docs.
        assert self.source.lists_tables_without_credentials is True
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "status, schema_name, expected_ok",
        [
            (200, None, True),
            (200, "Portfolios", True),
            (403, None, True),  # a key scoped to fewer entities is tolerated at source-create
            (403, "Bills", False),  # but rejected when validating a schema it can't reach
            (401, None, False),
            (500, None, False),
            (None, None, False),
        ],
    )
    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.propertyware.source.validate_propertyware_credentials"
    )
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        status: int | None,
        schema_name: str | None,
        expected_ok: bool,
    ) -> None:
        mock_validate.return_value = status
        ok, _ = self.source.validate_credentials(self.config, self.team_id, schema_name)
        assert ok is expected_ok

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.propertyware.source.validate_propertyware_credentials"
    )
    def test_validate_credentials_probes_health_at_create(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = 200
        self.source.validate_credentials(self.config, self.team_id, None)
        assert mock_validate.call_args.args[3] == "/health"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.propertyware.source.validate_propertyware_credentials"
    )
    def test_validate_credentials_probes_specific_endpoint(self, mock_validate: mock.MagicMock) -> None:
        mock_validate.return_value = 200
        self.source.validate_credentials(self.config, self.team_id, "LeaseCharges")
        assert mock_validate.call_args.args[3] == "/leases/charges?limit=1"

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        inputs = mock.MagicMock()
        manager = self.source.get_resumable_source_manager(inputs)
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is PropertywareResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.propertyware.source.propertyware_source"
    )
    def test_source_for_pipeline_passes_credentials_and_cursor(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "Portfolios"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2020-01-01T00:00:00Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["client_id"] == "cid"
        assert kwargs["client_secret"] == "secret"
        assert kwargs["system_id"] == "org-1"
        assert kwargs["endpoint"] == "Portfolios"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2020-01-01T00:00:00Z"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.propertyware.source.propertyware_source"
    )
    def test_source_for_pipeline_omits_cursor_when_not_incremental(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "Portfolios"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2020-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None
