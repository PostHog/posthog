from types import SimpleNamespace
from typing import Any

import pytest
from unittest.mock import patch

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.common.integration_accounts import (
    IntegrationAccount,
    IntegrationAccountListingError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.xero import XeroSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.xero.source import XeroSource

_CONFIG = XeroSourceConfig(xero_integration_id=7, tenant_id="tenant-abc")
_RESOLVE_TOKEN = "products.warehouse_sources.backend.temporal.data_imports.sources.xero.source.resolve_xero_oauth_token"


def _xero_integration(*tenant_ids: str) -> SimpleNamespace:
    tenants = [{"tenantId": tenant_id, "tenantName": tenant_id} for tenant_id in tenant_ids]
    return SimpleNamespace(kind="xero", config={"xero_tenants": tenants})


class TestXeroAccessToken:
    def test_rejects_an_integration_of_another_kind_before_reading_its_token(self) -> None:
        other = SimpleNamespace(kind="hubspot", access_token="hubspot-token")
        with (
            patch.object(XeroSource, "get_oauth_integration", return_value=other),
            patch(_RESOLVE_TOKEN) as resolve,
        ):
            with pytest.raises(ValueError, match="Integration not found"):
                XeroSource()._consented_tenant_ids(7, team_id=1)

        resolve.assert_not_called()

    def test_sync_refuses_an_organisation_outside_the_connections_consent(self) -> None:
        with (
            patch.object(XeroSource, "get_oauth_integration", return_value=_xero_integration("other-org")),
            patch(_RESOLVE_TOKEN) as resolve,
        ):
            result = SourceDriver(XeroSource(), _CONFIG).run("invoices", [])

        assert isinstance(result.raised, ValueError)
        assert "not chosen when this Xero account was connected" in str(result.raised)
        resolve.assert_not_called()


class TestXeroOrganisationPicker:
    def _accounts(self, script: Any) -> list[IntegrationAccount]:
        with (
            patch.object(XeroSource, "get_oauth_integration", return_value=_xero_integration("t-1")),
            patch(_RESOLVE_TOKEN, return_value="at_1"),
            scripted_network(script),
        ):
            return XeroSource().get_oauth_accounts(7, team_id=1)

    def test_lists_only_consented_organisations(self) -> None:
        # t-3 belongs to another consent of the same Xero user, possibly in another project.
        connections = [
            {"tenantId": "t-1", "tenantName": "Demo Company (UK)", "tenantType": "ORGANISATION"},
            {"tenantId": "t-2", "tenantName": "Practice", "tenantType": "PRACTICEMANAGER"},
            {"tenantId": "t-3", "tenantName": "Other company", "tenantType": "ORGANISATION"},
        ]

        accounts = self._accounts([ScriptedResponse(json=connections)])

        assert [(account.value, account.display_name) for account in accounts] == [("t-1", "Demo Company (UK)")]

    @pytest.mark.parametrize(
        ("response", "message"),
        [
            (ScriptedResponse(json=[]), "still connected"),
            (ScriptedResponse(status=401, json={"Title": "Unauthorized", "Status": 401}), "Reconnect"),
            (ScriptedResponse(status=503, json={"Title": "Service Unavailable"}), "Could not reach Xero"),
            (requests.ConnectionError("connection reset"), "Could not reach Xero"),
        ],
    )
    def test_turns_an_unusable_listing_into_an_actionable_error(self, response: Any, message: str) -> None:
        with pytest.raises(IntegrationAccountListingError, match=message):
            self._accounts(always(response))


class TestXeroValidateCredentials:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (200, (True, None)),
            (
                403,
                (False, "Xero refused access to this organisation. Pick an organisation the connected user can open."),
            ),
            (503, (False, "Could not reach Xero. Try again in a few minutes.")),
        ],
    )
    def test_maps_the_organisation_probe(self, status: int, expected: tuple[bool, str | None]) -> None:
        with (
            patch.object(XeroSource, "get_oauth_integration", return_value=_xero_integration("tenant-abc")),
            patch(_RESOLVE_TOKEN, return_value="at_1"),
            scripted_network(always(ScriptedResponse(status=status, json={}))) as network,
        ):
            assert XeroSource().validate_credentials(_CONFIG, team_id=1) == expected

        assert {request.path for request in network.requests_log} == {"/api.xro/2.0/Organisation"}
        assert network.requests_log[0].headers["xero-tenant-id"] == "tenant-abc"

    @pytest.mark.parametrize(
        ("integration", "expected_message"),
        [
            (ValueError("Integration not found: 7"), "This Xero connection no longer works"),
            (_xero_integration("other-org"), "not chosen when this Xero account was connected"),
        ],
    )
    def test_refuses_before_any_request(self, integration: Any, expected_message: str) -> None:
        lookup = {"side_effect": integration} if isinstance(integration, Exception) else {"return_value": integration}
        with patch.object(XeroSource, "get_oauth_integration", **lookup), scripted_network([]) as network:
            is_valid, message = XeroSource().validate_credentials(_CONFIG, team_id=1)

        assert is_valid is False
        assert message is not None and expected_message in message
        assert network.requests_log == []
