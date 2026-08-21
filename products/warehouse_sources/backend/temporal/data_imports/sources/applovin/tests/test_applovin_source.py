from typing import Optional

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.applovin.settings import (
    APPLOVIN_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.applovin.source import AppLovinSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.applovin import (
    AppLovinSourceConfig,
)

_SOURCE_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.applovin.source"


class TestAppLovinSource:
    def setup_method(self) -> None:
        self.source = AppLovinSource()
        self.team_id = 123
        self.config = AppLovinSourceConfig(api_key="report-key")

    def test_get_schemas(self) -> None:
        schemas = {schema.name: schema for schema in self.source.get_schemas(self.config, self.team_id)}

        assert set(schemas) == set(ENDPOINTS)
        for name, schema in schemas.items():
            # Every endpoint filters server-side on `day` via start/end.
            assert schema.supports_incremental is True
            assert schema.incremental_fields == INCREMENTAL_FIELDS[name]
            # Aggregate rows restate for a few days, so append would duplicate them.
            assert schema.supports_append is False
            assert schema.detected_primary_keys == APPLOVIN_ENDPOINTS[name].primary_keys

    @pytest.mark.parametrize(
        "probe_result, expected_valid, expected_message",
        [
            (True, True, None),
            (False, False, "Invalid AppLovin Report Key"),
        ],
    )
    @mock.patch(f"{_SOURCE_MODULE}.validate_applovin_credentials")
    def test_validate_credentials(
        self,
        mock_validate: mock.MagicMock,
        probe_result: bool,
        expected_valid: bool,
        expected_message: Optional[str],
    ) -> None:
        mock_validate.return_value = probe_result

        is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        mock_validate.assert_called_once_with("report-key")
