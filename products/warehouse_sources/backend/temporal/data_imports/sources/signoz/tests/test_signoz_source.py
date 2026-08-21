import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.signoz import SigNozSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.signoz.source import SigNozSource

INCREMENTAL_ENDPOINTS = {"logs", "traces"}


class TestSigNozSource:
    def setup_method(self) -> None:
        self.source = SigNozSource()
        self.team_id = 123
        self.config = SigNozSourceConfig(host="example.signoz.io", api_key="signoz-key")

    def test_new_sources_default_to_v5(self) -> None:
        # New sources (no pin) must be created on the current SigNoz query_range API version.
        assert self.source.default_version == "v5"
        assert self.source.resolve_api_version(None) == "v5"

    @pytest.mark.parametrize("version", ["v1", "v5"])
    def test_existing_pin_is_honored(self, version: str) -> None:
        # Existing instances keep their pinned version verbatim after the default bump, so their
        # syncs are unaffected.
        assert version in self.source.supported_versions
        assert self.source.resolve_api_version(version) == version

    @pytest.mark.parametrize("version", ["v1", "v5"])
    def test_no_version_is_deprecated(self, version: str) -> None:
        # This is a plain update, not a sunset: neither label is deprecated, so the in-product
        # deprecation banner must stay dark for existing v1 pins.
        assert self.source.get_version_deprecation(version) is None
