from typing import Any

import pytest

import requests_mock
from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.imperva import (
    ImpervaSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.imperva.settings import (
    AUTH_ERROR,
    PERMISSION_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.imperva.source import ImpervaSource

SITES_URL = "https://api.imperva.com/sites-mgmt/v3/sites"
STATS_URL = "https://my.imperva.com/api/stats/v1"
CONFIG = ImpervaSourceConfig(api_id="fake-api-id", api_key="fake-api-key", account_id="12345")


@pytest.mark.parametrize(
    ("status", "body", "schema_name", "expected"),
    [
        (200, {"data": [{"id": 10}]}, None, (True, None)),
        (200, {"res": 9411}, None, (False, AUTH_ERROR)),
        (200, {"res": 9413}, None, (False, PERMISSION_ERROR)),
        (200, {"res": 9415}, "sites", (False, PERMISSION_ERROR)),
        (200, {"res": 9415}, None, (True, None)),
        (401, {}, None, (False, AUTH_ERROR)),
        (403, {}, None, (False, PERMISSION_ERROR)),
        (403, {}, "sites", (False, PERMISSION_ERROR)),
    ],
)
def test_credential_probe_maps_auth_and_permissions(
    status: int, body: dict[str, Any], schema_name: str | None, expected: tuple[bool, str | None]
) -> None:
    with requests_mock.Mocker() as http:
        http.get(SITES_URL, status_code=status, json=body)
        assert ImpervaSource().validate_credentials(CONFIG, team_id=1, schema_name=schema_name) == expected
        assert http.call_count == 1
        assert http.last_request is not None
        assert http.last_request.qs["size"] == ["1"]


@pytest.mark.parametrize("name", ["visits_timeseries", "hits_timeseries", "bandwidth_timeseries"])
def test_schema_validation_probes_selected_statistic(name: str) -> None:
    with requests_mock.Mocker() as http:
        http.post(STATS_URL, json={"res": 0, name: []})
        assert ImpervaSource().validate_credentials(CONFIG, team_id=1, schema_name=name) == (True, None)
        assert http.call_count == 1
        assert http.last_request is not None
        assert http.last_request.qs["stats"] == [name]
        start = int(http.last_request.qs["start"][0])
        end = int(http.last_request.qs["end"][0])
        assert 0 <= end - start < 86_400_000


@pytest.mark.parametrize("account_id", ["", "example.com", "-1", "１２３", "123/456"])
def test_invalid_account_id_does_not_call_api(account_id: str) -> None:
    config = ImpervaSourceConfig(api_id="fake-api-id", api_key="fake-api-key", account_id=account_id)
    with requests_mock.Mocker() as http:
        valid, message = ImpervaSource().validate_credentials(config, team_id=1)
        assert valid is False
        assert message is not None and "numeric account ID" in message
        assert http.call_count == 0


def test_unknown_schema_does_not_call_api() -> None:
    with requests_mock.Mocker() as http:
        assert ImpervaSource().validate_credentials(CONFIG, team_id=1, schema_name="missing") == (
            False,
            "Unknown Imperva table: missing",
        )
        assert http.call_count == 0


def test_unexpected_http_error_is_not_an_authentication_failure() -> None:
    with requests_mock.Mocker() as http:
        http.get(SITES_URL, status_code=400, json={})
        with pytest.raises(HTTPError):
            ImpervaSource().validate_credentials(CONFIG, team_id=1)
