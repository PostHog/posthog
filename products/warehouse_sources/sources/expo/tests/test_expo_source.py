from unittest import mock

from products.warehouse_sources.sources.expo._config import ExpoSourceConfig
from products.warehouse_sources.sources.expo.source import ExpoSource

_SOURCE = "products.warehouse_sources.sources.expo.source"


class TestExpoSourceClass:
    def test_the_project_id_reaches_the_transport(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "builds"

        with mock.patch(f"{_SOURCE}.expo_source") as expo_source:
            ExpoSource().source_for_pipeline(
                ExpoSourceConfig(access_token="token", project_id="app-1"), mock.MagicMock(), inputs
            )

        assert expo_source.call_args.kwargs["project_id"] == "app-1"
