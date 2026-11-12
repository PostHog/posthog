from django.conf import settings

from posthog.integrations import IntegrationConflict, IntegrationManager
from posthog.integrations.contracts import IntegrationRecord
from posthog.models.team import Team
from posthog.models.user import User
from posthog.ph_client import feature_enabled_or_false

from products.workflows.backend.facade.contracts import SandboxSenderStatus, SandboxSenderUnavailable
from products.workflows.backend.models import SandboxSenderOrganizationBlock
from products.workflows.backend.services.sandbox_email.validation import ADOPTION_UNAVAILABLE

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


ORGANIZATION_BLOCKED = "This organization can't use the sandbox sender. Verify a domain to send email from workflows."


def set_up_sandbox_sender(team: Team, user: User) -> IntegrationRecord:
    check_sandbox_sender_available(team, user)
    return provision_sandbox_sender(team, user)


def check_sandbox_sender_available(team: Team, user: User) -> None:
    status = sandbox_sender_status(team, user)
    if not status.adoption_enabled:
        raise SandboxSenderUnavailable(ADOPTION_UNAVAILABLE)
    if status.organization_blocked:
        raise SandboxSenderUnavailable(ORGANIZATION_BLOCKED)


def has_verified_own_sender(team_id: int) -> bool:
    return any(sender.config.get("verified") for sender in IntegrationManager.email.credentials.list(team_id))


def verified_own_sender_ids(team_id: int) -> frozenset[int]:
    return frozenset(
        sender.id for sender in IntegrationManager.email.credentials.list(team_id) if sender.config.get("verified")
    )
