import json
from base64 import b64encode
from typing import Any, Literal, cast
from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import patch

from requests import Response
from requests.exceptions import ConnectionError, HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    DriveResult,
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sodacloud import (
    SodaCloudSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.soda_cloud.settings import (
    AUTH_ERROR,
    PERMISSION_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.soda_cloud.soda_cloud import SodaCloudResumeConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.soda_cloud.source import SodaCloudSource


@pytest.fixture
def config() -> SodaCloudSourceConfig:
    return SodaCloudSourceConfig(api_key_id="fake-key-id", api_key_secret="fake-key-secret", region="eu")


def response(rows: list[dict[str, object]], total_pages: int = 1, status: int = 200) -> Response:
    result = Response()
    result.status_code = status
    result.reason = {401: "Unauthorized", 403: "Forbidden"}.get(status, "Test response")
    result.url = "https://cloud.soda.io/api/v1/datasets"
    result.headers["Content-Type"] = "application/json"
    result._content = json.dumps({"content": rows, "totalPages": total_pages}).encode()
    return result


def page(rows: list[dict[str, object]], total_pages: int = 1, status: int = 200) -> ScriptedResponse:
    return ScriptedResponse(status=status, json={"content": rows, "totalPages": total_pages})


def run(
    config: SodaCloudSourceConfig, script: list[ScriptedResponse], schema_name: str = "datasets", **inputs: Any
) -> DriveResult:
    return SourceDriver(SodaCloudSource(), config).run(schema_name, script, **inputs)


@pytest.mark.parametrize("region,host", [("eu", "cloud.soda.io"), ("us", "cloud.us.soda.io")])
@pytest.mark.parametrize("endpoint", ["datasets", "checks", "incidents"])
def test_paginated_requests_and_checkpoint(
    config: SodaCloudSourceConfig,
    region: Literal["eu", "us"],
    host: str,
    endpoint: str,
) -> None:
    config.region = region
    rows: list[dict[str, object]] = [{"id": "row-one"}, {"id": "row-two"}]
    result = run(config, [page(rows[:1], 2), page(rows[1:], 2)], schema_name=endpoint)

    assert result.raised is None
    assert result.items == [rows[:1], rows[1:]]
    assert len(result.requests) == 2
    expected_auth = "Basic " + b64encode(b"fake-key-id:fake-key-secret").decode()
    for page_number, request in enumerate(result.requests):
        assert request.method == "GET"
        assert urlsplit(request.url).netloc == host
        assert request.path == f"/api/v1/{endpoint}"
        assert dict(request.query) == {"size": ("100",), "page": (str(page_number),)}
        assert request.headers["authorization"] == expected_auth
    assert result.saved_states == [SodaCloudResumeConfig(page=1)]


@pytest.mark.parametrize("original_from", [None, "2026-01-01T00:00:00Z"])
def test_resume_retains_original_filter(config: SodaCloudSourceConfig, original_from: str | None) -> None:
    result = run(
        config,
        [page([{"id": "row-five"}], 5)],
        should_use_incremental_field=True,
        db_incremental_field_last_value="2026-01-10T00:00:00Z",
        resume_state=SodaCloudResumeConfig(page=4, from_datetime=original_from),
    )
    assert result.items == [[{"id": "row-five"}]]
    assert len(result.requests) == 1
    request = result.requests[0]
    assert request.param("page") == "4"
    assert request.param("from") == original_from
    assert result.saved_states == []


@pytest.mark.parametrize("status,message", [(401, AUTH_ERROR), (403, PERMISSION_ERROR)])
def test_sync_error_matches_non_retryable_message(config: SodaCloudSourceConfig, status: int, message: str) -> None:
    source = SodaCloudSource()
    result = run(config, [page([], status=status)])
    assert isinstance(result.raised, HTTPError)
    assert len(result.requests) == 1
    assert message in [value for key, value in source.get_non_retryable_errors().items() if key in str(result.raised)]


@pytest.mark.parametrize(
    "status,expected",
    [
        (200, (True, None)),
        (401, (False, AUTH_ERROR)),
        (403, (False, PERMISSION_ERROR)),
        (429, (False, "Could not validate the Soda Cloud API keys. Try again later.")),
        (500, (False, "Could not validate the Soda Cloud API keys. Try again later.")),
        (302, (False, "Could not validate the Soda Cloud API keys. Try again later.")),
    ],
)
def test_credential_probe(config: SodaCloudSourceConfig, status: int, expected: tuple[bool, str | None]) -> None:
    config.region = "us"
    with patch("requests.sessions.Session.send", return_value=response([], status=status)) as send:
        assert SodaCloudSource().validate_credentials(config, team_id=1) == expected
    send.assert_called_once()
    request = send.call_args.args[0]
    assert urlsplit(request.url).netloc == "cloud.us.soda.io"
    assert parse_qs(urlsplit(request.url).query) == {"page": ["0"], "size": ["10"]}
    assert request.headers["Authorization"] == "Basic " + b64encode(b"fake-key-id:fake-key-secret").decode()
    assert send.call_args.kwargs["timeout"] == (10, 30)
    assert send.call_args.kwargs["allow_redirects"] is False


def test_connection_error_does_not_expose_credentials(config: SodaCloudSourceConfig) -> None:
    with patch("requests.sessions.Session.send", side_effect=ConnectionError(config.api_key_secret)):
        valid, message = SodaCloudSource().validate_credentials(config, team_id=1)
    assert not valid
    assert message == "Could not connect to Soda Cloud. Check the region and try again."


@pytest.mark.parametrize("region", ["", "https://example.com", "EU", "localhost"])
def test_invalid_region_never_sends_credentials(config: SodaCloudSourceConfig, region: str) -> None:
    config.region = cast(Literal["eu", "us"], region)
    with scripted_network([]) as network:
        valid, message = SodaCloudSource().validate_credentials(config, team_id=1)
        assert not valid
        assert message == "Select Europe or United States as the Soda Cloud region."
        result = run(config, [])
    assert isinstance(result.raised, ValueError)
    assert "Select Europe" in str(result.raised)
    assert network.requests_log == []
    assert result.requests == []


def test_invalid_endpoint_never_makes_request(config: SodaCloudSourceConfig) -> None:
    result = run(config, [], schema_name="../secrets")
    assert isinstance(result.raised, ValueError)
    assert "Unsupported Soda Cloud table" in str(result.raised)
    assert result.requests == []
