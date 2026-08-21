import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.appfigures.source import AppfiguresSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.appfigures import (
    AppfiguresSourceConfig,
)


class TestAppfiguresSource:
    def setup_method(self):
        self.source = AppfiguresSource()
        self.team_id = 123
        self.config = AppfiguresSourceConfig(personal_access_token="pat_test")

    @pytest.mark.parametrize(
        "status,schema_name,expected_ok",
        [
            (200, None, True),
            (200, "reviews", True),
            (401, None, False),
            (401, "reviews", False),
            # 403 at source-create is a valid token missing an unrelated scope — accept it.
            (403, None, True),
            # 403 for a specific schema means the token can't sync that table — reject.
            (403, "reviews", False),
            (500, None, False),
            (None, None, False),
        ],
    )
    def test_validate_credentials(self, status, schema_name, expected_ok):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.appfigures.source.check_credentials",
            return_value=status,
        ):
            ok, _ = self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)
            assert ok is expected_ok

    def test_validate_credentials_probes_schema_specific_path(self):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.appfigures.source.check_credentials",
            return_value=200,
        ) as probe:
            self.source.validate_credentials(self.config, self.team_id, schema_name="reviews")
            probe.assert_called_once_with("pat_test", "/reviews")

    def test_validate_credentials_defaults_to_products_path(self):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.appfigures.source.check_credentials",
            return_value=200,
        ) as probe:
            self.source.validate_credentials(self.config, self.team_id)
            probe.assert_called_once_with("pat_test", "/products/mine")
