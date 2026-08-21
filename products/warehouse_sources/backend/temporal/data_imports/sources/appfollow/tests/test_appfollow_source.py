import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.appfollow.source import AppfollowSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.appfollow import (
    AppfollowSourceConfig,
)


class TestAppfollowSource:
    def setup_method(self):
        self.source = AppfollowSource()
        self.team_id = 123
        self.config = AppfollowSourceConfig(api_key="tok_test")

    @pytest.mark.parametrize(
        "status,expected_ok",
        [
            (200, True),
            # A single account-wide token: a 403 still proves the token is genuine.
            (403, True),
            (401, False),
            (402, False),
            (500, False),
            (None, False),
        ],
    )
    def test_validate_credentials(self, status, expected_ok):
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.appfollow.source.check_credentials",
            return_value=status,
        ):
            ok, _ = self.source.validate_credentials(self.config, self.team_id)
            assert ok is expected_ok
