from collections.abc import Callable
from typing import Any

from django.db import transaction
from django.utils import timezone

import structlog

from posthog.models.team import Team
from posthog.plugins.plugin_server_api import reload_team_workflows_config_on_workers
from posthog.tasks.email import (
    send_email_sending_reputation_finding,
    send_email_sending_suspended,
    send_email_sending_unsuspended,
)

from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig
from products.workflows.backend.providers.ses import SESProvider

logger = structlog.get_logger(__name__)

PROVIDER_PAUSE_REASON = "Our email provider paused sending for this project because of high-impact reputation findings"
# A tenant can also be paused without high-impact findings: someone pausing it directly in the
# provider console shows up here identically. Don't assert a cause we can't see.
PROVIDER_PAUSE_REASON_UNSPECIFIED = "Our email provider paused sending for this project"

# AWS reports "NONE" for a tenant with no findings; "" is our own never-synced sentinel. Unknown
# values sort below LOW so a new AWS level can't be mistaken for an escalation we understand.
_IMPACT_SEVERITY = {"": 0, "NONE": 0, "LOW": 1, "HIGH": 2}

_MAX_FINDINGS_IN_EMAIL = 5

# Our wording for each type AWS can raise (its RecommendationType enum). The provider's own
# Description is its copy in its voice, and it arrives empty often enough to be unusable as-is.
_FINDING_DESCRIPTIONS = {
    "BOUNCE": "Stop sending to addresses that have bounced",
    "COMPLAINT": "Too many recipients are marking these emails as spam",
    "IP_LISTING": "A sending IP has been added to a blocklist",
    "FEEDBACK_3P": "A mailbox provider has flagged your sending",
    "DKIM": "Set up DKIM for your sending domain",
    "SPF": "Set up SPF for your sending domain",
    "DMARC": "Set up DMARC for your sending domain",
    "BIMI": "Set up BIMI for your sending domain",
}

_STATE_FIELDS = ["ses_tenant_sending_status", "ses_tenant_reputation_impact", "ses_tenant_state_synced_at"]


def _announce_state_change(team_id: int) -> None:
    """
    Tell the send path to drop its cached copy of the row. Best effort: it re-reads within a couple
    of minutes anyway, so a Redis blip must not fail a webhook or sweep whose state change has
    already committed — the retry would find the state unchanged and never announce it at all.
    """
    try:
        reload_team_workflows_config_on_workers(team_id)
    except Exception:
        logger.exception("Failed to announce SES tenant state change to workers", team_id=team_id)


def sync_ses_tenant_state(team_id: int, provider: SESProvider | None = None, *, verify_team: bool = True) -> None:
    """
    Fetch the authoritative AWS SES tenant state for a team and apply it. Called from the
    EventBridge webhook (events only say "something changed" — the API is the source of truth)
    and from the periodic reconciliation sweep (event delivery is best-effort).
    """
    # SES holds tenants for teams that no longer exist here (a deleted project keeps its tenant),
    # and the webhook takes its team id from whatever AWS sent. Without this the config row's FK to
    # posthog_team fails and the task retries a write that can never succeed. The sweep passes
    # verify_team=False: it reads team ids off integration rows, so the team exists by construction.
    if verify_team and not Team.objects.filter(id=team_id).exists():
        logger.warning("Skipping SES tenant state sync for unknown team", team_id=team_id)
        return

    tenant = (provider or SESProvider()).get_tenant_reputation(team_id)
    if tenant is None:
        return
    apply_ses_tenant_state(
        team_id,
        sending_status=tenant["sending_status"],
        reputation_impact=tenant["reputation_impact"],
        findings=tenant["findings"],
    )


def apply_ses_tenant_state(
    team_id: int,
    *,
    sending_status: str,
    reputation_impact: str | None,
    findings: list[dict[str, Any]] | None = None,
) -> None:
    """
    Persist the tenant state and email the project's admins on meaningful transitions:
    sending paused, sending re-enabled, or reputation findings escalating. The stored state is
    the dedupe mechanism — the row is locked for the read-compare-write so overlapping syncs
    (webhook + sweep, or duplicate events) serialize, and the loser sees an unchanged state.
    """
    impact = reputation_impact or ""
    if impact and impact not in _IMPACT_SEVERITY:
        logger.warning("Unknown SES reputation impact", team_id=team_id, impact=impact)
    TeamWorkflowsConfig.objects.get_or_create(team_id=team_id)

    with transaction.atomic():
        config = TeamWorkflowsConfig.objects.select_for_update().get(team_id=team_id)
        previous_status = config.ses_tenant_sending_status
        previous_impact = config.ses_tenant_reputation_impact
        if previous_status == sending_status and previous_impact == impact:
            config.ses_tenant_state_synced_at = timezone.now()
            config.save(update_fields=["ses_tenant_state_synced_at"])
            # Without this, a sync that found nothing and a sync that never ran look the same.
            logger.info("SES tenant state unchanged", team_id=team_id, status=sending_status, impact=impact)
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

        # The send path caches this row for a couple of minutes, so without this a pause keeps
        # sending and a reinstatement keeps blocking until the entry expires. After commit, so the
        # worker cannot re-read the row before the new state is visible and cache it again.
        transaction.on_commit(lambda: _announce_state_change(team_id))

        notify = _pick_notification(
            previous_status=previous_status,
            previous_impact=previous_impact,
            sending_status=sending_status,
            impact=impact,
            team_id=team_id,
            now_iso=now.isoformat(),
            findings=_findings_for_email(findings),
            staff_suspended=config.email_sending_suspended_at is not None,
        )
        if notify is not None:
            # Dispatch after commit so a rollback can't leave an email claiming a state
            # that was never persisted.
            transaction.on_commit(notify)


def _findings_for_email(findings: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    """
    What the provider flagged, in our words, worst first, trimmed to what fits an email. Carrying
    it in the message keeps the email useful on its own: the Reputation tab is flag-gated, so a
    recipient may not be able to open the link at all.
    """
    if not findings:
        return []
    # AWS can raise several recommendations of one type (DKIM for each domain, say), which would
    # render as repeated identical lines now that the wording comes from the type. Keep the worst.
    impact_by_type: dict[str, str] = {}
    for finding in findings:
        finding_type = str(finding.get("finding_type") or "")
        if finding_type not in _FINDING_DESCRIPTIONS:
            logger.warning("Omitting SES finding of unknown type from email", finding_type=finding_type)
            continue
        impact = str(finding.get("impact") or "")
        known = impact_by_type.get(finding_type)
        if known is None or _IMPACT_SEVERITY.get(impact, 0) > _IMPACT_SEVERITY.get(known, 0):
            impact_by_type[finding_type] = impact
    ordered = sorted(impact_by_type.items(), key=lambda item: _IMPACT_SEVERITY.get(item[1], 0), reverse=True)
    return [
        {"impact": impact, "description": _FINDING_DESCRIPTIONS[finding_type]}
        for finding_type, impact in ordered[:_MAX_FINDINGS_IN_EMAIL]
    ]


def _pick_notification(
    *,
    previous_status: str,
    previous_impact: str,
    sending_status: str,
    impact: str,
    team_id: int,
    now_iso: str,
    findings: list[dict[str, str]],
    staff_suspended: bool,
) -> Callable[[], None] | None:
    pause_reason = PROVIDER_PAUSE_REASON if impact == "HIGH" else PROVIDER_PAUSE_REASON_UNSPECIFIED

    if previous_status == "":
        # First sync is baseline adoption, not a transition — healthy teams stay silent so
        # rollout doesn't mass-email. But a tenant that is ALREADY paused or already carries
        # high-impact findings is exactly who this feature exists to tell, so those do notify.
        if sending_status == "DISABLED":
            return lambda: send_email_sending_suspended.delay(team_id, pause_reason, now_iso)
        if impact == "HIGH":
            return lambda: send_email_sending_reputation_finding.delay(team_id, impact, now_iso, findings)
        return None

    if sending_status == "DISABLED" and previous_status != "DISABLED":
        return lambda: send_email_sending_suspended.delay(team_id, pause_reason, now_iso)
    if previous_status == "DISABLED" and sending_status in ("ENABLED", "REINSTATED"):
        if staff_suspended:
            # The staff kill switch (email_sending_suspended_at) still blocks delivery, so
            # sending is not actually restored — a "re-enabled" email would contradict it. The
            # admin unsuspend action sends its own re-enabled email when that switch clears.
            return None
        return lambda: send_email_sending_unsuspended.delay(team_id, now_iso)
    if sending_status != "DISABLED" and _IMPACT_SEVERITY.get(impact, 0) > _IMPACT_SEVERITY.get(previous_impact, 0):
        # Escalation only, and only while still sending — a paused tenant already got the
        # suspension email, and de-escalations don't need action.
        return lambda: send_email_sending_reputation_finding.delay(team_id, impact, now_iso, findings)
    return None
