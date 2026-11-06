from django.conf import settings

import structlog

from posthog.models.integration import SANDBOX_EMAIL_INTEGRATION_ID, SANDBOX_EMAIL_PROVIDER, Integration
from posthog.models.team import Team
from posthog.permissions import posthog_feature_flag_enabled
from posthog.plugins.plugin_server_api import reload_integrations_on_workers

from products.workflows.backend.facade.contracts import SandboxEmailSender

logger = structlog.get_logger(__name__)

SANDBOX_SENDER_FLAG = "workflows-sandbox-sender"
SANDBOX_SENDER_FALLBACK_NAME = "PostHog sandbox"
SANDBOX_SENDER_NAME_MAX_LENGTH = 40
_SANDBOX_SENDER_NAME_PUNCTUATION = frozenset(" .,&'-")


class SandboxSenderUnavailable(Exception):
    pass


def ensure_sandbox_email_sender(team_id: int) -> SandboxEmailSender:
    team = Team.objects.select_related("organization").get(id=team_id)
    if not _sandbox_sender_configured() or not _sandbox_sender_enabled(team):
        raise SandboxSenderUnavailable()

    config = _sandbox_sender_config(team.organization.name)
    integration, created = Integration.objects.get_or_create(
        team_id=team_id,
        kind="email",
        integration_id=SANDBOX_EMAIL_INTEGRATION_ID,
        defaults={"config": config, "created_by": None},
    )
    if not created and integration.config != config:
        integration.config = config
        integration.save()
        reload_integrations_on_workers(team_id, [integration.id])
    return SandboxEmailSender(integration=integration, created=created)


def sandbox_sender_display_name(organization_name: str) -> str:
    kept = "".join(char for char in organization_name if char.isalnum() or char in _SANDBOX_SENDER_NAME_PUNCTUATION)
    name = " ".join(kept.split())[:SANDBOX_SENDER_NAME_MAX_LENGTH].strip()
    return f"{name} via PostHog" if name else SANDBOX_SENDER_FALLBACK_NAME


def _sandbox_sender_config(organization_name: str) -> dict[str, str | bool]:
    return {
        "provider": SANDBOX_EMAIL_PROVIDER,
        "email": settings.WORKFLOWS_SANDBOX_SENDER_FROM_ADDRESS,
        "domain": settings.WORKFLOWS_SANDBOX_SENDER_DOMAIN,
        "name": sandbox_sender_display_name(organization_name),
        "verified": True,
    }


def _sandbox_sender_configured() -> bool:
    return bool(settings.WORKFLOWS_SANDBOX_SENDER_DOMAIN and settings.WORKFLOWS_SANDBOX_SENDER_FROM_ADDRESS)


def _sandbox_sender_enabled(team: Team) -> bool:
    # A failed flag evaluation reads as off, so an outage never hands out sandbox senders.
    try:
        return posthog_feature_flag_enabled(
            SANDBOX_SENDER_FLAG,
            str(team.uuid),
            organization_id=team.organization_id,
            team_id=team.id,
        )
    except Exception:
        logger.warning("workflows.sandbox_sender_flag_check_failed", team_id=team.id, exc_info=True)
        return False
