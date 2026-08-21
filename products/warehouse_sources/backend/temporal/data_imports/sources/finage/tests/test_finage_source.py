import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.finage import source as finage_source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.finage.source import FinageSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.finage import FinageSourceConfig


class TestFinageSource:
    def setup_method(self):
        self.source = FinageSource()
        self.team_id = 123

    @pytest.mark.parametrize(
        "status,schema_name,expected_valid",
        [
            (200, None, True),
            (401, None, False),
            # 403 = valid token, plan gap. Accepted at source-create, rejected for a specific schema.
            (403, None, True),
            (403, "aggregates", False),
            (None, None, False),
            (500, None, False),
        ],
    )
    def test_validate_credentials(self, status, schema_name, expected_valid):
        with mock.patch.object(finage_source_module, "validate_finage_credentials", return_value=status):
            valid, message = self.source.validate_credentials(self._config(), self.team_id, schema_name=schema_name)
        assert valid is expected_valid
        if not expected_valid:
            assert message

    def test_validate_credentials_rejects_bad_config_before_probing(self):
        # A malformed symbol list must be rejected without ever calling the Finage API.
        with mock.patch.object(finage_source_module, "validate_finage_credentials") as probe:
            valid, message = self.source.validate_credentials(self._config(symbols="not a ticker"), self.team_id)
        assert valid is False
        assert message
        probe.assert_not_called()

    def _config(self, symbols: str = "AAPL", start_date: str | None = None) -> FinageSourceConfig:
        return FinageSourceConfig(api_key="secret", symbols=symbols, start_date=start_date)
