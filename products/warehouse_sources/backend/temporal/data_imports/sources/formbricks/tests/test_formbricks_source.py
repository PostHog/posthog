import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.formbricks.formbricks import (
    FORMBRICKS_API_VERSION_V1,
    FORMBRICKS_API_VERSION_V2,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.formbricks.settings import FORMBRICKS_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.formbricks.source import FormbricksSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.formbricks import (
    FormbricksSourceConfig,
)


class TestFormbricksSource:
    def setup_method(self) -> None:
        self.source = FormbricksSource()
        self.team_id = 123
        self.config = FormbricksSourceConfig(api_key="fb-key", host="https://formbricks.example.com")

    def test_supports_v1_and_v2_with_v2_default(self) -> None:
        # New sources are stamped v2 (the version Formbricks recommends and that the responses
        # incremental sync requires); v1 stays supported so existing pins keep resolving.
        assert self.source.supported_versions == (FORMBRICKS_API_VERSION_V1, FORMBRICKS_API_VERSION_V2)
        assert self.source.default_version == FORMBRICKS_API_VERSION_V2

    @parameterized.expand(
        [
            ("responses", FORMBRICKS_API_VERSION_V2),
            ("contact_attribute_keys", FORMBRICKS_API_VERSION_V2),
            ("webhooks", FORMBRICKS_API_VERSION_V2),
            ("surveys", FORMBRICKS_API_VERSION_V1),
            ("contacts", FORMBRICKS_API_VERSION_V1),
            ("contact_attributes", FORMBRICKS_API_VERSION_V1),
            ("action_classes", FORMBRICKS_API_VERSION_V1),
        ]
    )
    def test_each_resource_targets_the_version_that_lists_it(self, endpoint: str, expected_version: str) -> None:
        # Only responses/contact-attribute-keys/webhooks have an environment-wide v2 list endpoint;
        # the rest are v1-only. A resource pointed at the wrong version would 404 (v1-only resource
        # on v2) or lose incremental filtering (responses on v1), so pin the routing per resource.
        assert f"/api/{expected_version}/management/" in FORMBRICKS_ENDPOINTS[endpoint].path

    def test_only_responses_supports_incremental(self) -> None:
        schemas = self.source.get_schemas(self.config, self.team_id)
        by_name = {s.name: s for s in schemas}
        assert by_name["responses"].supports_incremental is True
        assert {f["field"] for f in by_name["responses"].incremental_fields} == {"createdAt", "updatedAt"}
        for name, schema in by_name.items():
            if name == "responses":
                continue
            assert schema.supports_incremental is False
            assert schema.incremental_fields == []

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.formbricks.source.formbricks_source")
    def test_source_for_pipeline_plumbs_arguments(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "responses"
        inputs.team_id = self.team_id
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"
        inputs.incremental_field = "updatedAt"
        manager = mock.MagicMock()

        self.source.source_for_pipeline(self.config, manager, inputs)

        mock_source.assert_called_once()
        kwargs = mock_source.call_args.kwargs
        assert kwargs["host"] == "https://formbricks.example.com"
        assert kwargs["api_key"] == "fb-key"
        assert kwargs["endpoint"] == "responses"
        assert kwargs["resumable_source_manager"] is manager
        assert kwargs["team_id"] == self.team_id
        assert kwargs["should_use_incremental_field"] is True
        assert kwargs["db_incremental_field_last_value"] == "2026-01-01T00:00:00Z"
        assert kwargs["incremental_field"] == "updatedAt"

    @mock.patch("products.warehouse_sources.backend.temporal.data_imports.sources.formbricks.source.formbricks_source")
    def test_source_for_pipeline_drops_last_value_on_full_refresh(self, mock_source: mock.MagicMock) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "responses"
        inputs.team_id = self.team_id
        inputs.should_use_incremental_field = False
        inputs.db_incremental_field_last_value = "2026-01-01T00:00:00Z"

        self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)

        assert mock_source.call_args.kwargs["db_incremental_field_last_value"] is None

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Formbricks schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
