from typing import Any

import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import (
    DATABASE_HOST_NOT_ALLOWED_ERROR,
    HostNotAllowedError,
    HostResolution,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
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
            (ScriptedResponse(json={"keys": [], "total_count": 0, "current_page": 1, "total_pages": 0}), True, None),
        ],
    )
    def test_maps_the_key_probe(self, answer: Any, expected_valid: bool, expected_fragment: str | None) -> None:
        config = LiteLLMSourceConfig(base_url="https://proxy.example.com", api_key="sk-master")
        with scripted_network(always(answer)) as network:
            is_valid, message = LiteLLMSource().validate_credentials(config, team_id=1)

        assert is_valid is expected_valid
        assert (message is None) if expected_fragment is None else (expected_fragment in (message or ""))
        assert {request.path for request in network.requests_log} == {"/key/list"}

    def test_plain_http_url_fails_before_any_request(self) -> None:
        config = LiteLLMSourceConfig(base_url="http://proxy.example.com", api_key="sk-master")
        with scripted_network([]) as network:
            is_valid, message = LiteLLMSource().validate_credentials(config, team_id=1)

        assert is_valid is False
        assert message is not None and "https://" in message
        assert network.requests_log == []

    def test_sync_refuses_a_host_that_now_resolves_privately_with_the_permanent_host_error(self) -> None:
        config = LiteLLMSourceConfig(base_url="https://proxy.example.com", api_key="sk-master")
        rejected = HostResolution(connect_host=None, error="Hosts with internal IP addresses are not allowed")
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.litellm.source.resolve_safe_host",
            return_value=rejected,
        ):
            result = SourceDriver(LiteLLMSource(), config).run("keys", [])

        assert isinstance(result.raised, HostNotAllowedError)
        assert str(result.raised).startswith(DATABASE_HOST_NOT_ALLOWED_ERROR)
        assert result.requests == []
