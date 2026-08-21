import datetime

from products.warehouse_sources.backend.temporal.data_imports.sources.qualys_vmdr.source import QualysVmdrSource

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.qualys_vmdr.source"


class TestQualysVmdrSource:
    def setup_method(self):
        self.source = QualysVmdrSource()

    def test_default_version_is_4_0_and_2_0_is_deprecated(self):
        # New sources start on 4.0; 2.0 carries the vendor's announced sunset date and 4.0 is clean.
        assert self.source.default_version == "4.0"
        deprecation = self.source.get_version_deprecation("2.0")
        assert deprecation is not None and deprecation.sunset_at == datetime.date(2026, 6, 30)
        assert self.source.get_version_deprecation("4.0") is None
