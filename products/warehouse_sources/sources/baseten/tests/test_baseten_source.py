import pytest

from products.warehouse_sources.sources.baseten._config import BasetenSourceConfig
from products.warehouse_sources.sources.baseten.source import BasetenSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, scripted_network


class TestBasetenCredentials:
    @pytest.mark.parametrize(("valid", "expected_ok"), [(True, True), (False, False)])
    def test_validate_credentials(self, valid: bool, expected_ok: bool) -> None:
        with scripted_network([ScriptedResponse(status=200 if valid else 403)]) as network:
            ok, error = BasetenSource().validate_credentials(BasetenSourceConfig(api_key="k"), team_id=1)

        assert ok is expected_ok
        assert (error is None) is expected_ok
        assert [request.path for request in network.requests_log] == ["/v1/users/me"]
