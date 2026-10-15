from typing import Any

import pytest

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.litellm import (
    LiteLLMSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.litellm.source import LiteLLMSource


class TestLiteLLMValidateCredentials:
    @pytest.mark.parametrize(
        ("answer", "expected_valid", "expected_fragment"),
        [
            (ScriptedResponse(json={"key": "sk-...abcd", "info": {}}), True, None),
            (
                ScriptedResponse(status=401, json={"error": {"message": "Authentication Error"}}),
                False,
                "rejected the key",
            ),
            (requests.ConnectionError("refused"), False, "Could not reach"),
        ],
    )
    def test_maps_the_key_probe(self, answer: Any, expected_valid: bool, expected_fragment: str | None) -> None:
        config = LiteLLMSourceConfig(base_url="https://proxy.example.com", api_key="sk-master")
        with scripted_network(always(answer)) as network:
            is_valid, message = LiteLLMSource().validate_credentials(config, team_id=1)

        assert is_valid is expected_valid
        assert (message is None) if expected_fragment is None else (expected_fragment in (message or ""))
        assert {request.path for request in network.requests_log} == {"/key/info"}

    def test_plain_http_url_fails_before_any_request(self) -> None:
        config = LiteLLMSourceConfig(base_url="http://proxy.example.com", api_key="sk-master")
        with scripted_network([]) as network:
            is_valid, message = LiteLLMSource().validate_credentials(config, team_id=1)

        assert is_valid is False
        assert message is not None and "https://" in message
        assert network.requests_log == []
