import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.guardian import (
    GuardianSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.guardian.source import GuardianSource


class TestGuardianSource:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [(200, (True, None))],
    )
    def test_validate_credentials(self, status: int, expected: tuple[bool, str | None]) -> None:
        with scripted_network([ScriptedResponse(status=status)]) as network:
            result = GuardianSource().validate_credentials(GuardianSourceConfig(api_key="test-key"), team_id=1)

        assert result == expected
        assert [request.path for request in network.requests_log] == ["/sections"]
