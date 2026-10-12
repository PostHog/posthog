import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.onfleet import (
    OnfleetSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.onfleet.source import OnfleetSource

_TRANSPORT_STATUS = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.onfleet.source.get_credentials_status"
)


class TestOnfleetSource:
    def setup_method(self):
        self.source = OnfleetSource()
        self.team_id = 123
        self.config = OnfleetSourceConfig(api_key="key")

    @pytest.mark.parametrize(
        "status, schema_name, expected_ok",
        [
            (200, None, True),
            (200, "tasks", True),
            (401, None, False),
            # 403 at source-create is a genuine but scoped key -> accept; reject for a specific schema.
            (403, None, True),
            (403, "tasks", False),
            (500, None, False),
            (None, None, False),
        ],
    )
    def test_validate_credentials(self, status, schema_name, expected_ok):
        with mock.patch(_TRANSPORT_STATUS, return_value=status):
            ok, _ = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)
        assert ok is expected_ok

    def test_source_for_pipeline_plumbs_arguments(self):
        inputs = mock.MagicMock()
        inputs.schema_name = "tasks"
        inputs.should_use_incremental_field = True
        inputs.db_incremental_field_last_value = 1700000000000
        inputs.incremental_field = "timeCreated"
        manager = mock.MagicMock()

        response = self.source.source_for_pipeline(self.config, manager, inputs)

        assert response.name == "tasks"
        assert response.primary_keys == ["id"]
