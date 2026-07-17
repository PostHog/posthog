from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.schema import (
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.featurebase.featurebase import (
    FeaturebaseResumeConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.featurebase.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.featurebase.source import FeaturebaseSource
from products.warehouse_sources.backend.types import ExternalDataSourceType

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.featurebase.source"


def _make_inputs(**overrides: Any) -> SourceInputs:
    defaults: dict[str, Any] = {
        "schema_name": "posts",
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


class TestFeaturebaseSource:
    def setup_method(self) -> None:
        self.source = FeaturebaseSource()

    def test_source_type(self) -> None:
        assert self.source.source_type == ExternalDataSourceType.FEATUREBASE

    def test_source_config_is_released_with_api_key_field(self) -> None:
        config = self.source.get_source_config
        assert config.name == SchemaExternalDataSourceType.FEATUREBASE
        # unreleasedSource hides the connector from every user; a finished source must not carry it.
        assert not config.unreleasedSource
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/featurebase"

        fields = {f.name: f for f in config.fields}
        assert set(fields.keys()) == {"api_key"}
        assert fields["api_key"].type == "password"
        assert fields["api_key"].required is True

        webhook_fields = {f.name: f for f in config.webhookFields or []}
        assert set(webhook_fields.keys()) == {"signing_secret"}

    def test_get_schemas_covers_every_endpoint(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=1)
        assert [s.name for s in schemas] == list(ENDPOINTS)

    def test_get_schemas_filters_by_names(self) -> None:
        schemas = self.source.get_schemas(MagicMock(), team_id=1, names=["posts", "boards"])
        assert [s.name for s in schemas] == ["posts", "boards"]

    @parameterized.expand(
        [
            # Posts/comments sweep newest-first with an early cutoff; changelogs filter
            # server-side via startDate. Everything else has no time filter — full refresh only.
            ("posts", True, True),
            ("comments", True, True),
            ("changelogs", True, True),
            ("boards", False, False),
            ("post_statuses", False, False),
            ("custom_fields", False, False),
            ("admins", False, False),
            ("companies", False, False),
            ("contacts", False, False),
            ("post_voters", False, False),
        ]
    )
    def test_schema_sync_capabilities(self, endpoint: str, incremental: bool, webhooks: bool) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(MagicMock(), team_id=1)}
        schema = schemas[endpoint]
        assert schema.supports_incremental is incremental
        assert schema.supports_webhooks is webhooks
        # All Featurebase resources are mutable, so merge is the only safe write disposition.
        assert schema.supports_append is False

    def test_post_voters_is_off_by_default(self) -> None:
        schemas = {s.name: s for s in self.source.get_schemas(MagicMock(), team_id=1)}
        assert schemas["post_voters"].should_sync_default is False

    @parameterized.expand(
        [
            ("valid", (True, None), True, None),
            ("invalid", (False, "Invalid API Key"), False, "Invalid API Key"),
        ]
    )
    def test_validate_credentials(
        self, _name: str, transport_result: tuple, expected_valid: bool, expected_error: str | None
    ) -> None:
        config = MagicMock(api_key="fb_test")
        with patch(f"{SOURCE_MODULE}.validate_featurebase_credentials", return_value=transport_result) as validate:
            valid, error = self.source.validate_credentials(config, team_id=1)
        validate.assert_called_once_with("fb_test")
        assert valid is expected_valid
        assert error == expected_error

    def test_non_retryable_errors_cover_featurebase_auth_statuses(self) -> None:
        errors = self.source.get_non_retryable_errors()
        # Featurebase responds 403 for invalid keys (verified live); 401 kept as a safety net.
        assert any(key.startswith("403 Client Error") for key in errors)
        assert any(key.startswith("401 Client Error") for key in errors)

    def test_resumable_source_manager_bound_to_resume_config(self) -> None:
        with patch.object(ResumableSourceManager, "__init__", return_value=None) as init:
            self.source.get_resumable_source_manager(_make_inputs())
        assert init.call_args.args[1] is FeaturebaseResumeConfig

    def test_source_for_pipeline_plumbs_incremental_inputs(self) -> None:
        config = MagicMock(api_key="fb_test")
        inputs = _make_inputs(
            schema_name="posts",
            should_use_incremental_field=True,
            db_incremental_field_last_value="2026-01-01T00:00:00.000Z",
            incremental_field="updatedAt",
        )
        manager = MagicMock()
        with (
            patch(f"{SOURCE_MODULE}.featurebase_source") as featurebase_source_mock,
            patch.object(FeaturebaseSource, "get_webhook_source_manager") as webhook_manager_mock,
        ):
            self.source.source_for_pipeline(config, manager, inputs)

        kwargs = featurebase_source_mock.call_args.kwargs
        assert kwargs["api_key"] == "fb_test"
        assert kwargs["endpoint"] == "posts"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["webhook_source_manager"] is webhook_manager_mock.return_value
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00.000Z"
        assert kwargs["incremental_field"] == "updatedAt"

    def test_source_for_pipeline_drops_watermark_on_full_refresh(self) -> None:
        # A stale watermark from a previous incremental setup must not leak into a
        # full-refresh run and silently truncate the sweep.
        config = MagicMock(api_key="fb_test")
        inputs = _make_inputs(
            should_use_incremental_field=False,
            db_incremental_field_last_value="2026-01-01T00:00:00.000Z",
        )
        with (
            patch(f"{SOURCE_MODULE}.featurebase_source") as featurebase_source_mock,
            patch.object(FeaturebaseSource, "get_webhook_source_manager"),
        ):
            self.source.source_for_pipeline(config, MagicMock(), inputs)

        assert featurebase_source_mock.call_args.kwargs["db_incremental_field_last_value"] is None


class TestFeaturebaseWebhooks:
    def setup_method(self) -> None:
        self.source = FeaturebaseSource()
        self.config = MagicMock(api_key="fb_test")

    def test_webhook_resource_map_routes_item_object_types(self) -> None:
        # Keys must be schema names from get_schemas; values must match data.item.object in
        # webhook payloads — this is what routes an event into the right warehouse table.
        assert self.source.webhook_resource_map == {
            "posts": "post",
            "comments": "comment",
            "changelogs": "changelog",
        }
        schema_names = {s.name for s in self.source.get_schemas(MagicMock(), team_id=1)}
        assert set(self.source.webhook_resource_map.keys()) <= schema_names

    def test_webhook_template_present(self) -> None:
        template = self.source.webhook_template
        assert template is not None
        assert template.id == "template-warehouse-source-featurebase"
        assert template.type == "warehouse_source_webhook"
        input_keys = {i["key"] for i in template.inputs_schema}
        assert {"signing_secret", "schema_mapping", "source_id"} <= input_keys

    def test_desired_webhook_events_only_mapped_topics(self) -> None:
        topics = self.source.get_desired_webhook_events(self.config, ["posts"]) or []
        assert set(topics) == {
            "post.created",
            "post.updated",
            "comment.created",
            "comment.updated",
            "changelog.published",
        }
        # Deleted-object topics would resurrect deleted rows through the merge path.
        assert not any(topic.endswith(".deleted") for topic in topics)

    @parameterized.expand(
        [
            ("create_webhook", "create_featurebase_webhook"),
            ("delete_webhook", "delete_featurebase_webhook"),
            ("get_external_webhook_info", "get_featurebase_webhook_info"),
        ]
    )
    def test_webhook_methods_delegate_to_transport(self, method_name: str, transport_name: str) -> None:
        with patch(f"{SOURCE_MODULE}.{transport_name}") as transport:
            result = getattr(self.source, method_name)(self.config, "https://us.posthog.com/webhook", team_id=1)
        transport.assert_called_once_with("fb_test", "https://us.posthog.com/webhook")
        assert result is transport.return_value

    def test_sync_webhook_events_passes_desired_topics(self) -> None:
        with patch(f"{SOURCE_MODULE}.sync_featurebase_webhook_events") as transport:
            self.source.sync_webhook_events(self.config, "https://us.posthog.com/webhook", 1, ["posts"])
        api_key, url, topics = transport.call_args.args
        assert api_key == "fb_test"
        assert url == "https://us.posthog.com/webhook"
        assert "changelog.published" in topics
