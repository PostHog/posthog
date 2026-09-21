from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.charthop.source import ChartHopSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.charthop import (
    ChartHopSourceConfig,
)

CHECK_ACCESS_PATH = "products.warehouse_sources.backend.temporal.data_imports.sources.charthop.source.check_access"


class TestChartHopSource:
    def setup_method(self) -> None:
        self.source = ChartHopSource()
        self.team_id = 123
        self.config = ChartHopSourceConfig(api_key="charthop-token")

    def test_version_declaration_defaults_to_v2(self) -> None:
        # New sources are stamped with default_version; v1 stays supported for existing pins.
        assert self.source.supported_versions == ("v1", "v2")
        assert self.source.default_version == "v2"

    def test_org_id_is_a_connection_host_field(self) -> None:
        # Changing org_id must force the api_key to be re-entered, so the stored token is
        # never retargeted at another org the editor doesn't hold credentials for.
        assert self.source.connection_host_fields == ["org_id"]

    @parameterized.expand(
        [
            ("bad_token", "401 Client Error: ChartHop API authentication or permission error for url /v1/org"),
            ("no_permission", "403 Client Error: ChartHop API authentication or permission error for url x"),
            ("bad_token_fetch", "401 Client Error: Unauthorized for url: https://api.charthop.com/v2/org/x/job"),
            ("no_permission_fetch", "403 Client Error: Forbidden for url: https://api.charthop.com/v2/org/x/job"),
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

    @parameterized.expand([("unpinned", None, "v2"), ("legacy", "v1", "v1"), ("v2", "v2", "v2")])
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.charthop.source.resolve_org_id")
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.charthop.source.charthop_source")
    def test_source_for_pipeline_plumbs_arguments(
        self,
        _name: str,
        pin: str | None,
        expected_version: str,
        mock_charthop_source: mock.MagicMock,
        mock_resolve: mock.MagicMock,
    ) -> None:
        mock_resolve.return_value = "org-42"
        inputs = mock.MagicMock()
        inputs.schema_name = "changes"
        inputs.team_id = 123
        inputs.job_id = "job-1"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01"
        inputs.api_version = pin
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_resolve.assert_called_once_with("charthop-token", None)
        kwargs = mock_charthop_source.call_args.kwargs
        assert kwargs["api_key"] == "charthop-token"
        assert kwargs["org_id"] == "org-42"
        assert kwargs["endpoint"] == "changes"
        assert kwargs["team_id"] == 123
        assert kwargs["job_id"] == "job-1"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01"
        # An unpinned source resolves to default_version so its sync path matches new rows.
        assert kwargs["api_version"] == expected_version

    @parameterized.expand([("unpinned", None, "v2"), ("legacy", "v1", "v1")])
    @mock.patch(CHECK_ACCESS_PATH)
    def test_validate_credentials_probes_under_resolved_version(
        self, _name: str, pin: str | None, expected_version: str, mock_check: mock.MagicMock
    ) -> None:
        mock_check.return_value = (200, None)
        self.source.validate_credentials(self.config, self.team_id, schema_name="changes", api_version=pin)
        assert mock_check.call_args.args == ("charthop-token", None, "changes", expected_version)
