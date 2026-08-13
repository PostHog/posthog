import pytest
from unittest import mock

from posthog.schema import ReleaseStatus, SourceFieldInputConfig, SourceFieldInputConfigType

from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.smartreach import (
    SmartreachSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartreach.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.smartreach.smartreach import (
    SMARTREACH_API_V1,
    SMARTREACH_API_V3,
    SmartreachResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.smartreach.source import SmartreachSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestSmartreachSource:
    def setup_method(self) -> None:
        self.source = SmartreachSource()
        self.team_id = 123
        self.config = SmartreachSourceConfig(api_key="uk_test", team_id="team_abc")

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.SMARTREACH

    def test_supported_versions_and_default(self) -> None:
        # v3 is the new default for freshly created sources; v1 stays supported so pinned rows keep working.
        assert self.source.supported_versions == (SMARTREACH_API_V1, SMARTREACH_API_V3)
        assert self.source.default_version == SMARTREACH_API_V3

    def test_get_source_config(self) -> None:
        config = self.source.get_source_config
        assert config.name.value == "Smartreach"
        assert config.label == "Smartreach"
        assert config.releaseStatus == ReleaseStatus.ALPHA
        # A finished source is visible — it must not carry the scaffolding flag.
        assert not config.unreleasedSource
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/smartreach"

        field_names = [f.name for f in config.fields if isinstance(f, SourceFieldInputConfig)]
        assert field_names == ["api_key", "team_id"]

    def test_team_id_field_is_optional_non_secret(self) -> None:
        # Optional at the form level so pre-existing v1 sources (stored without it) still load;
        # validate_credentials enforces it for v3.
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "team_id")
        assert field.type == SourceFieldInputConfigType.TEXT
        assert field.required is False
        assert field.secret is False

    def test_api_key_field_is_secret_password(self) -> None:
        config = self.source.get_source_config
        field = next(f for f in config.fields if isinstance(f, SourceFieldInputConfig) and f.name == "api_key")
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_no_connection_host_fields(self) -> None:
        # The base URL is hardcoded per version and the account is implicit in the key; neither
        # `api_key` nor `team_id` retargets the host where the key is sent.
        assert self.source.connection_host_fields == []

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_covers_all_endpoints_as_full_refresh(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        assert {s.name for s in schemas} == set(ENDPOINTS)
        assert all(s.supports_incremental is False for s in schemas)
        assert all(s.supports_append is False for s in schemas)
        assert all(s.incremental_fields == [] for s in schemas)

    def test_get_schemas_filtered_by_names(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id, names=["campaigns"])
        assert len(schemas) == 1
        assert schemas[0].name == "campaigns"

    def test_get_schemas_filtered_unknown_name_returns_empty(self) -> None:
        assert self.source.get_schemas(self.config, self.team_id, names=["nope"]) == []

    def test_documented_tables_render_for_public_docs(self) -> None:
        # Exercises the credential-free catalog path used by the posthog.com docs.
        tables = self.source.get_documented_tables()
        assert {t["name"] for t in tables} == set(ENDPOINTS)
        assert all("Full refresh" in t["sync_methods"] for t in tables)

    @pytest.mark.parametrize(
        "observed_error",
        [
            "401 Client Error: Unauthorized for url: https://api.smartreach.io/api/v1/prospects?cursor=abc",
            "403 Client Error: Forbidden for url: https://api.smartreach.io/api/v1/campaigns",
        ],
    )
    def test_non_retryable_errors_match_auth_failures(self, observed_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert any(key in observed_error for key in non_retryable)

    @pytest.mark.parametrize(
        "unrelated_error",
        [
            "500 Server Error: Internal Server Error for url: https://api.smartreach.io/api/v1/prospects",
            "HTTPSConnectionPool(host='api.smartreach.io', port=443): Read timed out.",
            "429 Client Error: Too Many Requests for url: https://api.smartreach.io/api/v1/campaigns",
        ],
    )
    def test_non_retryable_errors_ignore_transient(self, unrelated_error: str) -> None:
        non_retryable = self.source.get_non_retryable_errors()
        assert not any(key in unrelated_error for key in non_retryable)

    @pytest.mark.parametrize(
        "status, expected_valid, expected_message",
        [
            (200, True, None),
            (401, False, "Invalid SmartReach API key"),
            (403, False, "Invalid SmartReach API key"),
            (500, False, "SmartReach returned HTTP 500"),
            (0, False, "Could not connect to SmartReach: boom"),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.smartreach.source.check_access")
    def test_validate_credentials(
        self,
        mock_check: mock.MagicMock,
        status: int,
        expected_valid: bool,
        expected_message: str | None,
    ) -> None:
        message = (
            "SmartReach returned HTTP 500"
            if status == 500
            else ("Could not connect to SmartReach: boom" if status == 0 else None)
        )
        mock_check.return_value = (status, message)
        is_valid, returned = self.source.validate_credentials(self.config, self.team_id)
        assert is_valid is expected_valid
        assert returned == expected_message

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.smartreach.source.check_access")
    def test_validate_credentials_probes_the_user_key(self, mock_check: mock.MagicMock) -> None:
        # The user key is account-wide, so validation probes the key, not a per-schema scope. The
        # resolved version (v3 by default) and the SmartReach team id ride along to the probe.
        mock_check.return_value = (200, None)
        self.source.validate_credentials(self.config, self.team_id, schema_name="campaigns")
        mock_check.assert_called_once_with("uk_test", SMARTREACH_API_V3, "team_abc")

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.smartreach.source.check_access")
    def test_validate_credentials_v3_requires_team_id(self, mock_check: mock.MagicMock) -> None:
        # v3 list endpoints reject requests without team_id, so fail fast (before probing) when it's
        # missing on a v3-resolved source rather than letting every table 400 mid-sync.
        config = SmartreachSourceConfig(api_key="uk_test")
        is_valid, message = self.source.validate_credentials(config, self.team_id, api_version=SMARTREACH_API_V3)
        assert is_valid is False
        assert message == "Enter your SmartReach team ID. The current SmartReach API needs it to return your data."
        mock_check.assert_not_called()

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.smartreach.source.check_access")
    def test_validate_credentials_v1_does_not_require_team_id(self, mock_check: mock.MagicMock) -> None:
        # A source pinned to v1 (no team_id in its stored config) still validates — v1 never sends one.
        mock_check.return_value = (200, None)
        config = SmartreachSourceConfig(api_key="uk_test")
        is_valid, _ = self.source.validate_credentials(config, self.team_id, api_version=SMARTREACH_API_V1)
        assert is_valid is True
        mock_check.assert_called_once_with("uk_test", SMARTREACH_API_V1, None)

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(mock.MagicMock())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is SmartreachResumeConfig

    @pytest.mark.parametrize(
        "pinned_version, expected_version",
        [
            (None, SMARTREACH_API_V3),  # unpinned resolves to the new default
            (SMARTREACH_API_V1, SMARTREACH_API_V1),  # a legacy pin keeps syncing under v1
            (SMARTREACH_API_V3, SMARTREACH_API_V3),
        ],
    )
    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.smartreach.source.smartreach_source")
    def test_source_for_pipeline_plumbs_arguments(
        self, mock_smartreach_source: mock.MagicMock, pinned_version: str | None, expected_version: str
    ) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "prospects"
        inputs.api_version = pinned_version
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_smartreach_source.assert_called_once()
        kwargs = mock_smartreach_source.call_args.kwargs
        assert kwargs["api_key"] == "uk_test"
        assert kwargs["endpoint"] == "prospects"
        assert kwargs["resumable_source_manager"] is manager
        # The resolved pin and the SmartReach team id reach the request layer.
        assert kwargs["api_version"] == expected_version
        assert kwargs["smartreach_team_id"] == "team_abc"

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown SmartReach schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
