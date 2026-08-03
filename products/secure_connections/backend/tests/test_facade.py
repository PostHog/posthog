import json

from posthog.test.base import BaseTest

from django.test import SimpleTestCase, override_settings

import responses

from products.secure_connections.backend.facade import api
from products.secure_connections.backend.facade.contracts import SecureConnection, SecureConnectionState


@override_settings(
    SECURE_CONNECTION_MANAGEMENT_URL="https://management.internal",
    SECURE_CONNECTION_CONTROL_URL="https://control.internal",
    SECURE_CONNECTION_PUBLIC_CONTROL_URL="https://connect.example.com",
    SECURE_CONNECTION_ADMIN_TOKEN="operator-secret",
)
class TestSecureConnectionsFacade(SimpleTestCase):
    @override_settings(DEBUG=True, SECURE_CONNECTION_DEMO_TENANT_SLUG="acme")
    def test_debug_demo_uses_preloaded_tenant(self) -> None:
        assert api.tenant_slug(team_id=42) == "acme"

    @override_settings(DEBUG=False, SECURE_CONNECTION_DEMO_TENANT_SLUG="acme")
    def test_deployed_environment_ignores_demo_tenant(self) -> None:
        assert api.tenant_slug(team_id=42) == "posthog-team-42"

    @responses.activate
    def test_status_is_scoped_to_the_team_tenant(self) -> None:
        responses.get(
            "https://management.internal/admin/tenants/posthog-team-42",
            json={"id": "8247d991-d342-4ea3-a5d1-dce541312cb8", "slug": "posthog-team-42"},
        )
        responses.post(
            "https://management.internal/admin/tenants/8247d991-d342-4ea3-a5d1-dce541312cb8/tokens",
            json={"token": "tenant-token"},
            status=201,
        )
        responses.get(
            "https://control.internal/api/tenants/8247d991-d342-4ea3-a5d1-dce541312cb8/connections",
            json={
                "connections": [
                    {
                        "id": "7c18c57e-f1bb-4309-b879-42cb9a8c079e",
                        "name": "internal-api",
                        "kind": "http",
                        "selector_kind": "hostname",
                        "selector": "internal-api.local",
                        "status": "active",
                    },
                    {
                        "id": "83f4eeea-f273-4c61-ac24-37f46d23af6f",
                        "name": "old-api",
                        "kind": "http",
                        "selector_kind": "hostname",
                        "selector": "old-api.local",
                        "status": "disabled",
                    },
                ]
            },
        )

        result = api.get_status(team_id=42)

        assert result.connection_state == SecureConnectionState.CONNECTED
        assert len(result.connections) == 1
        assert result.connections[0].name == "internal-api"
        assert responses.calls[0].request.headers["Authorization"] == "Bearer operator-secret"
        assert json.loads(responses.calls[1].request.body)["audience"] == "burrow-control"
        assert responses.calls[2].request.headers["Authorization"] == "Bearer tenant-token"

    @responses.activate
    def test_status_falls_back_to_selector_kind_when_kind_is_empty(self) -> None:
        tenant_id = "8247d991-d342-4ea3-a5d1-dce541312cb8"
        responses.get(
            "https://management.internal/admin/tenants/posthog-team-42",
            json={"id": tenant_id, "slug": "posthog-team-42"},
        )
        responses.post(f"https://management.internal/admin/tenants/{tenant_id}/tokens", json={"token": "token"})
        responses.get(
            f"https://control.internal/api/tenants/{tenant_id}/connections",
            json={
                "connections": [
                    {
                        "id": "7c18c57e-f1bb-4309-b879-42cb9a8c079e",
                        "name": "warehouse",
                        "kind": "",
                        "selector_kind": "port",
                        "selector": "5432",
                        "status": "active",
                    }
                ]
            },
        )

        result = api.get_status(team_id=42)

        assert result.connections[0].connection_type == "port"

    @responses.activate
    def test_missing_tenant_does_not_mint_credentials(self) -> None:
        responses.get(
            "https://management.internal/admin/tenants/posthog-team-77",
            status=404,
        )

        result = api.get_status(team_id=77)

        assert result.connection_state == SecureConnectionState.NOT_CONFIGURED
        assert result.connections == ()
        assert len(responses.calls) == 1

    @responses.activate
    def test_enrollment_uses_team_id_and_separate_scoped_credentials(self) -> None:
        tenant_id = "8247d991-d342-4ea3-a5d1-dce541312cb8"
        responses.post(
            "https://management.internal/admin/tenants",
            json={"id": tenant_id, "slug": "posthog-team-42"},
            status=201,
        )
        responses.post(
            f"https://management.internal/admin/tenants/{tenant_id}/keys",
            json={"key": "enrollment-key"},
            status=201,
        )
        responses.post(
            f"https://management.internal/admin/tenants/{tenant_id}/tokens",
            json={"token": "advertisement-token"},
            status=201,
        )

        result = api.create_enrollment(team_id=42)

        assert result.enrollment_key == "enrollment-key"
        assert result.advertisement_token == "advertisement-token"
        assert result.tenant_id == tenant_id
        assert json.loads(responses.calls[0].request.body) == {"external_id": "42", "slug": "posthog-team-42"}
        assert json.loads(responses.calls[2].request.body) == {
            "name": "connection-proxy",
            "audience": "burrow-control",
            "scopes": ["advertise"],
            "ttl_seconds": 31536000,
        }


class TestSecureConnectionApprovals(BaseTest):
    def test_cdp_access_is_denied_by_default_and_can_be_approved_then_revoked(self) -> None:
        connection = SecureConnection(
            id="7c18c57e-f1bb-4309-b879-42cb9a8c079e",
            name="internal-api",
            connection_type="http",
            connection_status="active",
            selector_kind="hostname",
            selector="api.internal.example",
        )

        assert api.get_cdp_approved_connections(self.team.id) == {}

        api.set_cdp_connection_approval(self.team.id, connection, approved=True)

        assert api.get_cdp_approved_connections(self.team.id) == {
            connection.id: {
                "name": "internal-api",
                "selector_kind": "hostname",
                "selector": "api.internal.example",
            }
        }
        self.team.refresh_from_db()
        assert self.team.extra_settings is not None
        assert (
            self.team.extra_settings["secure_connections"]["cdp_approved_connections"][connection.id]["selector"]
            == "api.internal.example"
        )

        api.set_cdp_connection_approval(self.team.id, connection, approved=False)

        assert api.get_cdp_approved_connections(self.team.id) == {}
