from typing import Literal, cast
from urllib.parse import parse_qs, urlparse

import pytest

import responses
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.abnormal_security.source import (
    AbnormalSecuritySource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.abnormalsecurity import (
    AbnormalSecuritySourceConfig,
)


@pytest.mark.parametrize("region, host", [("us", "api.abnormalplatform.com"), ("eu", "eu.rest.abnormalsecurity.com")])
@pytest.mark.parametrize("status, expected", [(200, True), (401, False), (403, False)])
@responses.activate
def test_credentials(region: Literal["us", "eu"], host: str, status: int, expected: bool) -> None:
    responses.get(f"https://{host}/v1/threats", status=status, json={"threats": [], "nextPageNumber": 2})
    source = AbnormalSecuritySource()
    valid, message = source.validate_credentials(AbnormalSecuritySourceConfig(api_key="test-token", region=region), 1)
    assert valid is expected
    if expected:
        assert message is None
    else:
        assert message == source.get_non_retryable_errors()[f"{status} Client Error"]
    assert len(responses.calls) == 1
    request = responses.calls[0].request
    assert request.headers["Authorization"] == "Bearer test-token"
    query = parse_qs(urlparse(request.url).query)
    assert query["pageSize"] == ["1"]
    assert query["filter"][0].startswith("receivedTime lte ")


@pytest.mark.parametrize("field, value", [("region", "https://example.com"), ("api_version", "v2")])
@responses.activate
def test_invalid_region_or_version_makes_no_request(field: str, value: str) -> None:
    config = AbnormalSecuritySourceConfig(api_key="test-token")
    version = None
    if field == "region":
        config.region = cast(Literal["us", "eu"], value)
    else:
        version = value
    valid, message = AbnormalSecuritySource().validate_credentials(config, 1, api_version=version)
    assert not valid
    assert message
    assert len(responses.calls) == 0


@responses.activate
def test_validation_does_not_mask_unrelated_http_errors() -> None:
    responses.get("https://api.abnormalplatform.com/v1/threats", status=404, json={})
    with pytest.raises(HTTPError):
        AbnormalSecuritySource().validate_credentials(AbnormalSecuritySourceConfig(api_key="test-token"), 1)
