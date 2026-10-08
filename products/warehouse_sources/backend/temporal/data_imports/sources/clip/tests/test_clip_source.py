import pytest
from time_machine import travel
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.clip.source import ClipSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clip import ClipSourceConfig


@travel("2026-07-03", tick=False)
@pytest.mark.parametrize(
    "start_date,message",
    [
        ("invalid", "Enter the start date in YYYY-MM-DD format."),
        ("20260701", "Enter the start date in YYYY-MM-DD format."),
        ("2026-07-04", "The start date must be today or earlier."),
        ("2026-07-03", None),
    ],
)
def test_validate_start_date(start_date: str, message: str | None) -> None:
    config = ClipSourceConfig(api_key="test-key", secret_key="test-secret", start_date=start_date)
    with patch(
        "products.warehouse_sources.backend.temporal.data_imports.sources.clip.source.validate_credentials",
        return_value=(True, None),
    ) as probe:
        assert ClipSource().validate_credentials(config, team_id=1) == (message is None, message)
        assert probe.call_count == (1 if message is None else 0)
