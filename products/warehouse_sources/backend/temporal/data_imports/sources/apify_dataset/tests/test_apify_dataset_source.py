from products.warehouse_sources.backend.temporal.data_imports.sources.apify_dataset.source import ApifyDatasetSource


class TestApifyDatasetSource:
    def setup_method(self) -> None:
        self.source = ApifyDatasetSource()
        self.team_id = 123

    def test_source_config_basics(self) -> None:
        config = self.source.get_source_config
        assert config.label == "Apify Dataset"
        assert config.iconPath == "/static/services/apify_dataset.png"
        assert config.docsUrl == "https://posthog.com/docs/cdp/sources/apify-dataset"
        # Not hidden — a finished source ships visible, gated only by its alpha release status.
        assert getattr(config, "unreleasedSource", None) in (None, False)
        assert config.releaseStatus == "alpha"

    def test_connection_host_fields_includes_dataset_id(self) -> None:
        # dataset_id targets the stored token, so changing it must force re-entry of the secret.
        assert self.source.connection_host_fields == ["dataset_id"]
