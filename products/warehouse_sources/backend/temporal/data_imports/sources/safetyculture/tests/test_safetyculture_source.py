import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SafetyCultureSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.safetyculture.safetyculture import (
    SafetyCultureResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.safetyculture.settings import (
    ENDPOINTS,
    SAFETYCULTURE_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.safetyculture.source import SafetyCultureSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestSafetyCultureSource:
    def setup_method(self) -> None:
        self.source = SafetyCultureSource()
        self.team_id = 123
        self.config = SafetyCultureSourceConfig(api_token="sc-token")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.SAFETYCULTURE

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "SafetyCulture"
        assert config.label == "SafetyCulture"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is visible — it must not carry the scaffolding flag.
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/safetyculture"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_token"]

    def test_api_token_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_token")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_no_connection_host_fields(self) -> None:
        # The only field is the secret API token; the base URL is hardcoded, so there is no
        # non-secret field an editor could retarget to reuse a preserved token against another host.
        assert self.source.connection_host_fields == []

    def test_lists_tables_without_credentials(self) -> None:
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_covers_all_endpoints(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        by_name = {s.name: s for s in schemas}
        for name, endpoint_config in SAFETYCULTURE_ENDPOINTS.items():
            assert by_name[name].supports_incremental is endpoint_config.supports_incremental
            assert by_name[name].supports_append is endpoint_config.supports_incremental

    def test_incremental_schemas_advertise_modified_at(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(self.config, self.team_id)}
        assert [f["field"] for f in schemas["inspections"].incremental_fields] == ["modified_at"]
        assert schemas["users"].incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["inspections"])
        assert len(schemas) == 1
        assert schemas[0].name == "inspections"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_for_public_docs(self) -> None:
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.safetyculture.io/feed/users",
            "403 Client Error: Forbidden for url: https://api.safetyculture.io/feed/inspections?archived=both",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @pytest.mark.parametrize(
        "unrelated_error",
        [
            "500 Server Error: Internal Server Error for url: https://api.safetyculture.io/feed/users",
            "429 Client Error: Too Many Requests for url: https://api.safetyculture.io/feed/inspections",
        ],
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid SafetyCulture API token"),
            # Feed access is permission-scoped, so a 403 on the probe feed still proves the token
            # itself is genuine — it must not block source-create.
            (403, True, None),
            (500, False, "SafetyCulture returned HTTP 500"),
            (0, False, "Could not connect to SafetyCulture: boom"),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.safetyculture.source.check_access")
    def test_validate_credentials_at_source_create(
        self,
        mock_check: mock.MagicMock,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        message = (
            "SafetyCulture returned HTTP 500"
            if status == 500
            else ("Could not connect to SafetyCulture: boom" if status == 0 else None)
        )
        mock_check.return_value = (status, message)
        is_valid, returned = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        assert returned == expected_message

    @pytest.mark.parametrize("status, expected_valid", [(200, True), (401, False), (403, False)])
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.safetyculture.source.check_access")
    def test_validate_credentials_for_schema_probes_that_feed(
        self, mock_check: mock.MagicMock, status: int, expected_valid: bool
    ) -> None:
        mock_check.return_value = (status, None)
        is_valid, _ = self.source.validate_credentials(self.config, self.team_id, schema_name="inspections")
        assert is_valid is expected_valid
        mock_check.assert_called_once_with(self.config.api_token, "/feed/inspections")

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is SafetyCultureResumeConfig

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.safetyculture.source.safetyculture_source"
    )
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "inspections"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2024-03-01T00:00:00.000Z"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_token"] == "sc-token"
        assert kwargs["endpoint"] == "inspections"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2024-03-01T00:00:00.000Z"

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.safetyculture.source.safetyculture_source"
    )
    def test_source_for_pipeline_drops_cursor_on_full_refresh(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "inspections"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2024-03-01T00:00:00.000Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown SafetyCulture schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
