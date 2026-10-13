from urllib.parse import parse_qs, urlsplit

import pytest

import responses
from requests.exceptions import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.productive import (
    ProductiveSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.productive.source import ProductiveSource


@pytest.mark.parametrize(
    ("status", "schema_name", "valid", "message"),
    [
        (200, None, True, None),
        (200, "time_entries", True, None),
        (401, None, False, "invalid or expired"),
        (403, None, True, None),
        (403, "invoices", False, "permissions"),
    ],
)
@responses.activate
def test_credential_probe_distinguishes_bad_tokens_from_missing_table_access(
    config: ProductiveSourceConfig, status: int, schema_name: str | None, valid: bool, message: str | None
) -> None:
    responses.get(
        f"https://api.productive.io/api/v2/{schema_name or 'projects'}",
        status=status,
        json={"data": [], "meta": {"total_pages": 20}} if status == 200 else {"errors": [{"detail": "Access denied"}]},
    )
    success, error = ProductiveSource().validate_credentials(config, 1, schema_name)
    assert success is valid
    if message is None:
        assert error is None
    else:
        assert error is not None and message in error
    assert len(responses.calls) == 1
    assert parse_qs(urlsplit(responses.calls[0].request.url).query) == {"page[number]": ["1"], "page[size]": ["1"]}


@responses.activate
def test_unexpected_api_failure_is_not_reported_as_bad_credentials(config: ProductiveSourceConfig) -> None:
    responses.get("https://api.productive.io/api/v2/projects", status=400, json={"errors": []})
    with pytest.raises(HTTPError):
        ProductiveSource().validate_credentials(config, 1)


@pytest.mark.parametrize("organization_id", ["", "0", "-1", "abc", "123\r\nInjected: header", "１２３"])
@responses.activate
def test_invalid_organization_id_is_rejected_without_http(organization_id: str) -> None:
    config = ProductiveSourceConfig(api_token="test-token", organization_id=organization_id)
    valid, error = ProductiveSource().validate_credentials(config, 1)
    assert not valid
    assert error is not None and "numeric organization ID" in error
    assert len(responses.calls) == 0


@responses.activate
def test_unknown_table_is_rejected_before_probing(config: ProductiveSourceConfig) -> None:
    valid, error = ProductiveSource().validate_credentials(config, 1, "unknown")
    assert not valid
    assert error is not None and "Unknown Productive table" in error
    assert len(responses.calls) == 0
