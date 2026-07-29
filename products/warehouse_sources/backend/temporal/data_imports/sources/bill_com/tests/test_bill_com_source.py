from typing import Optional

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.bill_com.bill_com import BillComResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.bill_com.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bill_com.source import BillComSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.billcom import (
    BillComSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.bill_com.source"


class TestBillComSource:
    def setup_method(self) -> None:
        self.source = BillComSource()
        self.team_id = 123
        self.config = BillComSourceConfig(
            username="finance@acme.com",
            password="pw",
            organization_id="org-1",
            dev_key="dev-key",
            environment="production",
        )

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.BILLCOM

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "BillCom"
        assert config.label == "BILL (formerly Bill.com)"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.unreleasedSource is None
        assert config.iconPath == "/static/services/bill_com.png"
        assert [field.name for field in config.fields] == [
            "username",
            "password",
            "organization_id",
            "dev_key",
            "environment",
        ]

    @pytest.mark.parametrize("field_name", ["password", "dev_key"])
    def test_credential_fields_are_secret_passwords(self, field_name: str) -> None:
        field = next(
            f
            for f in self.source.get_source_config.fields
            if isinstance(f, SourceFieldInputConfig) and f.name == field_name
        )
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_environment_field_defaults_to_production(self) -> None:
        field = next(f for f in self.source.get_source_config.fields if f.name == "environment")
        assert isinstance(field, SourceFieldSelectConfig)
        assert field.defaultValue == "production"
        assert {option.value for option in field.options} == {"production", "sandbox"}

    def test_api_version_is_pinned_to_the_path_the_source_calls(self) -> None:
        assert self.source.supported_versions == ("v3",)
        assert self.source.default_version == "v3"
        assert self.source.resolve_api_version(None) == "v3"

    def test_get_schemas_are_incremental_on_update_and_create_times(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)

        assert {schema.name for schema in schemas} == set(ENDPOINTS)
        assert all(schema.supports_incremental for schema in schemas)
        assert all(
            [f["field"] for f in schema.incremental_fields] == ["updatedTime", "createdTime"] for schema in schemas
        )

    def test_get_schemas_needs_no_credentials(self) -> None:
        # The endpoint catalog is static, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True

    @pytest.mark.parametrize("names, expected", [(["bills"], ["bills"]), (["nope"], []), (None, list(ENDPOINTS))])
    def test_get_schemas_filtered_by_names(self, names: Optional[list[str]], expected: list[str]) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=names)
        assert [schema.name for schema in schemas] == expected

    def test_canonical_descriptions_cover_every_endpoint(self) -> None:
        descriptions = self.source.get_canonical_descriptions()
        assert set(descriptions) == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "observed_error",
        [
            "BILL sign-in failed: Invalid credentials",
            "401 Client Error: Unauthorized for url: https://gateway.prod.bill.com/connect/v3/bills",
            "403 Client Error: Forbidden for url: https://gateway.prod.bill.com/connect/v3/users",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        assert any(key in observed_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "other_error",
        [
            "500 Server Error for url: https://gateway.prod.bill.com/connect/v3/bills",
            "429 Client Error: Too Many Requests for url: https://gateway.prod.bill.com/connect/v3/bills",
        ],
    )
    def test_non_retryable_errors_does_not_match_transient_failures(self, other_error: str) -> None:
        assert not any(key in other_error for key in self.source.get_non_retryable_errors())

    @pytest.mark.parametrize(
        "validate_result",
        [(True, None), (False, "BILL sign-in failed: Invalid credentials")],
    )
    @mock.patch(f"{_MODULE}.validate_bill_com_credentials")
    def test_validate_credentials(
        self, mock_validate: mock.MagicMock, validate_result: tuple[bool, Optional[str]]
    ) -> None:
        mock_validate.return_value = validate_result

        assert self.source.validate_credentials(self.config, self.team_id) == validate_result
        mock_validate.assert_called_once_with(
            username="finance@acme.com",
            password="pw",
            organization_id="org-1",
            dev_key="dev-key",
            environment="production",
            api_version="v3",
        )

    def test_get_resumable_source_manager_is_bound_to_the_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert manager._data_class is BillComResumeConfig

    @mock.patch(f"{_MODULE}.bill_com_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "bills"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-03-01T00:00:00.000Z"
        inputs.incremental_field = "updatedTime"
        inputs.api_version = None
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["username"] == "finance@acme.com"
        assert kwargs["dev_key"] == "dev-key"
        assert kwargs["environment"] == "production"
        assert kwargs["api_version"] == "v3"
        assert kwargs["endpoint"] == "bills"
        assert kwargs["incremental_field"] == "updatedTime"
        assert kwargs["db_incremental_field_last_value"] == "2026-03-01T00:00:00.000Z"
        assert kwargs["resumable_source_manager"] is manager

    @mock.patch(f"{_MODULE}.bill_com_source")
    def test_source_for_pipeline_drops_the_cursor_on_a_full_refresh(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "vendors"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-03-01T00:00:00.000Z"
        inputs.api_version = None

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_every_endpoint_advertises_incremental_fields(self) -> None:
        assert set(INCREMENTAL_FIELDS) == set(ENDPOINTS)
