from django.conf import settings

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.integrations import IntegrationManager
from posthog.models.integration import SANDBOX_EMAIL_INTEGRATION_ID, SANDBOX_EMAIL_PROVIDER
from posthog.models.team import Team
from posthog.plugins.plugin_server_api import reload_integrations_on_workers

from products.workflows.backend.facade.contracts import SandboxEmailSender, SandboxSenderUnavailable

SANDBOX_SENDER_FLAG = "workflows-sandbox-sender"
SANDBOX_SENDER_FALLBACK_NAME = "PostHog sandbox"
SANDBOX_SENDER_NAME_MAX_LENGTH = 40
_SANDBOX_SENDER_NAME_PUNCTUATION = frozenset(" .,&'-")

logger = structlog.get_logger(__name__)


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


def _sandbox_sender_configured() -> bool:
    return bool(
        settings.WORKFLOWS_SANDBOX_SENDER_DOMAIN
        and settings.SES_SANDBOX_FROM_ADDRESS
        and settings.SES_SANDBOX_TENANT_NAME
    )


def _sandbox_sender_enabled(team: Team, *, only_evaluate_locally: bool = False) -> bool:
    # Deferred: posthog.permissions pulls DRF and posthog.auth onto the django.setup() path,
    # and the workflows facade imports this module at startup.
    from posthog.permissions import posthog_feature_flag_enabled  # noqa: PLC0415

    return posthog_feature_flag_enabled(
        SANDBOX_SENDER_FLAG,
        str(team.uuid),
        organization_id=team.organization_id,
        team_id=team.id,
        only_evaluate_locally=only_evaluate_locally,
    )


def ensure_sandbox_email_sender(team_id: int) -> SandboxEmailSender:
    team = Team.objects.select_related("organization").get(id=team_id)
    if not _sandbox_sender_configured() or not _sandbox_sender_enabled(team):
        raise SandboxSenderUnavailable()
    return _upsert_sandbox_email_sender(team)


def sandbox_email_sender_for_reads(team: Team) -> SandboxEmailSender | None:
    """The sandbox sender of a flagged project, created by the first read that needs it.

    Sender lists and setup checks call this on every request. A failure returns None so the read still answers.
    """
    if not _sandbox_sender_configured():
        return None
    try:
        # Local evaluation only, so a flag condition the SDK can't evaluate in memory never adds a network call to a read.
        if not _sandbox_sender_enabled(team, only_evaluate_locally=True):
            return None
        return _upsert_sandbox_email_sender(team)
    except Exception as error:
        logger.exception("workflows.sandbox_sender.ensure_on_read_failed", team_id=team.id)
        capture_exception(error, {"team_id": team.id})
        return None


def _upsert_sandbox_email_sender(team: Team) -> SandboxEmailSender:
    config = _sandbox_sender_config(team.organization.name)
    senders = IntegrationManager.email.credentials
    current = senders.find(team.id, external_id=SANDBOX_EMAIL_INTEGRATION_ID)
    if current is not None and current.config == config:
        return SandboxEmailSender(integration_id=current.id, created=False)
    integration, created = senders.upsert(team.id, SANDBOX_EMAIL_INTEGRATION_ID, config=config)
    if not created:
        reload_integrations_on_workers(team.id, [integration.id])
    return SandboxEmailSender(integration_id=integration.id, created=created)
