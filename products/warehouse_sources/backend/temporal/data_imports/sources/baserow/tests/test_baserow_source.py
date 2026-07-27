from typing import Any

import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.baserow.baserow import BaserowResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.baserow.source import BaserowSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.baserow import (
    BaserowSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Two databases sharing a table name — only the colliding names get the id suffix.
TABLES = [
    {"id": 10, "name": "Projects", "order": 1, "database_id": 1},
    {"id": 11, "name": "Tasks", "order": 2, "database_id": 1},
    {"id": 12, "name": "Tasks", "order": 1, "database_id": 2},
]

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.baserow.source"


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "Projects",
        "schema_id": "schema-1",
        "source_id": "source-1",
        "team_id": 123,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-1",
        "logger": mock.MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestBaserowSource:
    def setup_method(self) -> None:
        self.source = BaserowSource()
        self.team_id = 123
        self.config = BaserowSourceConfig(database_token="test-token", base_url=None)

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.BASEROW

    def test_base_url_is_a_connection_host_field(self) -> None:
        # Changing base_url must force the database token to be re-entered, so the stored
        # token is never sent to a freshly-specified host.
        assert self.source.connection_host_fields == ["base_url"]

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config

        assert config.name.value == "Baserow"
        assert config.unreleasedSource is None
        assert config.releaseStatus == ReleaseStatus.ALPHA

        token_field, base_url_field = config.fields
        assert isinstance(token_field, SourceFieldInputConfig)
        assert token_field.name == "database_token"
        assert token_field.type == SourceFieldInputConfigType.PASSWORD
        assert token_field.required is True
        assert token_field.secret is True

        assert isinstance(base_url_field, SourceFieldInputConfig)
        assert base_url_field.name == "base_url"
        assert base_url_field.type == SourceFieldInputConfigType.TEXT
        assert base_url_field.required is False

    @pytest.mark.parametrize(
        "expected_key",
        ["401 Client Error", "403 Client Error", "404 Client Error", "Invalid Baserow instance URL"],
    )
    def test_non_retryable_errors(self, expected_key: str) -> None:
        assert expected_key in self.source.get_non_retryable_errors()

    def test_get_schemas_builds_one_schema_per_table(self) -> None:
        with mock.patch(f"{SOURCE_MODULE}.list_tables", return_value=TABLES):
            schemas = self.source.get_schemas(self.config, self.team_id)

        assert [s.name for s in schemas] == ["Projects", "Tasks (11)", "Tasks (12)"]
        assert all(s.supports_incremental is False and s.supports_append is False for s in schemas)
        assert schemas[0].schema_metadata == {"table_id": 10, "database_id": 1}

    def test_get_schemas_filters_by_names(self) -> None:
        with mock.patch(f"{SOURCE_MODULE}.list_tables", return_value=TABLES):
            schemas = self.source.get_schemas(self.config, self.team_id, names=["Tasks (12)"])

        assert [s.name for s in schemas] == ["Tasks (12)"]

    @pytest.mark.parametrize(
        ("probe_result", "expected_valid", "expected_message"),
        [
            ((True, 200), True, None),
            # Baserow returns 403 (ERROR_TOKEN_DOES_NOT_EXIST) for a bad token, not 401.
            ((False, 403), False, "Invalid Baserow database token"),
            ((False, 401), False, "Invalid Baserow database token"),
            ((False, None), False, "Could not connect to Baserow. Please check the instance URL."),
        ],
    )
    def test_validate_credentials_maps_probe_results(
        self, probe_result: tuple[bool, int | None], expected_valid: bool, expected_message: str | None
    ) -> None:
        with (
            mock.patch.object(BaserowSource, "is_database_host_valid", return_value=(True, None)),
            mock.patch(f"{SOURCE_MODULE}.validate_baserow_credentials", return_value=probe_result),
        ):
            valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert valid is expected_valid
        assert message == expected_message

    def test_validate_credentials_rejects_invalid_url_without_probing(self) -> None:
        config = BaserowSourceConfig(database_token="test-token", base_url="http://insecure.example.com")
        with mock.patch(f"{SOURCE_MODULE}.validate_baserow_credentials") as mock_probe:
            valid, message = self.source.validate_credentials(config, self.team_id)

        assert valid is False
        assert message == "Invalid Baserow instance URL"
        mock_probe.assert_not_called()

    def test_validate_credentials_rejects_blocked_host(self) -> None:
        with mock.patch.object(BaserowSource, "is_database_host_valid", return_value=(False, "Host is not allowed")):
            valid, message = self.source.validate_credentials(self.config, self.team_id)

        assert valid is False
        assert message == "Host is not allowed"

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert manager._data_class is BaserowResumeConfig

    def test_source_for_pipeline_resolves_table_id_from_schema_metadata(self) -> None:
        inputs = _make_inputs(schema_name="Projects", schema_metadata={"table_id": 10, "database_id": 1})
        manager = mock.MagicMock()

        with (
            mock.patch.object(BaserowSource, "is_database_host_valid", return_value=(True, None)),
            mock.patch(f"{SOURCE_MODULE}.baserow_rows_source") as mock_rows_source,
        ):
            response = self.source.source_for_pipeline(self.config, manager, inputs)

        assert response is mock_rows_source.return_value
        mock_rows_source.assert_called_once_with(
            base_url=None,
            database_token="test-token",
            table_id=10,
            schema_name="Projects",
            team_id=123,
            job_id="job-1",
            resumable_source_manager=manager,
        )

    def test_source_for_pipeline_rejects_blocked_host(self) -> None:
        with mock.patch.object(BaserowSource, "is_database_host_valid", return_value=(False, "Host is not allowed")):
            with pytest.raises(ValueError, match="Host is not allowed"):
                self.source.source_for_pipeline(self.config, mock.MagicMock(), _make_inputs())

    def test_get_endpoint_permissions_reports_unreadable_tables(self) -> None:
        reason = "The database token does not have read permission for this table."

        def permission_for(base_url: Any, token: str, table_id: int) -> str | None:
            return reason if table_id == 11 else None

        with (
            mock.patch(f"{SOURCE_MODULE}.list_tables", return_value=TABLES),
            mock.patch(f"{SOURCE_MODULE}.check_table_read_permission", side_effect=permission_for),
        ):
            result = self.source.get_endpoint_permissions(
                self.config, self.team_id, ["Projects", "Tasks (11)", "Deleted table"]
            )

        assert result == {"Projects": None, "Tasks (11)": reason, "Deleted table": None}

    def test_get_endpoint_permissions_never_blocks_on_listing_failure(self) -> None:
        with mock.patch(f"{SOURCE_MODULE}.list_tables", side_effect=RuntimeError("boom")):
            result = self.source.get_endpoint_permissions(self.config, self.team_id, ["Projects"])

        assert result == {"Projects": None}
