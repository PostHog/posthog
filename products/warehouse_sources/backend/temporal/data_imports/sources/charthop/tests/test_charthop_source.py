from unittest import mock

from parameterized import parameterized

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.charthop.charthop import ChartHopResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.charthop.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.charthop.source import ChartHopSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ChartHopSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

CHECK_ACCESS_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.charthop.source.check_access"


class TestChartHopSource:
    def setup_method(self) -> None:
        self.source = ChartHopSource()
        self.team_id = 123
        self.config = ChartHopSourceConfig(api_key="charthop-token")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.CHARTHOP

    def test_org_id_is_a_connection_host_field(self) -> None:
        # Changing org_id must force the api_key to be re-entered, so the stored token is
        # never retargeted at another org the editor doesn't hold credentials for.
        assert self.source.connection_host_fields == ["org_id"]

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "ChartHop"
        assert config.label == "ChartHop"
        assert config.releaseStatus == ReleaseStatus.ALPHA

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key", "org_id"]

    def test_api_key_field_is_secret_password_and_org_id_optional(self) -> None:
        config = self.source.get_source_config
        api_key = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert api_key.type == SourceFieldInputConfigType.PASSWORD
        assert api_key.secret is True
        assert api_key.required is True

        org_id = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "org_id")
        assert org_id.required is False
        assert org_id.secret is False

    def test_get_schemas_only_changes_is_incremental(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)

        by_name = {s.name: s for s in schemas}
        assert by_name["changes"].supports_incremental is True
        assert [f["field"] for f in by_name["changes"].incremental_fields] == ["date"]
        for name, schema in by_name.items():
            if name != "changes":
                assert schema.supports_incremental is False
                assert schema.incremental_fields == []

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["persons", "nope"])
        assert [s.name for s in schemas] == ["persons"]

    @parameterized.expand(
        [
            ("bad_token", "401 Client Error: ChartHop API authentication or permission error for url /v1/org"),
            ("no_permission", "403 Client Error: ChartHop API authentication or permission error for url x"),
            ("no_org_access", "ChartHop API token has no access to any organization"),
            (
                "multiple_orgs",
                "ChartHop API token can access multiple organizations. Set the organization ID or slug on the source.",
            ),
        ]
    )
    def test_non_retryable_errors_match_credential_failures(self, _name: str, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @parameterized.expand(
        [
            ("server_error", "ChartHop API error (retryable): status=503, url=x"),
            ("rate_limited", "ChartHop API rate limited: status=429, url=x"),
        ]
    )
    def test_non_retryable_errors_ignore_transient_failures(self, _name: str, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @parameterized.expand(
        [
            ("ok", 200, None, True, None),
            ("bad_token", 401, None, False, "Invalid ChartHop API token"),
            (
                "schema_forbidden",
                403,
                "persons",
                False,
                "Your ChartHop API token does not have permission to read 'persons'",
            ),
            ("org_forbidden", 403, None, False, "boom"),
            ("network_error", 0, None, False, "boom"),
        ]
    )
    @mock.patch(CHECK_ACCESS_PATH)
    def test_validate_credentials(
        self,
        _name: str,
        status: int,
        schema_name: str | None,
        expected_valid: bool,
        expected_message: str | None,
        mock_check: mock.MagicMock,
    ) -> None:
        mock_check.return_value = (status, "boom")
        is_valid, message = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)
        assert is_valid is expected_valid
        assert message == expected_message

    @mock.patch(CHECK_ACCESS_PATH)
    def test_validate_credentials_org_not_found(self, mock_check: mock.MagicMock) -> None:
        mock_check.return_value = (404, None)
        config = ChartHopSourceConfig(api_key="charthop-token", org_id="typo-org")
        is_valid, message = self.source.validate_credentials(config, self.team_id)
        assert is_valid is False
        assert message == "ChartHop organization 'typo-org' was not found"

    @mock.patch(CHECK_ACCESS_PATH)
    def test_validate_credentials_rejects_unknown_schema_without_probing(self, mock_check: mock.MagicMock) -> None:
        is_valid, message = self.source.validate_credentials(self.config, self.team_id, schema_name="not_a_table")
        assert is_valid is False
        assert message == "Unknown ChartHop schema 'not_a_table'"
        mock_check.assert_not_called()

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is ChartHopResumeConfig

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.charthop.source.resolve_org_id")
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.charthop.source.charthop_source")
    def test_source_for_pipeline_plumbs_arguments(
        self, mock_charthop_source: mock.MagicMock, mock_resolve: mock.MagicMock
    ) -> None:
        mock_resolve.return_value = "org-42"
        inputs = mock.MagicMock()
        inputs.schema_name = "changes"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_resolve.assert_called_once_with("charthop-token", None)
        kwargs = mock_charthop_source.call_args.kwargs
        assert kwargs["api_key"] == "charthop-token"
        assert kwargs["org_id"] == "org-42"
        assert kwargs["endpoint"] == "changes"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01"
