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

    def test_property_id_is_a_connection_host_field(self) -> None:
        # property_id scopes which property the preserved API key reads from, so retargeting it must
        # re-require the key - otherwise a group-level credential could be pointed at another property.
        assert self.source.connection_host_fields == ["property_id"]

    @mock.patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.cloudbeds.source.validate_credentials"
    )
    def test_validate_credentials_delegates_with_api_key_property_and_version(
        self, mock_validate: mock.MagicMock
    ) -> None:
        # The status-to-message mapping lives in cloudbeds.validate_credentials; here we only assert
        # the source probes with the configured credentials on the resolved version (default_version
        # before a row exists) and returns the delegate's verdict.
        mock_validate.return_value = (False, "Invalid Cloudbeds API key")
        result = self.source.validate_credentials(self.config, self.team_id)
        mock_validate.assert_called_once_with("cbat_key", "v1.3", "12345")
        assert result == (False, "Invalid Cloudbeds API key")

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
