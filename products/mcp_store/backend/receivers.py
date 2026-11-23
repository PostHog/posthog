"""Removes a member's MCP connections when they leave an organization.

A grant lends its owner's connection to the project's agent runs, and OAuth tokens refresh on use, so a
departed member's credential would otherwise keep acting in agent runs. Their shared connections go too,
because a shared connection lends its creator's credential to every teammate.
"""

from typing import Any

from django.db import transaction
from django.db.models.signals import post_delete

import structlog

from posthog.models.organization import OrganizationMembership

from products.mcp_store.backend.models import MCPServerInstallation, MCPServiceAccountServerAccess

logger = structlog.get_logger(__name__)


def _remove_member_mcp_connections(
    sender: type[OrganizationMembership], instance: OrganizationMembership, **kwargs: Any
) -> None:
    with transaction.atomic():
        MCPServiceAccountServerAccess.objects.unscoped().filter(
            user_id=instance.user_id, team__organization_id=instance.organization_id
        ).delete()
        connections = MCPServerInstallation.objects.filter(
            user_id=instance.user_id, team__organization_id=instance.organization_id
        )
        deleted_count = connections.count()
        connections.delete()

    if deleted_count > 0:
        logger.info(
            "Removed MCP connections for user removed from organization",
            user_id=instance.user_id,
            organization_id=str(instance.organization_id),
            deleted_count=deleted_count,
        )


def connect() -> None:
    post_delete.connect(
        _remove_member_mcp_connections,
        sender=OrganizationMembership,
        dispatch_uid="mcp_store_remove_member_mcp_connections",
    )
