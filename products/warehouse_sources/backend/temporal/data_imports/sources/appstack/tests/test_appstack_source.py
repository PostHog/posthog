from unittest.mock import MagicMock, patch

import requests
from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.appstack.settings import (
    DEFAULT_INCREMENTAL_LOOKBACK_SECONDS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.appstack.source import AppstackSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.appstack import (
    AppstackSourceConfig,
)


def _config() -> AppstackSourceConfig:
    return AppstackSourceConfig(api_key="appstack-key")


class TestGetSchemas:
    def test_events_schema(self) -> None:
        schemas = AppstackSource().get_schemas(_config(), team_id=1)
        assert {s.name for s in schemas} == set(ENDPOINTS)

        events = next(s for s in schemas if s.name == "events")
        assert events.supports_incremental is True
        # The lookback re-reads a trailing window each run; append would duplicate the overlap.
        assert events.supports_append is False
        assert [f["field"] for f in events.incremental_fields] == ["event_time"]
        assert events.default_incremental_lookback_seconds == DEFAULT_INCREMENTAL_LOOKBACK_SECONDS


class TestValidateCredentials:
    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.appstack.source.validate_appstack_credentials"
    )
    def test_validate(self, _label: str, api_result: bool, expected_ok: bool, mock_validate: MagicMock) -> None:
        mock_validate.return_value = api_result
        ok, error = AppstackSource().validate_credentials(_config(), team_id=1)
        assert ok is expected_ok
        assert (error is None) is expected_ok

    @patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.appstack.source.validate_appstack_credentials"
    )
    def test_network_blip_is_not_reported_as_bad_credentials(self, mock_validate: MagicMock) -> None:
        mock_validate.side_effect = requests.ConnectionError("boom")
        ok, error = AppstackSource().validate_credentials(_config(), team_id=1)
        assert ok is False
        assert error is not None
        assert "try again" in error
