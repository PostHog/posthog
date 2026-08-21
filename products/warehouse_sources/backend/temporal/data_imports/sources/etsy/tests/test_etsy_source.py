from products.warehouse_sources.backend.temporal.data_imports.sources.etsy.settings import ETSY_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.etsy.source import EtsySource

_INCREMENTAL_ENDPOINTS = [name for name, cfg in ETSY_ENDPOINTS.items() if cfg.incremental_fields]
_FULL_REFRESH_ENDPOINTS = [name for name, cfg in ETSY_ENDPOINTS.items() if not cfg.incremental_fields]


class TestEtsySourceClass:
    def test_api_version_metadata(self) -> None:
        assert EtsySource.supported_versions == ("v3",)
        assert EtsySource.default_version == "v3"
        assert EtsySource.api_docs_url is not None
        assert EtsySource.api_docs_url.startswith("https://")
