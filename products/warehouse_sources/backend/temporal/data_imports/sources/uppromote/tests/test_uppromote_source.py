from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceFieldInputConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.uppromote.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.uppromote.source import UpPromoteSource
from products.warehouse_sources.backend.temporal.data_imports.sources.uppromote.uppromote import UpPromoteResumeConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.uppromote.source"


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "affiliates",
        "schema_id": "schema-id",
        "source_id": "source-id",
        "team_id": 1,
        "should_use_incremental_field": False,
        "db_incremental_field_last_value": None,
        "db_incremental_field_earliest_value": None,
        "incremental_field": None,
        "incremental_field_type": None,
        "job_id": "job-id",
        "logger": MagicMock(),
        "reset_pipeline": False,
    }
    defaults.update(overrides)
    return SourceInputs(**defaults)


class TestUpPromoteSource:
    def setup_method(self) -> None:
        self.source = UpPromoteSource()

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.UPPROMOTE

    def test_source_config_is_released_with_api_key_field(self) -> None:
        config = self.source.get_source_config
        assert config.name == SchemaExternalDataSourceType.UP_PROMOTE
        # unreleasedSource hides the connector from every user; a finished source must not carry it.
        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/uppromote"

        fields = {f.name: f for f in config.fields}
        assert set(fields.keys()) == {"api_key"}
        api_key_field = fields["api_key"]
        assert isinstance(api_key_field, SourceFieldInputConfig)
        assert api_key_field.type == "password"
        assert api_key_field.required is True

        webhook_fields = {f.name: f for f in config.webhookFields or []}
        assert set(webhook_fields.keys()) == {"signing_secret"}

    def test_get_schemas_covers_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=1)
        assert [s.name for s in schemas] == list(ENDPOINTS)

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=1, names=["affiliates", "referrals"])
        assert [s.name for s in schemas] == ["affiliates", "referrals"]

    @parameterized.expand(
        [
            # Windowed endpoints sync incrementally on the creation-time filter; programs has
            # no date filter and payments_unpaid is an aggregated snapshot — full refresh only.
            ("programs", False, False),
            ("affiliates", True, True),
            ("coupons", True, False),
            ("referrals", True, True),
            ("payments_paid", True, True),
            ("payments_unpaid", False, False),
        ]
    )
    def test_schema_sync_capabilities(self, endpoint: str, supports_incremental: bool, supports_webhooks: bool) -> None:
        schema = next(s for s in self.source.get_schemas(MagicMock(), team_id=1) if s.name == endpoint)
        assert schema.supports_incremental is supports_incremental
        assert schema.supports_webhooks is supports_webhooks
        # Every row is mutable (statuses, amounts), so append mode is never offered.
        assert schema.supports_append is False

    @parameterized.expand(
        [
            (True, None),
            (False, "UpPromote rejected the API key"),
        ]
    )
    def test_validate_credentials_delegates_to_transport(self, valid: bool, error: str | None) -> None:
        with patch(f"{SOURCE_MODULE}.validate_uppromote_credentials", return_value=(valid, error)) as mock_validate:
            result, message = self.source.validate_credentials(MagicMock(api_key="key-1"), team_id=1)

        mock_validate.assert_called_once_with("key-1")
        assert result is valid
        assert message == error

    def test_get_resumable_source_manager_binds_resume_config(self) -> None:
        manager = self.source.get_resumable_source_manager(_make_inputs())
        assert isinstance(manager, ResumableSourceManager)
        assert manager._data_class is UpPromoteResumeConfig

    def test_source_for_pipeline_plumbs_incremental_arguments(self) -> None:
        inputs = _make_inputs(
            schema_name="referrals",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
            incremental_field="created_at",
        )
        with patch(f"{SOURCE_MODULE}.uppromote_source") as mock_source:
            self.source.source_for_pipeline(MagicMock(api_key="key-1"), MagicMock(), inputs)

        kwargs = mock_source.call_args.kwargs
        assert kwargs["api_key"] == "key-1"
        assert kwargs["endpoint"] == "referrals"
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"

    def test_source_for_pipeline_drops_watermark_on_full_refresh(self) -> None:
        inputs = _make_inputs(
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-01-01T00:00:00Z",
        )
        with patch(f"{SOURCE_MODULE}.uppromote_source") as mock_source:
            self.source.source_for_pipeline(MagicMock(api_key="key-1"), MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_webhook_resource_map_routes_object_types(self) -> None:
        assert self.source.webhook_resource_map == {
            "affiliates": "affiliate",
            "referrals": "referral",
            "payments_paid": "payment",
        }

    def test_webhook_template_routes_and_verifies_signature(self) -> None:
        template = self.source.webhook_template
        assert template is not None
        assert template.id == "template-warehouse-source-uppromote"
        assert template.type == "warehouse_source_webhook"
        input_keys = {i["key"] for i in template.inputs_schema}
        assert {"signing_secret", "bypass_signature_check", "schema_mapping", "source_id"} <= input_keys
        assert "x-uppromote-signature" in template.code
        assert "produceToWarehouseWebhooks" in template.code

    def test_desired_webhook_events_exclude_unmergeable_status_changed(self) -> None:
        events = self.source.get_desired_webhook_events(MagicMock(), ["affiliates"])
        assert events is not None
        assert set(events) == {
            "affiliate.new",
            "affiliate.approved",
            "affiliate.inactive",
            "referral.new",
            "referral.approved",
            "referral.denied",
            "payment.paid",
        }
        # Status-changed payloads are {previous_status, current_status} diffs and can't be
        # merged into a table row.
        assert not any(event.endswith("status-changed") for event in events)

    @parameterized.expand(
        [
            ("create_webhook", "create_uppromote_webhook"),
            ("delete_webhook", "delete_uppromote_webhook"),
            ("get_external_webhook_info", "get_uppromote_webhook_info"),
        ]
    )
    def test_webhook_management_delegates_to_transport(self, method: str, transport_fn: str) -> None:
        with patch(f"{SOURCE_MODULE}.{transport_fn}") as mock_fn:
            getattr(self.source, method)(MagicMock(api_key="key-1"), "https://hooks.posthog.com/x", team_id=1)

        mock_fn.assert_called_once_with("key-1", "https://hooks.posthog.com/x")

    def test_sync_webhook_events_passes_all_desired_events(self) -> None:
        with patch(f"{SOURCE_MODULE}.sync_uppromote_webhook_events") as mock_fn:
            self.source.sync_webhook_events(
                MagicMock(api_key="key-1"), "https://hooks.posthog.com/x", team_id=1, eligible_schema_names=[]
            )

        api_key, webhook_url, events = mock_fn.call_args.args
        assert api_key == "key-1"
        assert webhook_url == "https://hooks.posthog.com/x"
        assert len(events) == 7

    def test_non_retryable_errors_cover_auth_failures(self) -> None:
        errors = self.source.get_non_retryable_errors()
        assert any("401" in key for key in errors)
        assert any("403" in key for key in errors)
        assert all("aff-api.uppromote.com" in key for key in errors)
