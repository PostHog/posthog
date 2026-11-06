import pytest

from products.warehouse_sources.sources.guardian._config import GuardianSourceConfig
from products.warehouse_sources.sources.guardian.source import GuardianSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, scripted_network


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
