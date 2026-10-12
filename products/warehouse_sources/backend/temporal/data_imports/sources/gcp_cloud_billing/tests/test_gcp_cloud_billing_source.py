import pytest

from google.auth.exceptions import TransportError

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gcp_cloud_billing.source import (
    GcpCloudBillingSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gcpcloudbilling import (
    GcpCloudBillingSourceConfig,
)


@pytest.mark.parametrize(
    ("status", "schema", "valid"),
    [(200, None, True), (401, None, False), (403, None, True), (401, "services", False), (403, "services", False)],
)
def test_credentials_distinguish_invalid_key_from_missing_scope(
    service_account_json: str, status: int, schema: str | None, valid: bool
) -> None:
    with scripted_network(
        [
            ScriptedResponse(json={"access_token": "fake-token", "expires_in": 3600}),
            ScriptedResponse(
                status=status, json={"error": {"code": status, "status": "PERMISSION_DENIED"}} if status != 200 else {}
            ),
        ]
    ):
        success, message = GcpCloudBillingSource().validate_credentials(
            GcpCloudBillingSourceConfig(service_account_json=service_account_json), team_id=1, schema_name=schema
        )
    assert success is valid
    assert (message is None) is valid


@pytest.mark.parametrize(
    "key",
    [
        "not-json",
        "[]",
        '{"type":"authorized_user"}',
        '{"type":"service_account"}',
        '{"type":"service_account","client_email":"fake@example.com","private_key":123}',
    ],
)
def test_malformed_keys_fail_without_network(key: str) -> None:
    with scripted_network([]):
        valid, message = GcpCloudBillingSource().validate_credentials(
            GcpCloudBillingSourceConfig(service_account_json=key), team_id=1
        )
    assert valid is False
    assert message == "Invalid GCP service account key. Enter a valid JSON key."


@pytest.mark.parametrize("empty_parents", [False, True])
def test_child_permission_probe_uses_account_and_budget_host(service_account_json: str, empty_parents: bool) -> None:
    script = [
        ScriptedResponse(json={"access_token": "fake-token", "expires_in": 3600}),
        ScriptedResponse(json={} if empty_parents else {"billingAccounts": [{"name": "billingAccounts/fake-account"}]}),
    ]
    if not empty_parents:
        script.append(ScriptedResponse(status=403, json={"error": {"code": 403, "status": "PERMISSION_DENIED"}}))
    with scripted_network(script) as network:
        valid, _ = GcpCloudBillingSource().validate_credentials(
            GcpCloudBillingSourceConfig(service_account_json=service_account_json), team_id=1, schema_name="budgets"
        )
    assert valid is empty_parents
    if not empty_parents:
        assert (
            network.requests_log[-1].url
            == "https://billingbudgets.googleapis.com/v1/billingAccounts/fake-account/budgets?pageSize=1"
        )


def test_revoked_key_returns_safe_message(service_account_json: str) -> None:
    with scripted_network(
        [ScriptedResponse(status=400, json={"error": "invalid_grant", "error_description": "Invalid JWT Signature."})]
    ):
        valid, message = GcpCloudBillingSource().validate_credentials(
            GcpCloudBillingSourceConfig(service_account_json=service_account_json), team_id=1
        )
    assert valid is False
    assert message == "Google rejected the service account key. Replace the key and reconnect."


def test_transient_token_failure_propagates(service_account_json: str) -> None:
    with (
        scripted_network([ScriptedResponse(status=503, json={"error": "temporarily_unavailable"})] * 20),
        pytest.raises(TransportError),
    ):
        GcpCloudBillingSource().validate_credentials(
            GcpCloudBillingSourceConfig(service_account_json=service_account_json), team_id=1
        )
