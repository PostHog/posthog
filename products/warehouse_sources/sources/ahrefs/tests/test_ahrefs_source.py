import pytest

from products.warehouse_sources.sources.ahrefs._config import AhrefsSourceConfig
from products.warehouse_sources.sources.ahrefs.source import AhrefsSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, scripted_network


@pytest.mark.parametrize("project_id", ["", "0", "-1", "1.5", "https://example.com/123", "１２３", " 123 "])
def test_invalid_project_id_prevents_probe(project_id: str) -> None:
    with scripted_network([]) as network:
        valid, message = AhrefsSource().validate_credentials(
            AhrefsSourceConfig(api_key="test-key", project_id=project_id), 1
        )
    assert valid is False
    assert message == "Enter a positive Site Audit project ID from your Ahrefs project URL."
    assert network.requests_log == []


@pytest.mark.parametrize("project_id", ["123", "00123"])
def test_valid_project_id_reaches_probe(project_id: str) -> None:
    with scripted_network(
        [
            ScriptedResponse(json={"limits_and_usage": {"subscription": "Lite"}}),
            ScriptedResponse(json={"healthscores": [{"project_id": 123, "target_url": "example.com"}]}),
        ]
    ) as network:
        assert AhrefsSource().validate_credentials(
            AhrefsSourceConfig(api_key="test-key", project_id=project_id), 1
        ) == (
            True,
            None,
        )
    assert [request.path for request in network.requests_log] == [
        "/v3/subscription-info/limits-and-usage",
        "/v3/site-audit/projects",
    ]
    assert network.requests_log[1].param("project_id") == "123"
    assert all(request.headers["authorization"] == "Bearer test-key" for request in network.requests_log)
