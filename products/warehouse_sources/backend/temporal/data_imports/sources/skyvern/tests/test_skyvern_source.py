import pytest
from unittest import mock

import structlog

from posthog.schema import SourceFieldInputConfig

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SkyvernSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.skyvern import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.skyvern.skyvern import SkyvernResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.skyvern.source import SkyvernSource
from products.warehouse_sources.backend.types import ExternalDataSourceType


def _inputs() -> SourceInputs:
    return SourceInputs(
        schema_name="runs",
        schema_id="s1",
        source_id="src1",
        team_id=1,
        should_use_incremental_field=False,
        db_incremental_field_last_value=None,
        db_incremental_field_earliest_value=None,
        incremental_field=None,
        incremental_field_type=None,
        job_id="job1",
        logger=structlog.get_logger(),
        reset_pipeline=False,
    )


class TestSkyvernSource:
    def setup_method(self):
        self.source = SkyvernSource()
        self.team_id = 1

    def test_source_type(self):
        assert self.source.source_type == ExternalDataSourceType.SKYVERN

    @pytest.mark.parametrize(
        "error_message",
        [
            "401 Client Error: Unauthorized for url: https://api.skyvern.com/v1/agents?page=1",
            "403 Client Error: Forbidden for url: http://localhost:8000/v1/runs?page=1",
        ],
    )
    def test_auth_errors_are_non_retryable(self, error_message):
        # The framework substring-matches these keys against the raised error, so a revoked key must
        # fail fast instead of retrying forever. The match must be host-agnostic since the base URL is
        # configurable (self-hosted).
        keys = self.source.get_non_retryable_errors()
        assert any(key in error_message for key in keys)

    @pytest.mark.parametrize(
        "endpoint,expected_incremental,expected_primary_keys",
        [
            # Only runs has a server-side timestamp filter (created_at_start); everything else must be
            # full-refresh so the picker never offers an incremental mode that would sync nothing.
            ("runs", True, ["workflow_run_id"]),
            ("workflows", False, ["workflow_permanent_id"]),
            ("schedules", False, ["workflow_schedule_id"]),
            ("browser_profiles", False, ["browser_profile_id"]),
            ("credentials", False, ["credential_id"]),
        ],
    )
    def test_schema_sync_capabilities(self, endpoint, expected_incremental, expected_primary_keys):
        config = SkyvernSourceConfig(api_key="k")
        schemas = {s.name: s for s in self.source.get_schemas(config, self.team_id)}

        schema = schemas[endpoint]
        assert schema.supports_incremental is expected_incremental
        assert schema.supports_append is False
        assert schema.detected_primary_keys == expected_primary_keys

    def test_get_schemas_can_filter_by_name(self):
        config = SkyvernSourceConfig(api_key="k")
        schemas = self.source.get_schemas(config, self.team_id, names=["runs"])
        assert [s.name for s in schemas] == ["runs"]

    def test_public_docs_table_catalog_renders(self):
        # lists_tables_without_credentials=True means the posthog.com <SourceTables /> section is fed by
        # this catalog built from a credential-free placeholder config. If it broke (bad canonical
        # import, get_schemas needing real creds), the public doc would silently show no tables.
        tables = self.source.get_documented_tables()
        names = {t["name"] for t in tables}
        assert names == {"workflows", "runs", "schedules", "browser_profiles", "credentials"}
        assert all(t["description"] for t in tables)
        runs = next(t for t in tables if t["name"] == "runs")
        assert "Incremental" in runs["sync_methods"]

    def test_validate_credentials_plumbs_key_and_base_url(self):
        config = SkyvernSourceConfig(api_key="secret", base_url="http://localhost:8000")
        with mock.patch.object(
            source_module, "validate_skyvern_credentials", return_value=(True, None)
        ) as mock_validate:
            result = self.source.validate_credentials(config, self.team_id)

        assert result == (True, None)
        mock_validate.assert_called_once_with("secret", "http://localhost:8000")

    def test_get_resumable_source_manager_bound_to_resume_config(self):
        manager = self.source.get_resumable_source_manager(_inputs())
        assert manager._data_class is SkyvernResumeConfig

    def test_config_has_required_api_key_and_optional_base_url(self):
        # api_key must stay a required secret and base_url optional, or self-hosted setup breaks and
        # the key stops being masked in the wizard.
        fields = {f.name: f for f in self.source.get_source_config.fields if isinstance(f, SourceFieldInputConfig)}
        assert fields["api_key"].required is True
        assert fields["api_key"].secret is True
        assert fields["base_url"].required is False

    def test_base_url_is_a_connection_host_field(self):
        # base_url decides where the API key is sent, so retargeting it must re-require the secret —
        # otherwise the stored key could be exfiltrated to an attacker-controlled host on edit.
        assert self.source.connection_host_fields == ["base_url"]
