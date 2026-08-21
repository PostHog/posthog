from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.cursor.source import CursorSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cursor import CursorSourceConfig


class TestCursorSource:
    def setup_method(self):
        self.source = CursorSource()
        self.config = CursorSourceConfig(api_key="key_test")
        self.team_id = 123

    @parameterized.expand([(True, (True, None)), (False, (False, "Invalid Cursor Admin API key"))])
    def test_validate_credentials(self, valid, expected):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.cursor.source.validate_cursor_credentials",
            return_value=valid,
        ):
            assert self.source.validate_credentials(self.config, self.team_id) == expected
