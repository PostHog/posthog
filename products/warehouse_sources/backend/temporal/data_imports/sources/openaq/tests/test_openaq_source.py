from unittest.mock import patch

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.openaq import OpenAQSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.openaq.source import OpenAQSource


def _config() -> OpenAQSourceConfig:
    return OpenAQSourceConfig(api_key="key")


class TestOpenAQSchemas:
    def test_measurement_primary_key_is_sensor_and_period(self) -> None:
        # A non-unique key seeds duplicate rows that every later merge multi-matches; measurements have
        # no id of their own, so the key must be (sensor_id, datetime_from).
        schema = {s.name: s for s in OpenAQSource().get_schemas(_config(), team_id=1)}["measurements"]
        assert schema.detected_primary_keys == ["sensor_id", "datetime_from"]


class TestOpenAQValidateCredentials:
    @parameterized.expand([("valid", True), ("invalid", False)])
    def test_validate_credentials(self, _name: str, upstream_ok: bool) -> None:
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.openaq.source.validate_openaq_credentials",
            return_value=upstream_ok,
        ):
            valid, message = OpenAQSource().validate_credentials(_config(), team_id=1)
        assert valid is upstream_ok
        assert (message is None) is upstream_ok
