from base64 import b64encode

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.outbrain import (
    OutbrainSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.outbrain.source import OutbrainSource


class TestOutbrainSource:
    def setup_method(self):
        self.source = OutbrainSource()
        self.team_id = 123
        self.config = OutbrainSourceConfig(username="u@x.com", password="pw")

    @pytest.mark.parametrize(
        "mock_return, expected_valid",
        [
            (True, True),
            (False, False),
        ],
    )
    def test_validate_credentials(self, mock_return: bool, expected_valid: bool) -> None:
        with mock.patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.outbrain.outbrain.cache"
        ) as mock_cache:
            mock_cache.get.return_value = None
            response = ScriptedResponse(json={"OB-TOKEN-V1": "tok"} if mock_return else {"message": "nope"})
            with scripted_network([response]) as network:
                is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        if not expected_valid:
            assert error_message == "Invalid Outbrain credentials"
        assert [request.path for request in network.requests_log] == ["/amplify/v0.1/login"]
        credentials = b64encode(b"u@x.com:pw").decode()
        assert network.requests_log[0].headers["authorization"] == f"Basic {credentials}"
