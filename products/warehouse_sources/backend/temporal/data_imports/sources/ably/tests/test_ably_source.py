import pytest
from unittest.mock import MagicMock, patch

from posthog.schema import SourceFieldInputConfig, SourceFieldInputConfigType, SourceFieldSelectConfig

from products.warehouse_sources.backend.temporal.data_imports.sources.ably.source import AblySource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ably import AblySourceConfig


class TestAblySource:
    def setup_method(self):
        self.source = AblySource()
        self.team_id = 123

    def _field(self, name: str):
        return next(f for f in self.source.get_source_config.fields if f.name == name)

    def test_api_key_field_is_secret_password(self):
        field = self._field("api_key")
        assert isinstance(field, SourceFieldInputConfig)
        assert field.type == SourceFieldInputConfigType.PASSWORD
        assert field.secret is True
        assert field.required is True

    def test_unit_field_defaults_to_hour(self):
        field = self._field("unit")
        assert isinstance(field, SourceFieldSelectConfig)
        assert field.defaultValue == "hour"
        assert {option.value for option in field.options} == {"minute", "hour", "day", "month"}

    @pytest.mark.parametrize(
        ("status_code", "expected"),
        [
            (200, (True, None)),
            (401, (False, "Ably authentication failed. Please check your API key.")),
            (403, (False, "Ably authentication failed. Please check your API key.")),
        ],
    )
    def test_validate_credentials(self, status_code, expected):
        config = AblySourceConfig(api_key="app.key:secret", unit="hour")
        mock_response = MagicMock(status_code=status_code)
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.ably.ably.make_tracked_session"
        ) as mock_make_session:
            mock_make_session.return_value.get.return_value = mock_response
            assert self.source.validate_credentials(config, self.team_id) == expected

    def test_validate_credentials_rejects_malformed_key(self):
        config = AblySourceConfig(api_key="no-colon-here", unit="hour")
        ok, error = self.source.validate_credentials(config, self.team_id)
        assert ok is False
        assert error is not None and "malformed" in error.lower()
