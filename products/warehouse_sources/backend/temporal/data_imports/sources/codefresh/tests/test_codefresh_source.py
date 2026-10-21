import pytest
from unittest import mock

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.sources.codefresh.source import CodefreshSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.codefresh import (
    CodefreshSourceConfig,
)


class TestCodefreshSource:
    def setup_method(self) -> None:
        self.source = CodefreshSource()
        self.team_id = 123

    @parameterized.expand(
        [
            ("valid", True, None, True),
            ("invalid", False, "Your Codefresh API key is invalid or has been revoked.", False),
        ]
    )
    def test_validate_credentials_plumbs_through(
        self, _name: str, inner_valid: bool, inner_error: str | None, expected_valid: bool
    ) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.codefresh.source.validate_codefresh_credentials",
            return_value=(inner_valid, inner_error),
        ) as mocked:
            valid, error = self.source.validate_credentials(CodefreshSourceConfig(api_key="t"), self.team_id)
        mocked.assert_called_once_with("t", schema_name=None)
        assert valid is expected_valid
        if not expected_valid:
            assert error == inner_error


if __name__ == "__main__":
    pytest.main([__file__])
