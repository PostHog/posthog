import pytest
from unittest.mock import patch


@pytest.fixture(autouse=True)
def _parallel_read_flag_off():
    # The flag lookup reads the schema row, and the contract tests run without a database.
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.shopify.source._is_parallel_read_enabled",
        return_value=False,
    ):
        yield
