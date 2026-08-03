from posthog.test.base import APIBaseTest

from django.test import override_settings

import responses
from rest_framework import status

from posthog.models import OrganizationMembership

CONNECTION_ID = "7c18c57e-f1bb-4309-b879-42cb9a8c079e"
TENANT_ID = "8247d991-d342-4ea3-a5d1-dce541312cb8"


@override_settings(
    DEBUG=True,
    SECURE_CONNECTION_MANAGEMENT_URL="https://management.internal",
    SECURE_CONNECTION_CONTROL_URL="https://control.internal",
    SECURE_CONNECTION_PUBLIC_CONTROL_URL="https://connect.example.com",
    SECURE_CONNECTION_ADMIN_TOKEN="operator-secret",
)
class TestSecureConnectionApprovalsApi(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/secure_connections/cdp_approvals/"

    def _mock_active_connection(
        self,
        *,
        connection_id: str = CONNECTION_ID,
        selector_kind: str = "hostname",
        selector: str = "api.internal.example",
    ) -> None:
        responses.get(
            f"https://management.internal/admin/tenants/posthog-team-{self.team.id}",
            json={"id": TENANT_ID, "slug": f"posthog-team-{self.team.id}"},
        )
        responses.post(
            f"https://management.internal/admin/tenants/{TENANT_ID}/tokens",
            json={"token": "tenant-token"},
        )
        responses.get(
            f"https://control.internal/api/tenants/{TENANT_ID}/connections",
            json={
                "connections": [
                    {
                        "id": connection_id,
                        "name": "internal-api",
                        "kind": "http",
                        "selector_kind": selector_kind,
                        "selector": selector,
                        "status": "active",
                    }
                ]
            },
        )

    def test_member_can_list_but_cannot_change_cdp_approvals(self) -> None:
        response = self.client.get(self.url)
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"cdp_approved_connections": {}}

        response = self.client.post(self.url, {"connection_id": CONNECTION_ID, "approved": True})
        assert response.status_code == status.HTTP_403_FORBIDDEN

    @responses.activate
    def test_admin_cannot_approve_a_port_routed_service_for_cdp(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self._mock_active_connection(selector_kind="port", selector="5432")

        response = self.client.post(self.url, {"connection_id": CONNECTION_ID, "approved": True})

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["attr"] == "connection_id"

    @responses.activate
    def test_admin_can_approve_and_revoke_an_active_connection(self) -> None:
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()
        self._mock_active_connection()

        response = self.client.post(self.url, {"connection_id": CONNECTION_ID, "approved": True})

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["cdp_approved_connections"][CONNECTION_ID] == {
            "name": "internal-api",
            "selector_kind": "hostname",
            "selector": "api.internal.example",
        }
        self.team.refresh_from_db()
        assert self.team.extra_settings is not None
        assert (
            self.team.extra_settings["secure_connections"]["cdp_approved_connections"][CONNECTION_ID]["selector"]
            == "api.internal.example"
        )

        responses.reset()
        response = self.client.post(self.url, {"connection_id": CONNECTION_ID, "approved": False})

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"cdp_approved_connections": {}}
