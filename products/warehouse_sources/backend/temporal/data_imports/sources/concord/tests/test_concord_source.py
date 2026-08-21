from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.concord import source as source_module
from products.warehouse_sources.backend.temporal.data_imports.sources.concord.source import ConcordSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.concord import (
    ConcordSourceConfig,
)


class TestConcordSourceClass:
    def setup_method(self):
        self.source = ConcordSource()
        self.team_id = 123

    @parameterized.expand([("valid", True, True), ("invalid", False, False)])
    def test_validate_credentials(self, _name, underlying, expected_ok):
        with mock.patch.object(source_module, "validate_concord_credentials", return_value=underlying):
            ok, error = self.source.validate_credentials(
                ConcordSourceConfig(api_key="k", environment="production"), self.team_id
            )
        assert ok is expected_ok
        assert (error is None) is expected_ok
