from typing import Any, cast

import pytest

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.frontegg.settings import AUTH_ERROR, REGION_ERROR
from products.warehouse_sources.backend.temporal.data_imports.sources.frontegg.source import FronteggSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.frontegg import (
    FronteggSourceConfig,
)


class TestFronteggSource:
    @pytest.mark.parametrize("body", [b"{}", b"[]", b"null", b"not json", b'{"token": ""}'])
    def test_invalid_token_response(self, body: bytes) -> None:
        config = FronteggSourceConfig(client_id="example-client", api_key="fake-key", region="EU")
        with scripted_network([ScriptedResponse(body=body)]) as network:
            assert FronteggSource().validate_credentials(config, 1) == (False, AUTH_ERROR)
        assert [request.path for request in network.requests_log] == ["/auth/vendor"]

    @pytest.mark.parametrize(
        "status,expected",
        [
            (400, AUTH_ERROR),
            (429, "Couldn't reach Frontegg to check your credentials. Try again in a few minutes."),
            (500, "Couldn't reach Frontegg to check your credentials. Try again in a few minutes."),
        ],
    )
    def test_validate_credentials(self, status: int, expected: str | None) -> None:
        config = FronteggSourceConfig(client_id="example-client", api_key="fake-key", region="EU")
        source = FronteggSource()
        answer = (
            ScriptedResponse(json={"token": "fake-token", "expiresIn": 3600})
            if status == 200
            else ScriptedResponse(status=status, json={})
        )
        with scripted_network(always(answer)) as network:
            assert source.validate_credentials(config, 1) == (status == 200, expected)
        assert {request.path for request in network.requests_log} == {"/auth/vendor"}
        mappings = source.get_non_retryable_errors()
        assert any(pattern in f"{status} Client Error" for pattern in mappings) == (status in (400, 401, 403))

    def test_invalid_region_does_not_send_credentials(self) -> None:
        config = FronteggSourceConfig(client_id="example-client", api_key="fake-key", region=cast(Any, "invalid"))
        with scripted_network([]) as network:
            assert FronteggSource().validate_credentials(config, 1) == (False, REGION_ERROR)
        assert network.requests_log == []
