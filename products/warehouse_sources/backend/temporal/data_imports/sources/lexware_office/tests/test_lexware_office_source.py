import pytest
from unittest.mock import MagicMock

import requests_mock
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import UnknownResourceError
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.lexwareoffice import (
    LexwareOfficeSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.lexware_office.source import LexwareOfficeSource

BASE = "https://api.lexware.io/v1"


@pytest.mark.parametrize(
    "status,schema,valid,message",
    [
        (200, None, True, None),
        (401, None, False, "invalid or expired"),
        (403, None, True, None),
        (403, "contacts", False, "read access"),
    ],
)
def test_credential_status_mapping(status: int, schema: str | None, valid: bool, message: str | None) -> None:
    source = LexwareOfficeSource()
    with requests_mock.Mocker() as http:
        http.get(f"{BASE}/contacts", status_code=status, json={"content": []})
        result, error = source.validate_credentials(LexwareOfficeSourceConfig(api_key="fake-key"), 1, schema)
        assert result is valid
        if message:
            assert error is not None and message in error
        else:
            assert error is None
        assert http.last_request is not None
        assert http.last_request.qs == {"size": ["1"]}
        assert http.last_request.headers["Authorization"] == "Bearer fake-key"


@pytest.mark.parametrize("status", [401, 403, 400])
def test_detail_permission_probe_and_error_classification(status: int) -> None:
    source = LexwareOfficeSource()
    with requests_mock.Mocker() as http:
        http.get(f"{BASE}/voucherlist", json={"content": [{"id": "invoice-a", "createdDate": "2026-01-01T00:00:00Z"}]})
        http.get(f"{BASE}/invoices/invoice-a", status_code=status, json={})
        config = LexwareOfficeSourceConfig(api_key="fake-key")
        if status == 400:
            with pytest.raises(HTTPError):
                source.validate_credentials(config, 1, "invoices")
        else:
            valid, message = source.validate_credentials(config, 1, "invoices")
            assert not valid
            assert message
            assert message in source.get_non_retryable_errors().values()
        assert len(http.request_history) == 2
        assert http.request_history[0].qs["size"] == ["1"]
        assert http.request_history[1].qs == {}


def test_unknown_schema_fails_before_network() -> None:
    with requests_mock.Mocker() as http, pytest.raises(UnknownResourceError, match="not available on this worker"):
        LexwareOfficeSource().validate_credentials(LexwareOfficeSourceConfig(api_key="fake-key"), 1, "unknown")
    assert not http.called


def test_pipeline_rejects_unknown_schema() -> None:
    inputs = MagicMock(schema_name="unknown", team_id=1, job_id="job")
    with pytest.raises(UnknownResourceError):
        LexwareOfficeSource().source_for_pipeline(LexwareOfficeSourceConfig(api_key="fake-key"), MagicMock(), inputs)
