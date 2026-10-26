import base64

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ownerrez import (
    OwnerrezSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ownerrez.source import OwnerrezSource


class TestOwnerrezSource:
    def setup_method(self) -> None:
        self.source = OwnerrezSource()
        self.team_id = 123
        self.config = OwnerrezSourceConfig(email="host@example.com", api_key="pt_key")

    def test_new_sources_default_to_v2(self) -> None:
        assert self.source.supported_versions == ("v1", "v2")
        assert self.source.default_version == "v2"

    @pytest.mark.parametrize(
        "status_code, expected_valid, expected_message",
        [
            (
                None,
                False,
                "Could not connect to OwnerRez with the provided account email and personal access token",
            ),
        ],
    )
    def test_validate_credentials(
        self, status_code: int | None, expected_valid: bool, expected_message: str | None
    ) -> None:
        script = (
            always(ConnectionResetError("reset")) if status_code is None else [ScriptedResponse(status=status_code)]
        )
        with scripted_network(script) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        assert network.requests_log[0].path == "/v2/properties"
        encoded = base64.b64encode(b"host@example.com:pt_key").decode()
        assert network.requests_log[0].headers["authorization"] == f"Basic {encoded}"
