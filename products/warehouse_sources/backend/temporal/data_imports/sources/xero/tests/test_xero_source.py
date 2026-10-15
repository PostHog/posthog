from types import SimpleNamespace
from typing import Any

import pytest
from unittest.mock import patch

from products.warehouse_sources.backend.temporal.data_imports.sources.common.integration_accounts import (
    IntegrationAccount,
    IntegrationAccountListingError,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.xero import XeroSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.xero.source import XeroSource

_CONFIG = XeroSourceConfig(xero_integration_id=7, tenant_id="tenant-abc")


class TestXeroAccessToken:
    def test_rejects_an_integration_of_another_kind_before_reading_its_token(self) -> None:
        other = SimpleNamespace(kind="hubspot", access_token="hubspot-token")
        with (
            patch.object(XeroSource, "get_oauth_integration", return_value=other),
            patch(
                "products.warehouse_sources.backend.temporal.data_imports.sources.xero.source.resolve_xero_oauth_token"
            ) as resolve,
        ):
            with pytest.raises(ValueError, match="Integration not found"):
                XeroSource()._access_token(7, team_id=1)

        resolve.assert_not_called()


class TestXeroOrganisationPicker:
    def _accounts(self, script: Any) -> list[IntegrationAccount]:
        with (
            patch.object(XeroSource, "_access_token", return_value="at_1"),
            scripted_network(script),
        ):
            return XeroSource().get_oauth_accounts(7, team_id=1)

    def test_lists_organisations_and_skips_practice_manager_tenants(self) -> None:
        connections = [
            {"tenantId": "t-1", "tenantName": "Demo Company (UK)", "tenantType": "ORGANISATION"},
            {"tenantId": "t-2", "tenantName": "Practice", "tenantType": "PRACTICEMANAGER"},
        ]

        accounts = self._accounts([ScriptedResponse(json=connections)])

        assert [(account.value, account.display_name) for account in accounts] == [("t-1", "Demo Company (UK)")]

    @pytest.mark.parametrize(
        ("response", "message"),
        [
            (ScriptedResponse(json=[]), "no organisation connected"),
            (ScriptedResponse(status=401, json={"Title": "Unauthorized", "Status": 401}), "Reconnect"),
        ],
    )
    def test_turns_an_unusable_listing_into_an_actionable_error(self, response: ScriptedResponse, message: str) -> None:
        with pytest.raises(IntegrationAccountListingError, match=message):
            self._accounts([response])


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
            patch.object(XeroSource, "_access_token", return_value="at_1"),
            scripted_network(always(ScriptedResponse(status=status, json={}))) as network,
        ):
            assert XeroSource().validate_credentials(_CONFIG, team_id=1) == expected

        assert {request.path for request in network.requests_log} == {"/api.xro/2.0/Organisation"}
        assert network.requests_log[0].headers["xero-tenant-id"] == "tenant-abc"

    def test_deleted_connection_asks_for_a_reconnect(self) -> None:
        with patch.object(XeroSource, "_access_token", side_effect=ValueError("Integration not found: 7")):
            assert XeroSource().validate_credentials(_CONFIG, team_id=1) == (
                False,
                "The Xero connection no longer exists. Reconnect your Xero account.",
            )
