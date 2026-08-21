from unittest.mock import MagicMock, patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.featurebase.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.featurebase.source import FeaturebaseSource

SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.featurebase.source"


class TestFeaturebaseSource:
    def setup_method(self) -> None:
        self.source = FeaturebaseSource()

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
