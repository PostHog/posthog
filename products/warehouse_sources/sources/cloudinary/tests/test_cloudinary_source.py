from products.warehouse_sources.backend.temporal.data_imports.sources.cloudinary.source import CloudinarySource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cloudinary import (
    CloudinarySourceConfig,
)


def _config() -> CloudinarySourceConfig:
    return CloudinarySourceConfig(cloud_name="my-cloud", api_key="key", api_secret="secret", region="eu")


class TestCloudinarySourceClass:
    def test_the_configured_region_reaches_the_transport(self) -> None:
        result = SourceDriver(CloudinarySource(), _config()).run(
            "images", [ScriptedResponse(json={"resources": [{"asset_id": "one"}]})]
        )

        assert result.raised is None
        assert result.requests[0].origin == "https://api-eu.cloudinary.com"
        assert result.requests[0].path == "/v1_1/my-cloud/resources/image"
