from typing import Literal

from django.conf import settings
from django.contrib.auth.models import AnonymousUser

import structlog

from posthog.exceptions_capture import capture_exception
from posthog.integrations import IntegrationManager
from posthog.models.integration import SANDBOX_EMAIL_INTEGRATION_ID, SANDBOX_EMAIL_PROVIDER
from posthog.models.team import Team
from posthog.models.user import User
from posthog.plugins.plugin_server_api import reload_integrations_on_workers

from products.workflows.backend.facade.contracts import SandboxEmailSender, SandboxSenderUnavailable

SANDBOX_SENDER_FLAG = "workflows-sandbox-sender"
# pinned: analytics event name - renaming breaks the impact insight
SANDBOX_SENDER_PROVISIONED_EVENT = "workflows sandbox sender provisioned"
SANDBOX_SENDER_FALLBACK_NAME = "PostHog sandbox"
SANDBOX_SENDER_NAME_MAX_LENGTH = 40
_SANDBOX_SENDER_NAME_PUNCTUATION = frozenset(" .,&'-")

logger = structlog.get_logger(__name__)

SandboxSenderReadSource = Literal["integrations_list", "setup_status", "data_suggestions"]


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


def sandbox_email_sender_for_reads(
    team: Team, *, reader: User | AnonymousUser, source: SandboxSenderReadSource
) -> SandboxEmailSender | None:
    if not _sandbox_sender_configured():
        return None
    try:
        if not _sandbox_sender_enabled_without_network_call(team):
            return None
        sender = _upsert_sandbox_email_sender(team)
    except Exception as error:
        logger.exception("workflows.sandbox_sender.ensure_on_read_failed", team_id=team.id)
        capture_exception(error, {"team_id": team.id})
        return None
    if sender.created and isinstance(reader, User):
        _report_provisioned_on_read(reader, team, source)
    return sender


def has_sandbox_email_sender(team: Team) -> bool:
    try:
        return (
            _sandbox_sender_configured()
            and _sandbox_sender_enabled_without_network_call(team)
            and IntegrationManager.email.credentials.find(team.id, external_id=SANDBOX_EMAIL_INTEGRATION_ID) is not None
        )
    except Exception as error:
        capture_exception(error, {"team_id": team.id})
        return False


def _sandbox_sender_enabled_without_network_call(team: Team) -> bool:
    return _sandbox_sender_enabled(team, only_evaluate_locally=True)


def _report_provisioned_on_read(reader: User, team: Team, source: SandboxSenderReadSource) -> None:
    from posthog.event_usage import report_user_action  # noqa: PLC0415

    report_user_action(reader, SANDBOX_SENDER_PROVISIONED_EVENT, {"source": source}, team=team)


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
