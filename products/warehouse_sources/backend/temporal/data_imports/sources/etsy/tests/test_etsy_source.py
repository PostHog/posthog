from posthog.schema import DataWarehouseSourceCategory, ReleaseStatus

from products.warehouse_sources.backend.temporal.data_imports.sources.etsy.settings import ENDPOINTS, ETSY_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.etsy.source import EtsySource

_INCREMENTAL_ENDPOINTS = [name for name, cfg in ETSY_ENDPOINTS.items() if cfg.incremental_fields]
_FULL_REFRESH_ENDPOINTS = [name for name, cfg in ETSY_ENDPOINTS.items() if not cfg.incremental_fields]


class TestEtsySourceClass:
    def test_source_config(self) -> None:
        config = EtsySource().get_source_config

        assert config.label == "Etsy"
        assert config.category == DataWarehouseSourceCategory.E_COMMERCE
        assert config.releaseStatus == ReleaseStatus.ALPHA
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/etsy"
        assert config.iconPath == "/static/services/etsy.png"
        # A hidden source cannot be connected — a finished source must stay visible.
        assert config.unreleasedSource is None

    def test_shop_id_is_a_connection_host_field(self) -> None:
        # shop_id steers where the stored token is sent, so changing it must force credential re-entry.
        assert EtsySource().connection_host_fields == ["shop_id"]

    def test_api_version_metadata(self) -> None:
        assert EtsySource.supported_versions == ("v3",)
        assert EtsySource.default_version == "v3"
        assert EtsySource.api_docs_url is not None
        assert EtsySource.api_docs_url.startswith("https://")

    def test_lists_tables_without_credentials(self) -> None:
        # get_schemas is a static catalog with no I/O, so the public docs table list must render.
        assert EtsySource.lists_tables_without_credentials is True
        assert {table["name"] for table in EtsySource().get_documented_tables()} == set(ENDPOINTS)
