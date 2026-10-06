from typing import Any, cast

import pytest
from unittest.mock import patch

from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.frontegg.settings import (
    AUTH_ERROR,
    PERMISSION_ERROR,
    REGION_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.frontegg.source import FronteggSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.frontegg import (
    FronteggSourceConfig,
)


class TestFronteggSource:
    @pytest.mark.parametrize("body", [b"{}", b"[]", b"null", b"not json", b'{"token": ""}'])
    def test_invalid_token_response(self, body: bytes) -> None:
        config = FronteggSourceConfig(client_id="example-client", api_key="fake-key", region="EU")
        response = Response()
        response.status_code = 200
        response._content = body
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.frontegg.frontegg.make_tracked_session"
        ) as factory:
            factory.return_value.__enter__.return_value.post.return_value = response
            assert FronteggSource().validate_credentials(config, 1) == (False, AUTH_ERROR)

    @pytest.mark.parametrize(
        "status,expected",
        [(200, None), (400, AUTH_ERROR), (401, AUTH_ERROR), (403, PERMISSION_ERROR), (429, "raise"), (500, "raise")],
    )
    def test_validate_credentials(self, status: int, expected: str | None) -> None:
        config = FronteggSourceConfig(client_id="example-client", api_key="fake-key", region="EU")
        source = FronteggSource()
        response = Response()
        response.status_code = status
        response.url = "https://api.frontegg.com/auth/vendor"
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.frontegg.source.FronteggAuth._obtain_token"
        ) as obtain:
            if status != 200:
                obtain.side_effect = HTTPError(f"{status} Client Error", response=response)
            if expected == "raise":
                with pytest.raises(HTTPError):
                    source.validate_credentials(config, 1)
            else:
                assert source.validate_credentials(config, 1) == (status == 200, expected)
            obtain.assert_called_once_with(timeout=(5, 10))
        mappings = source.get_non_retryable_errors()
        assert any(pattern in f"{status} Client Error" for pattern in mappings) == (status in (400, 401, 403))

    def test_invalid_region_does_not_send_credentials(self) -> None:
        config = FronteggSourceConfig(client_id="example-client", api_key="fake-key", region=cast(Any, "invalid"))
        with patch(
            "products.warehouse_sources.backend.temporal.data_imports.sources.frontegg.source.FronteggAuth"
        ) as auth:
            assert FronteggSource().validate_credentials(config, 1) == (False, REGION_ERROR)
        auth.assert_not_called()
