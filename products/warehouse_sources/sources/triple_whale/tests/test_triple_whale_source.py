import pytest
from time_machine import travel

from requests import HTTPError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.triplewhale import (
    TripleWhaleSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.triple_whale.source import TripleWhaleSource


@travel("2024-03-02T12:34:56+00:00", tick=False)
@pytest.mark.parametrize(
    ("schema_name", "status", "valid", "message"),
    [
        (None, 200, True, None),
        (None, 401, False, "rejected"),
        (None, 403, True, None),
        ("orders_with_journeys", 403, False, "Pixel Attribution"),
        ("summary_page", 403, False, "Summary Page"),
        ("orders_with_journeys", 200, True, None),
        ("summary_page", 200, True, None),
    ],
)
def test_credential_probe_accepts_limited_keys_and_checks_selected_table_scope(
    schema_name: str | None, status: int, valid: bool, message: str | None
) -> None:
    config = TripleWhaleSourceConfig(api_key="test-key", shop="example.myshopify.com", start_date="2024-01-01")
    with scripted_network([ScriptedResponse(status=status, json={})]) as network:
        result, error = TripleWhaleSource().validate_credentials(config, team_id=1, schema_name=schema_name)
    assert result is valid
    assert (error is None) if message is None else message in (error or "")
    request = network.requests_log[0]
    assert request.headers["x-api-key"] == "test-key"
    if schema_name is None:
        assert request.method == "GET"
        assert request.path == "/api/v2/users/api-keys/me"
    elif schema_name == "orders_with_journeys":
        assert request.method == "POST"
        assert request.json() == {
            "shop": "example.myshopify.com",
            "startDate": "2024-03-02T00:00:00.000+00:00",
            "endDate": "2024-03-02T12:34:56.000+00:00",
            "pageSize": 1,
            "page": 1,
            "excludeJourneyData": True,
        }
    else:
        assert request.json() == {
            "shopDomain": "example.myshopify.com",
            "period": {"start": "2024-03-02", "end": "2024-03-02"},
            "todayHour": 13,
        }


@travel("2024-03-02T12:34:56+00:00", tick=False)
@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("api_key", "", "API key"),
        ("api_key", "key\n", "API key"),
        ("api_key", "clé", "API key"),
        ("shop", "", "shop domain"),
        ("shop", "https://example.myshopify.com", "shop domain"),
        ("start_date", "not-a-date", "YYYY-MM-DD"),
        ("start_date", "20240101", "YYYY-MM-DD"),
        ("start_date", "2024-03-03", "future"),
    ],
)
def test_invalid_input_does_not_send_credentials(field: str, value: str, message: str) -> None:
    values = {"api_key": "test-key", "shop": "example.myshopify.com", "start_date": "2024-01-01", field: value}
    with scripted_network([]) as network:
        valid, error = TripleWhaleSource().validate_credentials(TripleWhaleSourceConfig(**values), team_id=1)
    assert not valid
    assert message in (error or "")
    assert network.requests_log == []


@travel("2024-03-02T12:34:56+00:00", tick=False)
def test_permission_probes_report_scopes_without_blocking_other_tables() -> None:
    config = TripleWhaleSourceConfig(api_key="test-key", shop="example.myshopify.com", start_date="2024-01-01")
    with scripted_network([ScriptedResponse(status=403, json={}), ScriptedResponse(json={})]):
        permissions = TripleWhaleSource().get_endpoint_permissions(config, 1, ["orders_with_journeys", "summary_page"])
    assert "Pixel Attribution" in (permissions["orders_with_journeys"] or "")
    assert permissions["summary_page"] is None


@travel("2024-03-02T12:34:56+00:00", tick=False)
def test_bad_request_is_not_reported_as_missing_scope() -> None:
    config = TripleWhaleSourceConfig(api_key="test-key", shop="example.myshopify.com", start_date="2024-01-01")
    with scripted_network([ScriptedResponse(status=400, json={"error": "bad_request"})]):
        with pytest.raises(HTTPError):
            TripleWhaleSource().get_endpoint_permissions(config, 1, ["summary_page"])
