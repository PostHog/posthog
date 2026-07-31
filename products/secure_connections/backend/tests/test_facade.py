import json

from django.test import SimpleTestCase, override_settings

import responses

from products.secure_connections.backend.facade import api
from products.secure_connections.backend.facade.contracts import SecureConnectionState


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
                        "status": "active",
                    },
                    {
                        "id": "83f4eeea-f273-4c61-ac24-37f46d23af6f",
                        "name": "old-api",
                        "kind": "http",
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
        assert responses.calls[2].request.headers["Authorization"] == "Bearer tenant-token"

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
            "audience": "control",
            "scopes": ["advertise"],
            "ttl_seconds": 31536000,
        }
