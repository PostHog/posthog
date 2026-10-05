from datetime import UTC, datetime

import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.promptingcompany import (
    PromptingCompanySourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.prompting_company.source import (
    PromptingCompanySource,
)

SOURCE = "products.warehouse_sources.backend.temporal.data_imports.sources.prompting_company.source"


@pytest.mark.parametrize(
    "start_date, error",
    [
        ("not-a-date", "YYYY-MM-DD"),
        ("2025-02-30", "YYYY-MM-DD"),
        ("20250101", "YYYY-MM-DD"),
        ("2025-01-02", "today or earlier"),
        ("2025-01-01", None),
        ("2024-12-31", None),
    ],
)
def test_start_date_validation(start_date: str, error: str | None) -> None:
    config = PromptingCompanySourceConfig(api_key="fake-test-key", product_id="product_example", start_date=start_date)
    with (
        patch(SOURCE + ".datetime") as clock,
        patch(SOURCE + ".validate_credentials", return_value=(True, None)) as probe,
    ):
        clock.now.return_value = datetime(2025, 1, 1, tzinfo=UTC)
        valid, message = PromptingCompanySource().validate_credentials(config, team_id=1)
    if error is not None:
        assert valid is False
        assert error in (message or "")
        probe.assert_not_called()
    else:
        assert (valid, message) == (True, None)
        probe.assert_called_once_with(config, None)
