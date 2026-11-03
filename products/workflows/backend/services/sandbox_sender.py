from django.conf import settings

from posthog.integrations import IntegrationManager
from posthog.models.integration import SANDBOX_EMAIL_INTEGRATION_ID, SANDBOX_EMAIL_PROVIDER
from posthog.models.team import Team
from posthog.plugins.plugin_server_api import reload_integrations_on_workers

from products.workflows.backend.facade.contracts import SandboxEmailSender, SandboxSenderUnavailable
from products.workflows.backend.models.sandbox_sender_organization_block import SandboxSenderOrganizationBlock

SANDBOX_SENDER_FLAG = "workflows-sandbox-sender"
SANDBOX_SENDER_FALLBACK_NAME = "PostHog sandbox"
SANDBOX_SENDER_NAME_MAX_LENGTH = 40
_SANDBOX_SENDER_NAME_PUNCTUATION = frozenset(" .,&'-")


def _sandbox_sender_display_name(organization_name: str) -> str:
    kept = "".join(char for char in organization_name if char.isalnum() or char in _SANDBOX_SENDER_NAME_PUNCTUATION)
    name = " ".join(kept.split())[:SANDBOX_SENDER_NAME_MAX_LENGTH].strip()
    return f"{name} via PostHog" if name else SANDBOX_SENDER_FALLBACK_NAME


def _sandbox_sender_config(organization_name: str) -> dict[str, str | bool]:
    return {
        "provider": SANDBOX_EMAIL_PROVIDER,
        "email": settings.SES_SANDBOX_FROM_ADDRESS,
        "domain": settings.WORKFLOWS_SANDBOX_SENDER_DOMAIN,
        "name": _sandbox_sender_display_name(organization_name),
        "verified": True,
    }


def sandbox_sender_configured() -> bool:
    """Whether this deployment can provision sandbox senders. Off, no sandbox send can exist."""
    return bool(
        settings.WORKFLOWS_SANDBOX_SENDER_DOMAIN
        and settings.SES_SANDBOX_FROM_ADDRESS
        and settings.SES_SANDBOX_TENANT_NAME
    )


def _sandbox_sender_enabled(team: Team) -> bool:
    # Deferred: posthog.permissions pulls DRF and posthog.auth onto the django.setup() path,
    # and the workflows facade imports this module at startup.
    from posthog.permissions import posthog_feature_flag_enabled  # noqa: PLC0415

    # A flag-service error propagates: answering "unavailable" would hide an outage behind the
    # response a project gets while the flag is off.
    return posthog_feature_flag_enabled(
        SANDBOX_SENDER_FLAG,
        str(team.uuid),
        organization_id=team.organization_id,
        team_id=team.id,
    )


def sandbox_sender_enabled_for_team(team_id: int) -> bool:
    """Whether the project has the sandbox sender flag. Runs no query while the deployment has no sandbox sender."""
    if not sandbox_sender_configured():
        return False
    team = Team.objects.only("id", "uuid", "organization_id").get(id=team_id)
    return _sandbox_sender_enabled(team)


def _organization_blocked(team: Team) -> bool:
    return SandboxSenderOrganizationBlock.objects.filter(organization_id=team.organization_id).exists()


def ensure_sandbox_email_sender(team_id: int) -> SandboxEmailSender:
    team = Team.objects.select_related("organization").get(id=team_id)
    if not sandbox_sender_configured() or not _sandbox_sender_enabled(team) or _organization_blocked(team):
        raise SandboxSenderUnavailable()

    config = _sandbox_sender_config(team.organization.name)
    senders = IntegrationManager.email.credentials
    current = senders.find(team_id, external_id=SANDBOX_EMAIL_INTEGRATION_ID)
    if current is not None and current.config == config:
        return SandboxEmailSender(integration_id=current.id, created=False)
    integration, created = senders.upsert(team_id, SANDBOX_EMAIL_INTEGRATION_ID, config=config)
    if not created:
        reload_integrations_on_workers(team_id, [integration.id])
    return SandboxEmailSender(integration_id=integration.id, created=created)
