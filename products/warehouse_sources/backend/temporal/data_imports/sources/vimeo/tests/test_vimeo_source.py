from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import patch

from requests import HTTPError, Response

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.vimeo import VimeoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.vimeo.settings import AUTH_ERROR, PERMISSION_ERROR
from products.warehouse_sources.backend.temporal.data_imports.sources.vimeo.source import VimeoSource


@pytest.mark.parametrize(
    "status,schema,expected",
    [
        (200, None, (True, None)),
        (401, None, (False, AUTH_ERROR)),
        (403, None, (True, None)),
        (200, "folders", (True, None)),
        (401, "folders", (False, AUTH_ERROR)),
        (403, "folders", (False, PERMISSION_ERROR)),
    ],
)
def test_credentials_probe(status: int, schema: str | None, expected: tuple[bool, str | None]) -> None:
    response = Response()
    response.status_code = status
    with patch("requests.Session.send", return_value=response) as send:
        assert (
            VimeoSource().validate_credentials(VimeoSourceConfig(access_token="test-token"), 1, schema_name=schema)
            == expected
        )
    send.assert_called_once()
    request = send.call_args.args[0]
    url = urlsplit(request.url)
    assert url.path == ("/me/projects" if schema else "/me")
    assert parse_qs(url.query) == ({"per_page": ["1"]} if schema else {"fields": ["uri"]})
    assert request.headers["Authorization"] == "Bearer test-token"
    assert request.headers["Accept"] == "application/vnd.vimeo.*+json;version=3.4"


def test_service_error_is_not_reported_as_invalid_credentials() -> None:
    response = Response()
    response.status_code = 503
    with patch("requests.Session.send", return_value=response), pytest.raises(HTTPError):
        VimeoSource().validate_credentials(VimeoSourceConfig(access_token="test-token"), 1)
