import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudinary.source import CloudinarySource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cloudinary import (
    CloudinarySourceConfig,
)

_SOURCE = "products.warehouse_sources.backend.temporal.data_imports.sources.cloudinary.source"


def _config() -> CloudinarySourceConfig:
    return CloudinarySourceConfig(cloud_name="my-cloud", api_key="key", api_secret="secret", region="eu")


class TestCloudinarySourceClass:
    def test_an_unknown_schema_fails_before_any_request_goes_out(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "not_a_cloudinary_table"

        with pytest.raises(ValueError, match="Unknown Cloudinary endpoint"):
            CloudinarySource().source_for_pipeline(_config(), mock.MagicMock(), inputs)

    def test_the_configured_region_reaches_the_transport(self) -> None:
        inputs = mock.MagicMock()
        inputs.schema_name = "images"

        with mock.patch(f"{_SOURCE}.cloudinary_source") as cloudinary_source:
            CloudinarySource().source_for_pipeline(_config(), mock.MagicMock(), inputs)

        assert cloudinary_source.call_args.kwargs["region"] == "eu"
        assert cloudinary_source.call_args.kwargs["cloud_name"] == "my-cloud"
