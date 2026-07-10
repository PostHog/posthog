from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.trigger_dev import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.trigger_dev.source import TriggerDevSource
from products.warehouse_sources.backend.temporal.data_imports.sources.trigger_dev.trigger_dev import (
    TriggerDevResumeConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


class TestTriggerDevSourceConfig:
    def test_source_type(self) -> None:
        assert TriggerDevSource().source_type == ExternalDataSourceType.TRIGGERDEV

    def test_fields_require_secret_api_key_and_optional_base_url(self) -> None:
        fields = {f.name: f for f in TriggerDevSource().get_source_config.fields}
        assert fields["api_key"].required is True
        assert fields["api_key"].secret is True
        assert fields["base_url"].required is False
        assert fields["base_url"].secret is False

    def test_base_url_is_a_connection_host_field(self) -> None:
        # Retargeting base_url must re-require the secret, else the preserved key leaks to a new host.
        assert TriggerDevSource().connection_host_fields == ["base_url"]

    def test_lists_tables_without_credentials(self) -> None:
        # Static endpoint catalog with no I/O, so public docs can render the table list.
        assert TriggerDevSource.lists_tables_without_credentials is True


class TestTriggerDevSchemas:
    def test_runs_is_incremental_and_config_endpoints_are_full_refresh(self) -> None:
        schemas = {s.name: s for s in TriggerDevSource().get_schemas(MagicMock(), team_id=1)}
        assert set(schemas) == {"runs", "schedules", "queues"}
        assert schemas["runs"].supports_incremental is True
        assert [f["field"] for f in schemas["runs"].incremental_fields] == ["createdAt"]
        assert schemas["schedules"].supports_incremental is False
        assert schemas["queues"].supports_incremental is False

    def test_names_filter(self) -> None:
        schemas = TriggerDevSource().get_schemas(MagicMock(), team_id=1, names=["queues"])
        assert [s.name for s in schemas] == ["queues"]


class TestNonRetryableErrors:
    @parameterized.expand(
        [
            ("unauthorized", "401 Client Error: Unauthorized for url: https://api.trigger.dev/api/v1/runs"),
            ("forbidden", "403 Client Error: Forbidden for url: https://api.trigger.dev/api/v1/schedules"),
            ("invalid_body", "Invalid API key"),
        ]
    )
    def test_credential_errors_are_non_retryable(self, _name: str, observed: str) -> None:
        errors = TriggerDevSource().get_non_retryable_errors()
        assert any(key in observed for key in errors)

    @parameterized.expand(
        [
            ("read_timeout", "HTTPSConnectionPool(host='api.trigger.dev', port=443): Read timed out."),
            ("server_error", "500 Server Error: Internal Server Error"),
        ]
    )
    def test_transient_errors_remain_retryable(self, _name: str, observed: str) -> None:
        errors = TriggerDevSource().get_non_retryable_errors()
        assert not any(key in observed for key in errors)


class TestValidateCredentials:
    def test_blocks_unsafe_host_before_probing(self) -> None:
        # An internal/private base_url must be rejected without an outbound request being made.
        config = MagicMock(api_key="tr_prod_x", base_url="http://169.254.169.254")
        with (
            patch.object(source_module, "_is_host_safe", return_value=(False, "internal IP blocked")) as host_check,
            patch.object(source_module, "validate_trigger_dev_credentials") as probe,
        ):
            valid, error = TriggerDevSource().validate_credentials(config, team_id=1)
        assert valid is False
        assert error == "internal IP blocked"
        host_check.assert_called_once()
        probe.assert_not_called()

    def test_delegates_to_transport_when_host_is_safe(self) -> None:
        config = MagicMock(api_key="tr_prod_x", base_url=None)
        with (
            patch.object(source_module, "_is_host_safe", return_value=(True, None)),
            patch.object(source_module, "validate_trigger_dev_credentials", return_value=(True, None)) as probe,
        ):
            valid, error = TriggerDevSource().validate_credentials(config, team_id=1)
        assert valid is True
        assert error is None
        # Blank base_url resolves to the hosted API URL before probing.
        probe.assert_called_once_with("tr_prod_x", "https://api.trigger.dev")


class TestSourceForPipeline:
    def test_plumbs_resolved_base_url_and_incremental_inputs(self) -> None:
        config = MagicMock(api_key="tr_prod_x", base_url="https://trigger.acme.dev/")
        inputs = MagicMock(
            schema_name="runs",
            team_id=1,
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
            incremental_field="createdAt",
        )
        with (
            patch.object(source_module, "_is_host_safe", return_value=(True, None)),
            patch.object(source_module, "trigger_dev_source", return_value="SENTINEL") as build,
        ):
            result = TriggerDevSource().source_for_pipeline(config, MagicMock(), inputs)
        assert result == "SENTINEL"
        kwargs = build.call_args.kwargs
        assert kwargs["base_url"] == "https://trigger.acme.dev"
        assert kwargs["endpoint"] == "runs"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    def test_does_not_pass_watermark_when_not_incremental(self) -> None:
        config = MagicMock(api_key="tr_prod_x", base_url=None)
        inputs = MagicMock(
            schema_name="schedules",
            team_id=1,
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
            incremental_field=None,
        )
        with (
            patch.object(source_module, "_is_host_safe", return_value=(True, None)),
            patch.object(source_module, "trigger_dev_source", return_value="SENTINEL") as build,
        ):
            TriggerDevSource().source_for_pipeline(config, MagicMock(), inputs)
        assert build.call_args.kwargs["db_incremental_field_last_value"] is None


class TestResumableSourceManager:
    def test_returns_manager_bound_to_resume_config(self) -> None:
        inputs = MagicMock()
        manager = TriggerDevSource().get_resumable_source_manager(inputs)
        assert manager._data_class is TriggerDevResumeConfig


class TestGetDocumentedTables:
    def test_publishes_runs_table_with_canonical_description(self) -> None:
        tables = {t["name"]: t for t in TriggerDevSource().get_documented_tables()}
        assert set(tables) == {"runs", "schedules", "queues"}
        assert "execution" in tables["runs"]["description"].lower()
        assert "Incremental" in tables["runs"]["sync_methods"]
        assert tables["schedules"]["sync_methods"] == ["Full refresh"]
