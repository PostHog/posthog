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

    def test_lists_tables_without_credentials(self):
        # get_schemas is a static catalog with no I/O, so the public docs can render the table list.
        assert self.source.lists_tables_without_credentials is True

    def test_get_schemas_filtered_by_names(self):
        schemas = self.source.get_schemas(self.config, self.team_id, names=["reviews"])
        assert len(schemas) == 1
        assert schemas[0].name == "reviews"

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

    @pytest.mark.parametrize(
        "schema_name,expected_path",
        [
            ("reviews", "/reviews"),
            # /ranks takes product ids in its path, so it can't be requested as-is. It shares the
            # `public:read` grant with reviews, so reviews is what gets probed.
            ("ranks", "/reviews"),
        ],
    )
    def test_validate_credentials_probes_schema_specific_path(self, schema_name: str, expected_path: str):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.appfigures.source.check_credentials",
            return_value=200,
        ) as probe:
            self.source.validate_credentials(self.config, self.team_id, schema_name=schema_name)
            probe.assert_called_once_with("pat_test", expected_path)

    def test_validate_credentials_defaults_to_products_path(self):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.appfigures.source.check_credentials",
            return_value=200,
        ) as probe:
            self.source.validate_credentials(self.config, self.team_id)
            probe.assert_called_once_with("pat_test", "/products/mine")
