import logging

from django.utils import timezone

from posthog.tasks.email import (
    send_email_sending_reputation_finding,
    send_email_sending_suspended,
    send_email_sending_unsuspended,
)

from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig
from products.workflows.backend.providers.ses import SESProvider

logger = logging.getLogger(__name__)

PROVIDER_PAUSE_REASON = "Our email provider paused sending for this project because of high-impact reputation findings"

_IMPACT_SEVERITY = {"": 0, "LOW": 1, "HIGH": 2}

_STATE_FIELDS = ["ses_tenant_sending_status", "ses_tenant_reputation_impact", "ses_tenant_state_synced_at"]


def sync_ses_tenant_state(team_id: int) -> None:
    """
    Fetch the authoritative AWS SES tenant state for a team and apply it. Called from the
    EventBridge webhook (events only say "something changed" — the API is the source of truth)
    and from the periodic reconciliation sweep (event delivery is best-effort).
    """
    tenant = SESProvider().get_tenant_reputation(team_id)
    if tenant is None:
        return
    apply_ses_tenant_state(
        team_id, sending_status=tenant["sending_status"], reputation_impact=tenant["reputation_impact"]
    )


def apply_ses_tenant_state(team_id: int, *, sending_status: str, reputation_impact: str | None) -> None:
    """
    Persist the tenant state and email the project's admins on meaningful transitions:
    sending paused, sending re-enabled, or reputation findings escalating. The stored state is
    the dedupe mechanism — reapplying an unchanged state sends nothing, so the webhook and the
    sweep can safely overlap.
    """
    impact = reputation_impact or ""
    config, _ = TeamWorkflowsConfig.objects.get_or_create(team_id=team_id)
    previous_status = config.ses_tenant_sending_status
    previous_impact = config.ses_tenant_reputation_impact
    if previous_status == sending_status and previous_impact == impact:
        config.ses_tenant_state_synced_at = timezone.now()
        config.save(update_fields=["ses_tenant_state_synced_at"])
        return

    now = timezone.now()
    config.ses_tenant_sending_status = sending_status
    config.ses_tenant_reputation_impact = impact
    config.ses_tenant_state_synced_at = now
    config.save(update_fields=_STATE_FIELDS)
    logger.info(
        "SES tenant state changed",
        extra={
            "team_id": team_id,
            "from_status": previous_status,
            "to_status": sending_status,
            "from_impact": previous_impact,
            "to_impact": impact,
        },
    )

    if previous_status == "":
        # First sync is baseline adoption, not a transition — don't notify on rollout.
        return

    if sending_status == "DISABLED" and previous_status != "DISABLED":
        send_email_sending_suspended.delay(team_id, PROVIDER_PAUSE_REASON, now.isoformat())
    elif previous_status == "DISABLED" and sending_status in ("ENABLED", "REINSTATED"):
        send_email_sending_unsuspended.delay(team_id, now.isoformat())
    elif _IMPACT_SEVERITY.get(impact, 0) > _IMPACT_SEVERITY.get(previous_impact, 0):
        # Escalation only, and only while still sending — the pause email above already covers
        # the paused case, and de-escalations don't need action.
        send_email_sending_reputation_finding.delay(team_id, impact, now.isoformat())
