from django.conf import settings

from products.secure_connections.backend.client import SecureConnectionServiceClient
from products.secure_connections.backend.facade.contracts import (
    SecureConnection,
    SecureConnectionEnrollment,
    SecureConnectionState,
    SecureConnectionStatus,
)


def tenant_slug(team_id: int) -> str:
    if settings.DEBUG and settings.SECURE_CONNECTION_DEMO_TENANT_SLUG:
        return settings.SECURE_CONNECTION_DEMO_TENANT_SLUG
    return f"posthog-team-{team_id}"


def get_status(team_id: int) -> SecureConnectionStatus:
    client = SecureConnectionServiceClient()
    tenant = client.get_tenant(tenant_slug(team_id))
    if tenant is None:
        return SecureConnectionStatus(connection_state=SecureConnectionState.NOT_CONFIGURED, connections=())

    service_connections = client.list_connections(tenant.id)
    connections = tuple(
        SecureConnection(
            id=str(connection["id"]),
            name=str(connection["name"]),
            connection_type=str(connection.get("kind") or connection["selector_kind"]),
            connection_status=str(connection["status"]),
        )
        for connection in service_connections
        if connection["status"] == "active"
    )
    state = SecureConnectionState.CONNECTED if connections else SecureConnectionState.WAITING
    return SecureConnectionStatus(connection_state=state, connections=connections)


def create_enrollment(team_id: int) -> SecureConnectionEnrollment:
    client = SecureConnectionServiceClient()
    tenant = client.create_tenant(team_id=team_id, slug=tenant_slug(team_id))
    return SecureConnectionEnrollment(
        enrollment_key=client.mint_enrollment_key(tenant.id),
        advertisement_token=client.mint_advertisement_token(tenant.id),
        tenant_id=tenant.id,
        control_url=client.public_control_url,
    )
