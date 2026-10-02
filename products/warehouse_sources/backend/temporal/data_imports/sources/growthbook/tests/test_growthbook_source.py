from urllib.parse import parse_qs, urlsplit

import pytest
from unittest.mock import MagicMock

import responses

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.rest_client import (
    RESTClientRetryableError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.growthbook import (
    GrowthBookSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.growthbook.source import GrowthBookSource


@pytest.mark.parametrize(
    ("status", "schema_name", "expected", "message"),
    [
        (200, None, True, None),
        (401, None, False, "invalid or expired"),
        (403, None, True, None),
        (403, "projects", False, "read access"),
        (200, "projects", True, None),
    ],
)
def test_credential_probe_status_mapping(
    config: GrowthBookSourceConfig,
    http: responses.RequestsMock,
    status: int,
    schema_name: str | None,
    expected: bool,
    message: str | None,
) -> None:
    path = "v1/projects" if schema_name else "v2/features"
    selector = schema_name or "features"
    http.add(
        responses.GET,
        f"https://api.growthbook.io/api/{path}",
        status=status,
        json={selector: [], "nextOffset": 100, "hasMore": True},
    )
    valid, error = GrowthBookSource().validate_credentials(config, 123, schema_name)
    assert valid is expected
    if message is not None:
        assert error is not None and message in error
    else:
        assert error is None
    assert len(http.calls) == 1
    assert parse_qs(urlsplit(http.calls[0].request.url).query)["limit"] == ["1"]
    assert http.calls[0].request.headers["Authorization"] == "Bearer secret_test_growthbook"


@pytest.mark.parametrize("status", [429, 503])
def test_transient_probe_failure_is_not_bad_credentials(
    config: GrowthBookSourceConfig,
    http: responses.RequestsMock,
    status: int,
) -> None:
    http.add(responses.GET, "https://api.growthbook.io/api/v2/features", status=status, json={"message": "Try again"})
    with pytest.raises(RESTClientRetryableError):
        GrowthBookSource().validate_credentials(config, 123)


@pytest.mark.parametrize(
    "base_url",
    [
        "http://flags.example.com/api",
        "https://user:pass@flags.example.com/api",
        "https://flags.example.com/api?key=value",
        "https://flags.example.com/api#fragment",
        "https://",
        "https://flags.example.com:invalid/api",
        "https://flags.example.com\\@127.0.0.1/api",
        "https://flags.example.com%5c/api",
    ],
)
def test_malformed_urls_fail_before_sending_credentials(base_url: str, http: responses.RequestsMock) -> None:
    config = GrowthBookSourceConfig.from_dict({"api_key": "secret_test", "base_url": base_url})
    valid, message = GrowthBookSource().validate_credentials(config, 123)
    assert not valid
    assert message and "HTTPS" in message
    assert not http.calls


def test_private_hosts_rejected_for_validation_and_sync(
    config: GrowthBookSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
    http: responses.RequestsMock,
    safe_host: MagicMock,
) -> None:
    safe_host.return_value = (False, "private IP")
    valid, message = GrowthBookSource().validate_credentials(config, 123)
    assert not valid
    assert message and "publicly reachable" in message
    with pytest.raises(ValueError, match="publicly reachable"):
        GrowthBookSource().source_for_pipeline(config, manager, inputs)
    assert not http.calls


def test_unknown_table_rejected_without_http(
    config: GrowthBookSourceConfig,
    inputs: SourceInputs,
    manager: MagicMock,
    http: responses.RequestsMock,
) -> None:
    inputs.schema_name = "unknown"
    valid, message = GrowthBookSource().validate_credentials(config, 123, inputs.schema_name)
    assert not valid
    assert message and "Unknown GrowthBook table" in message
    with pytest.raises(UnknownResourceError):
        GrowthBookSource().source_for_pipeline(config, manager, inputs)
    assert not http.calls


@pytest.mark.parametrize(
    ("base_url", "expected_url"),
    [
        ("  ", "https://api.growthbook.io/api/v2/features"),
        (" https://flags.example.com/custom/api/ ", "https://flags.example.com/custom/api/v2/features"),
    ],
)
def test_base_url_normalization(base_url: str, expected_url: str, http: responses.RequestsMock) -> None:
    config = GrowthBookSourceConfig.from_dict({"api_key": "secret_test", "base_url": base_url})
    http.add(responses.GET, expected_url, json={"features": []})
    assert GrowthBookSource().validate_credentials(config, 123) == (True, None)
    assert len(http.calls) == 1
