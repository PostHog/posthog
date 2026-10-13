from typing import Any

from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.featurebase.source import FeaturebaseSource

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
            # Conversations list takes no sort or timestamp param, so it is full refresh only;
            # tickets sweep newest-first on updatedAt.
            ("conversations", False, False),
            ("tickets", True, False),
            ("ticket_statuses", False, False),
            ("ticket_categories", False, False),
            ("conversation_tags", False, False),
            # Surveys and their responses take no sort or timestamp param either.
            ("surveys", False, False),
            ("survey_responses", False, False),
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

    def test_retryable_errors_cover_exhausted_transient_failures(self) -> None:
        errors = self.source.get_retryable_errors()
        # The sentinel `_fetch_page` raises after exhausting its own 429/5xx retries.
        assert any("Featurebase API error (retryable)" in error for error in errors)
        # A read timeout or dropped connection surfaces as a raw requests exception whose
        # message includes the connection pool host, not the sentinel above.
        assert any("do.featurebase.app" in error for error in errors)

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
