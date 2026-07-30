from collections.abc import Callable

from django.db import transaction
from django.utils import timezone

import structlog

from posthog.tasks.email import (
    send_email_sending_reputation_finding,
    send_email_sending_suspended,
    send_email_sending_unsuspended,
)

from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig
from products.workflows.backend.providers.ses import SESProvider

logger = structlog.get_logger(__name__)

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
    the dedupe mechanism — the row is locked for the read-compare-write so overlapping syncs
    (webhook + sweep, or duplicate events) serialize, and the loser sees an unchanged state.
    """
    impact = reputation_impact or ""
    TeamWorkflowsConfig.objects.get_or_create(team_id=team_id)

    with transaction.atomic():
        config = TeamWorkflowsConfig.objects.select_for_update().get(team_id=team_id)
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
            team_id=team_id,
            from_status=previous_status,
            to_status=sending_status,
            from_impact=previous_impact,
            to_impact=impact,
        )

        notify = _pick_notification(
            previous_status=previous_status,
            previous_impact=previous_impact,
            sending_status=sending_status,
            impact=impact,
            team_id=team_id,
            now_iso=now.isoformat(),
        )
        if notify is not None:
            # Dispatch after commit so a rollback can't leave an email claiming a state
            # that was never persisted.
            transaction.on_commit(notify)


def _pick_notification(
    *, previous_status: str, previous_impact: str, sending_status: str, impact: str, team_id: int, now_iso: str
) -> Callable[[], None] | None:
    if previous_status == "":
        # First sync is baseline adoption, not a transition — healthy teams stay silent so
        # rollout doesn't mass-email. But a tenant that is ALREADY paused or already carries
        # high-impact findings is exactly who this feature exists to tell, so those do notify.
        if sending_status == "DISABLED":
            return lambda: send_email_sending_suspended.delay(team_id, PROVIDER_PAUSE_REASON, now_iso)
        if impact == "HIGH":
            return lambda: send_email_sending_reputation_finding.delay(team_id, impact, now_iso)
        return None

    if sending_status == "DISABLED" and previous_status != "DISABLED":
        return lambda: send_email_sending_suspended.delay(team_id, PROVIDER_PAUSE_REASON, now_iso)
    if previous_status == "DISABLED" and sending_status in ("ENABLED", "REINSTATED"):
        return lambda: send_email_sending_unsuspended.delay(team_id, now_iso)
    if sending_status != "DISABLED" and _IMPACT_SEVERITY.get(impact, 0) > _IMPACT_SEVERITY.get(previous_impact, 0):
        # Escalation only, and only while still sending — a paused tenant already got the
        # suspension email, and de-escalations don't need action.
        return lambda: send_email_sending_reputation_finding.delay(team_id, impact, now_iso)
    return None
