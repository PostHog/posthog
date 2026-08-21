import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.salesforce.source import SalesforceSource


class TestSalesforceSourceVersions:
    def setup_method(self):
        self.source = SalesforceSource()

    def test_new_sources_default_to_v67(self):
        # New sources (no pin) must be created on the current API version.
        assert self.source.default_version == "v67.0"
        assert self.source.resolve_api_version(None) == "v67.0"

    @pytest.mark.parametrize("version", ["v61.0", "v67.0"])
    def test_existing_pin_is_honored(self, version):
        # Pinned rows keep their version even after the default bump.
        assert version in self.source.supported_versions
        assert self.source.resolve_api_version(version) == version
