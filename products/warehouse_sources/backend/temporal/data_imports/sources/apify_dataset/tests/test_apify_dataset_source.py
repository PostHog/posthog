from products.warehouse_sources.backend.temporal.data_imports.sources.apify_dataset.source import ApifyDatasetSource


class TestApifyDatasetSource:
    def setup_method(self) -> None:
        self.source = ApifyDatasetSource()
        self.team_id = 123

    def test_connection_host_fields_includes_dataset_id(self) -> None:
        # dataset_id targets the stored token, so changing it must force re-entry of the secret.
        assert self.source.connection_host_fields == ["dataset_id"]
