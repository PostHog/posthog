import json

import pytest
from unittest.mock import MagicMock

from products.warehouse_sources.backend.temporal.data_imports.sources.azure_application_insights.source import (
    APP_ERROR,
    AUTH_ERROR,
    PERMISSION_ERROR,
    AzureApplicationInsightsSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.auth import (
    OAuth2AuthRequestError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.azureapplicationinsights import (
    AzureApplicationInsightsSourceConfig,
)


@pytest.mark.parametrize(
    ("status", "schema", "result"),
    [
        (200, None, (True, None)),
        (200, "requests", (True, None)),
        (401, None, (False, AUTH_ERROR)),
        (403, None, (True, None)),
        (403, "requests", (False, PERMISSION_ERROR)),
        (404, None, (False, APP_ERROR)),
    ],
)
def test_credential_probe_status(
    config: AzureApplicationInsightsSourceConfig,
    http_mock: MagicMock,
    status: int,
    schema: str | None,
    result: tuple[bool, str | None],
) -> None:
    http_mock.side_effect = [
        (200, {"access_token": "fake-token", "expires_in": 3600}),
        (status, {"tables": [{"name": "PrimaryResult", "columns": [], "rows": []}]}),
    ]
    assert AzureApplicationInsightsSource().validate_credentials(config, 1, schema_name=schema) == result
    assert http_mock.call_count == 2
    assert json.loads(http_mock.call_args.args[0].body) == {
        "query": "requests | take 1" if schema else "print 1",
        "timespan": "PT1M",
    }


@pytest.mark.parametrize(
    ("status", "error_code"),
    [
        (400, "invalid_client"),
        (401, "invalid_client"),
        (429, "temporarily_unavailable"),
        (503, "temporarily_unavailable"),
    ],
)
def test_token_error_mapping(
    config: AzureApplicationInsightsSourceConfig,
    http_mock: MagicMock,
    status: int,
    error_code: str,
) -> None:
    http_mock.return_value = (status, {"error": error_code})
    source = AzureApplicationInsightsSource()
    if status in (400, 401):
        assert source.validate_credentials(config, 1) == (False, AUTH_ERROR)
    else:
        with pytest.raises(OAuth2AuthRequestError) as error:
            source.validate_credentials(config, 1)
        assert not error.value.is_permanent
    assert http_mock.call_count == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tenant_id", "../common"),
        ("client_id", "invalid"),
        ("application_id", "id/query?query=evil"),
        ("client_secret", " "),
    ],
)
def test_invalid_config_makes_no_request(
    config: AzureApplicationInsightsSourceConfig,
    http_mock: MagicMock,
    field: str,
    value: str,
) -> None:
    setattr(config, field, value)
    valid, message = AzureApplicationInsightsSource().validate_credentials(config, 1)
    assert valid is False
    assert message and "Enter" in message
    http_mock.assert_not_called()


def test_unknown_schema_makes_no_request(config: AzureApplicationInsightsSourceConfig, http_mock: MagicMock) -> None:
    assert AzureApplicationInsightsSource().validate_credentials(config, 1, schema_name="requests | take 10") == (
        False,
        "Unknown Application Insights table.",
    )
    http_mock.assert_not_called()
