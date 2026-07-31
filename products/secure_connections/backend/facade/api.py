from django.conf import settings
from django.db import transaction

from products.secure_connections.backend.client import SecureConnectionServiceClient
from products.secure_connections.backend.facade.contracts import (
    SecureConnection,
    SecureConnectionEnrollment,
    SecureConnectionState,
    SecureConnectionStatus,
)
from products.secure_connections.backend.models import TeamSecureConnectionsConfig


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
            selector_kind=str(connection["selector_kind"]),
            selector=str(connection["selector"]),
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


def get_cdp_approved_connections(team_id: int) -> dict[str, dict[str, str]]:
    config = TeamSecureConnectionsConfig.objects.filter(team_id=team_id).only("cdp_approved_connections").first()
    return config.cdp_approved_connections if config else {}


@transaction.atomic
def set_cdp_connection_approval(team_id: int, connection: SecureConnection, *, approved: bool) -> None:
    config, _ = TeamSecureConnectionsConfig.objects.select_for_update().get_or_create(team_id=team_id)
    approvals = dict(config.cdp_approved_connections)
    if approved:
        approvals[connection.id] = {
            "name": connection.name,
            "selector_kind": connection.selector_kind,
            "selector": connection.selector,
        }
    else:
        approvals.pop(connection.id, None)
    config.cdp_approved_connections = approvals
    config.save(update_fields=["cdp_approved_connections"])
