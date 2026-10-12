from http import HTTPStatus
from urllib.parse import parse_qs, urlparse

import pytest
from unittest.mock import patch

from requests import Response
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.buildium.settings import (
    AUTH_ERROR,
    PERMISSION_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buildium.source import BuildiumSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.buildium import (
    BuildiumSourceConfig,
)


@pytest.mark.parametrize("schema_name", [None, "bills"])
@pytest.mark.parametrize(
    ("status", "expected"),
    [(200, (True, None)), (401, (False, AUTH_ERROR)), (403, (False, PERMISSION_ERROR)), (500, None)],
)
def test_validate_credentials(schema_name: str | None, status: int, expected: tuple[bool, str | None] | None) -> None:
    response = Response()
    response.status_code = status
    response.reason = HTTPStatus(status).phrase
    config = BuildiumSourceConfig(client_id="example-client", client_secret="example-secret")
    with patch("requests.Session.send", return_value=response) as send:
        if expected is None:
            with pytest.raises(HTTPError):
                BuildiumSource().validate_credentials(config, 1, schema_name)
        else:
            assert BuildiumSource().validate_credentials(config, 1, schema_name) == expected
    send.assert_called_once()
    request = send.call_args.args[0]
    assert urlparse(request.url).path == ("/v1/bills" if schema_name else "/v1/rentals")
    assert parse_qs(urlparse(request.url).query) == {"limit": ["1"]}
    assert request.headers["x-buildium-client-id"] == config.client_id
    assert request.headers["x-buildium-client-secret"] == config.client_secret
