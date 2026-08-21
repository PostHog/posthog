from products.warehouse_sources.backend.temporal.data_imports.sources.flutterwave.source import FlutterwaveSource

SOURCE_MODULE_PATCH = (
    "products.warehouse_sources.backend.temporal.data_imports.sources.flutterwave.source.flutterwave_source"
)


class TestSourceConfig:
    def test_pins_the_generally_available_api_version(self) -> None:
        # The request layer builds its base URL from this pin, so a drift here silently retargets
        # every customer's sync at a different API surface.
        source = FlutterwaveSource()
        assert source.supported_versions == ("v3",)
        assert source.default_version == "v3"
        assert source.resolve_api_version(None) == "v3"
