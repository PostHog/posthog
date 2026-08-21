from unittest.mock import MagicMock, patch

from products.warehouse_sources.backend.temporal.data_imports.sources.trigger_dev import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.trigger_dev.source import TriggerDevSource


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


class TestValidateCredentials:
    def test_blocks_unsafe_host_before_probing(self) -> None:
        # An internal/private base_url must be rejected without an outbound request being made.
        config = MagicMock(api_key="tr_prod_x", base_url="https://169.254.169.254")
        with (
            patch.object(source_module, "_is_host_safe", return_value=(False, "internal IP blocked")) as host_check,
            patch.object(source_module, "validate_trigger_dev_credentials") as probe,
        ):
            valid, error = TriggerDevSource().validate_credentials(config, team_id=1)
        assert valid is False
        assert error == "internal IP blocked"
        host_check.assert_called_once()
        probe.assert_not_called()

    def test_rejects_plaintext_base_url_before_probing(self) -> None:
        # A non-HTTPS URL would leak the bearer token; reject it without any outbound request.
        config = MagicMock(api_key="tr_prod_x", base_url="http://trigger.acme.dev")
        with patch.object(source_module, "validate_trigger_dev_credentials") as probe:
            valid, error = TriggerDevSource().validate_credentials(config, team_id=1)
        assert valid is False
        assert error is not None
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
        assert result is build.return_value
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
