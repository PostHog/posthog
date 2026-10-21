import pytest

from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    route,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lexwareoffice import (
    LexwareOfficeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lexware_office.source import LexwareOfficeSource


@pytest.mark.parametrize(
    "status,schema,valid,message",
    [
        (200, None, True, None),
        (403, None, True, None),
        (403, "contacts", False, "read access"),
    ],
)
def test_credential_status_mapping(status: int, schema: str | None, valid: bool, message: str | None) -> None:
    source = LexwareOfficeSource()
    with scripted_network([ScriptedResponse(status=status, json={"content": []})]) as network:
        result, error = source.validate_credentials(LexwareOfficeSourceConfig(api_key="fake-key"), 1, schema)
    assert result is valid
    if message:
        assert error is not None and message in error
    else:
        assert error is None
    assert len(network.requests_log) == 1
    assert network.requests_log[0].param("size") == "1"
    assert network.requests_log[0].headers["authorization"] == "Bearer fake-key"


@pytest.mark.parametrize("status", [401, 403, 400])
def test_detail_permission_probe_and_error_classification(status: int) -> None:
    source = LexwareOfficeSource()
    with scripted_network(
        route(
            {
                "/v1/voucherlist": [
                    ScriptedResponse(json={"content": [{"id": "invoice-a", "createdDate": "2026-01-01T00:00:00Z"}]})
                ],
                "/v1/invoices/invoice-a": [ScriptedResponse(status=status, json={})],
            }
        )
    ) as network:
        config = LexwareOfficeSourceConfig(api_key="fake-key")
        if status == 400:
            with pytest.raises(HTTPError):
                source.validate_credentials(config, 1, "invoices")
        else:
            valid, message = source.validate_credentials(config, 1, "invoices")
            assert not valid
            assert message
            assert message in source.get_non_retryable_errors().values()
    assert len(network.requests_log) == 2
    assert network.requests_log[0].param("size") == "1"
    assert network.requests_log[1].query == {}


def test_unknown_schema_fails_before_network() -> None:
    with scripted_network([]) as network:
        with pytest.raises(UnknownResourceError, match="not available on this worker"):
            LexwareOfficeSource().validate_credentials(LexwareOfficeSourceConfig(api_key="fake-key"), 1, "unknown")
    assert network.requests_log == []
