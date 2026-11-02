import pytest
from time_machine import travel

from products.warehouse_sources.backend.temporal.data_imports.sources.clip.source import ClipSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
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
    script = [ScriptedResponse(status=200)] if message is None else []
    with scripted_network(script) as network:
        assert ClipSource().validate_credentials(config, team_id=1) == (message is None, message)
    assert len(network.requests_log) == (1 if message is None else 0)
