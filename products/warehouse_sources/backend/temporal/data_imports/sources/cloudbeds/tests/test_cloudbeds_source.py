import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudbeds.source import CloudbedsSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cloudbeds import (
    CloudbedsSourceConfig,
)


class TestCloudbedsSource:
    def setup_method(self) -> None:
        self.source = CloudbedsSource()
        self.team_id = 123
        self.config = CloudbedsSourceConfig(api_key="cbat_key", property_id="12345")

    def test_new_sources_default_to_latest_version(self) -> None:
        # New Cloudbeds sources are stamped with default_version; v1.3 is the current PMS API version.
        assert self.source.supported_versions == ("v1.2", "v1.3")
        assert self.source.default_version == "v1.3"

    @parameterized.expand([("pinned_legacy", "v1.2", "v1.2"), ("unpinned_uses_default", None, "v1.3")])
    def test_source_for_pipeline_plumbs_arguments(self, _name: str, pin: str | None, expected_version: str) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.cloudbeds.source.cloudbeds_source"
        ) as mock_source:
            inputs = mock.MagicMock()
            inputs.schema_name = "reservations"
            inputs.api_version = pin
            manager = mock.MagicMock()

            self.source.source_for_pipeline(self.config, manager, inputs)

            mock_source.assert_called_once()
            kwargs = mock_source.call_args.kwargs
            assert kwargs["api_key"] == "cbat_key"
            assert kwargs["endpoint"] == "reservations"
            assert kwargs["property_id"] == "12345"
            assert kwargs["resumable_source_manager"] is manager
            # A pinned row syncs on its own version; an unpinned row follows the new default.
            assert kwargs["api_version"] == expected_version

    def test_source_for_pipeline_rejects_unknown_schema(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_table"
        with pytest.raises(ValueError, match="Unknown Cloudbeds schema 'not_a_table'"):
            self.source.source_for_pipeline(self.config, mock.MagicMock(), inputs)
