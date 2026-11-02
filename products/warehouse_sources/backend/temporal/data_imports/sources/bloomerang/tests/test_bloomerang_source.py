import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.bloomerang.bloomerang import BASE_URL
from products.warehouse_sources.backend.temporal.data_imports.sources.bloomerang.source import BloomerangSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bloomerang import (
    BloomerangSourceConfig,
)

_INCREMENTAL_ENDPOINTS = {"Constituents"}
_FULL_REFRESH_ENDPOINTS = {"Transactions", "Interactions", "Appeals", "Campaigns", "Funds"}


class TestBloomerangSource:
    def setup_method(self):
        self.source = BloomerangSource()
        self.team_id = 123
        self.config = BloomerangSourceConfig(api_key="key")

    @pytest.mark.parametrize(
        "answer, expected_valid, expected_message",
        [
            (ConnectionResetError("reset"), False, "Could not connect to Bloomerang with the provided API key"),
        ],
    )
    def test_validate_credentials(
        self, answer: ScriptedResponse | BaseException, expected_valid: bool, expected_message: str | None
    ) -> None:
        with scripted_network([answer]) as network:
            is_valid, error_message = self.source.validate_credentials(self.config, self.team_id)

        assert is_valid is expected_valid
        assert error_message == expected_message
        assert network.requests_log[0].headers["x-api-key"] == "key"

    def test_request_layer_stays_on_the_v2_wire(self):
        # No per-version dispatch: `/v2` is a fixed path segment, so a legacy v1 pin rides the same
        # wire as v2. Regressing this URL to v1 would move every v1-pinned source onto the vendor's
        # deprecated API.
        assert BASE_URL == "https://api.bloomerang.co/v2"
