from django.conf import settings

from posthog.integrations import IntegrationConflict, IntegrationManager
from posthog.integrations.contracts import IntegrationRecord
from posthog.models.team import Team
from posthog.models.user import User
from posthog.ph_client import feature_enabled_or_false

from products.workflows.backend.facade.contracts import SandboxSenderStatus
from products.workflows.backend.models import SandboxSenderOrganizationBlock

SANDBOX_SENDER_ADOPTION_FLAG = "workflows-sandbox-sender"
SANDBOX_SENDER_INTEGRATION_ID = "posthog-managed-sandbox"


def sandbox_adoption_enabled(team: Team, user: User | None = None) -> bool:
    organization_id = str(team.organization_id)
    return feature_enabled_or_false(
        SANDBOX_SENDER_ADOPTION_FLAG,
        user.distinct_id if user is not None and user.distinct_id else str(team.uuid),
        groups={"organization": organization_id},
        group_properties={"organization": {"id": organization_id}},
        send_feature_flag_events=False,
    )


def organization_blocked(team: Team) -> bool:
    return SandboxSenderOrganizationBlock.objects.filter(organization_id=team.organization_id).exists()


def provision_sandbox_sender(team: Team, user: User) -> IntegrationRecord:
    accessor = IntegrationManager.email_sandbox.credentials
    existing = accessor.find(team.id, external_id=SANDBOX_SENDER_INTEGRATION_ID)
    if existing is not None:
        return existing
    try:
        return accessor.create(team.id, external_id=SANDBOX_SENDER_INTEGRATION_ID, config={}, created_by_id=user.id)
    except IntegrationConflict:
        winner = accessor.find(team.id, external_id=SANDBOX_SENDER_INTEGRATION_ID)
        if winner is None:
            raise
        return winner


def sandbox_sender_status(team: Team, user: User | None = None) -> SandboxSenderStatus:
    row = IntegrationManager.email_sandbox.credentials.find(team.id, external_id=SANDBOX_SENDER_INTEGRATION_ID)
    return SandboxSenderStatus(
        integration_id=row.id if row is not None else None,
        from_address=settings.SES_SANDBOX_FROM_ADDRESS,
        display_name=f"{team.organization.name} via PostHog",
        organization_blocked=organization_blocked(team),
        adoption_enabled=sandbox_adoption_enabled(team, user),
    )
