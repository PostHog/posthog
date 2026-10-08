from typing import Any

from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.framer.source import FramerSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.framer import FramerSourceConfig


def _config() -> FramerSourceConfig:
    return FramerSourceConfig(project_url="https://framer.com/projects/My-Site--" + "a" * 20, api_key="key")


def _inputs(schema_name: str, api_version: str | None = None) -> Any:
    inputs = mock.MagicMock()
    inputs.schema_name = schema_name
    inputs.api_version = api_version
    return inputs


class TestFramerSource:
    @parameterized.expand(
        [
            (None, "5.1.0"),  # no pin falls back to default_version
            ("0.1.29", "0.1.29"),
            ("9.9.9", "9.9.9"),  # a stored pin is honored verbatim
        ]
    )
    def test_source_for_pipeline_plumbs_config(self, api_version: str | None, expected_version: str) -> None:
        source = FramerSource()
        sentinel = mock.MagicMock()
        inputs = _inputs("CollectionItems", api_version=api_version)
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.framer.source.framer_source",
            return_value=sentinel,
        ) as factory:
            assert source.source_for_pipeline(_config(), inputs) is sentinel
        factory.assert_called_once_with(
            project=_config().project_url,
            api_key="key",
            endpoint="CollectionItems",
            protocol_version=expected_version,
            logger=inputs.logger,
        )

    def test_pool_exhausted_stays_retryable(self) -> None:
        observed_error = "Framer API error POOL_EXHAUSTED: busy"
        assert not any(key in observed_error for key in FramerSource().get_non_retryable_errors())
        assert any(key in observed_error for key in FramerSource().get_retryable_errors())
