from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.deno_deploy import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.deno_deploy.source import DenoDeploySource


def _config() -> Any:
    config = MagicMock()
    config.access_token = "ddo_test"
    return config


class TestDenoDeploySourceConfig:
    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static endpoint catalog (no I/O), so the public docs catalog opts in.
        assert DenoDeploySource.lists_tables_without_credentials is True
        assert len(DenoDeploySource().get_documented_tables()) == 5


class TestGetSchemas:
    def test_all_endpoints_present(self) -> None:
        schemas = DenoDeploySource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == {"apps", "revisions", "domains", "analytics", "logs"}

    @parameterized.expand(
        [
            # Only the time-windowed endpoints with genuine server-side filters are incremental.
            ("apps", False, True),
            ("revisions", False, True),
            ("domains", False, True),
            ("analytics", True, True),
            # Logs are high volume, so they're deselected by default.
            ("logs", True, False),
        ]
    )
    def test_schema_flags(self, name: str, incremental: bool, should_sync_default: bool) -> None:
        schema = next(s for s in DenoDeploySource().get_schemas(_config(), team_id=1) if s.name == name)
        assert schema.supports_incremental is incremental
        assert schema.supports_append is incremental
        assert schema.should_sync_default is should_sync_default

    def test_names_filter(self) -> None:
        schemas = DenoDeploySource().get_schemas(_config(), team_id=1, names=["apps", "logs"])
        assert {s.name for s in schemas} == {"apps", "logs"}


class TestNonRetryableErrors:
    def test_auth_errors_are_non_retryable(self) -> None:
        errors = DenoDeploySource().get_non_retryable_errors()
        assert any("401 Client Error" in key for key in errors)
        assert any("403 Client Error" in key for key in errors)
        # Matches the base host, not a per-request path, so it survives any URL.
        assert all("https://api.deno.com" in key for key in errors)


class TestResumableWiring:
    def test_source_for_pipeline_drops_watermark_when_not_incremental(self) -> None:
        inputs = MagicMock()
        inputs.schema_name = "apps"
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.logger = MagicMock()
        with patch.object(source_module, "deno_deploy_source", return_value="response") as mock_source:
            DenoDeploySource().source_for_pipeline(_config(), MagicMock(), inputs)
        _, kwargs = mock_source.call_args
        # A full-refresh endpoint must not pass a stale watermark through.
        assert kwargs["db_incremental_field_last_value"] is None
