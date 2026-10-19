from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.expo.source import ExpoSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.expo import ExpoSourceConfig

_SOURCE = "products.warehouse_sources.backend.temporal.data_imports.sources.expo.source"


class TestExpoSourceClass:
    def test_the_project_id_reaches_the_transport(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "builds"

        with mock.patch(f"{_SOURCE}.expo_source") as expo_source:
            ExpoSource().source_for_pipeline(
                ExpoSourceConfig(access_token="token", project_id="app-1"), mock.MagicMock(), inputs
            )

        assert expo_source.call_args.kwargs["project_id"] == "app-1"
