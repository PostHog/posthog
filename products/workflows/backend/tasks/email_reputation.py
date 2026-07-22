from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any, Optional

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

import requests
from celery import shared_task
from structlog import get_logger

from posthog.models import Team
from posthog.tasks.email import send_email_reputation_degraded
from posthog.tasks.utils import CeleryQueue

from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    Priority,
    TargetType,
    create_notification,
)
from products.workflows.backend.models.email_reputation import EmailReputationSnapshot
from products.workflows.backend.models.team_workflows_config import TeamWorkflowsConfig

logger = get_logger(__name__)

# The evaluator snapshots daily; two days of lookback pairs each latest snapshot with its
# predecessor even when a run lands late, and a longer gap means the previous state is stale
# enough that re-entering a degraded state deserves a fresh notification anyway.
SNAPSHOT_LOOKBACK = timedelta(days=2)

# The scan runs hourly but each snapshot must produce side effects exactly once; the marker
# outlives any realistic evaluator gap. Emails are additionally deduped via MessagingRecord,
# so a cache eviction can at worst duplicate an in-app notification or Slack message.
PROCESSED_MARKER_TTL_SECONDS = int(timedelta(days=7).total_seconds())

REPUTATION_TAB_PATH = "/workflows/reputation"


def _processed_marker_key(team_id: int, evaluated_at: datetime) -> str:
    return f"email_reputation_transitions:{team_id}:{evaluated_at.isoformat()}"


@shared_task(ignore_result=True, queue=CeleryQueue.DEFAULT.value)
def check_email_reputation_transitions() -> None:
    """
    Notify on team email reputation state transitions.

    Compares each team's two most recent team-scope snapshots (written daily by the Node
    Temporal evaluator): entering ``warning`` notifies the customer (email + in-app);
    entering ``critical`` additionally alerts us on Slack, and Slack keeps firing on every
    new critical snapshot until the team is suspended or recovers — that nag is the manual
    enforcement queue.
    """
    now = timezone.now()
    # Cross-team by design: this scan covers every sending team, hence unscoped().
    rows = (
        EmailReputationSnapshot.objects.unscoped()
        .filter(scope=EmailReputationSnapshot.Scope.TEAM, evaluated_at__gte=now - SNAPSHOT_LOOKBACK)
        .order_by("team_id", "-evaluated_at")
        .values("team_id", "state", "bounce_rate", "complaint_rate", "emails_sent", "evaluated_at")
    )

    snapshots_by_team: dict[int, list[Mapping[str, Any]]] = {}
    for row in rows:
        team_rows = snapshots_by_team.setdefault(row["team_id"], [])
        if len(team_rows) < 2:
            team_rows.append(row)

    degraded_team_ids = [
        team_id
        for team_id, team_rows in snapshots_by_team.items()
        if team_rows[0]["state"] in (EmailReputationSnapshot.State.WARNING, EmailReputationSnapshot.State.CRITICAL)
    ]
    if not degraded_team_ids:
        return

    teams_by_id = {team.id: team for team in Team.objects.filter(id__in=degraded_team_ids)}
    suspended_team_ids = set(
        TeamWorkflowsConfig.objects.filter(
            team_id__in=degraded_team_ids, email_sending_suspended_at__isnull=False
        ).values_list("team_id", flat=True)
    )

    for team_id in degraded_team_ids:
        team = teams_by_id.get(team_id)
        if not team:
            continue
        latest = snapshots_by_team[team_id][0]
        previous = snapshots_by_team[team_id][1] if len(snapshots_by_team[team_id]) > 1 else None
        marker_key = _processed_marker_key(team_id, latest["evaluated_at"])
        if cache.get(marker_key):
            continue
        try:
            _process_team_transition(team, latest, previous, suspended=team_id in suspended_team_ids)
        except Exception:
            # Per-team isolation: one team failing must not starve the rest of the scan.
            logger.exception("Failed to process email reputation transition", team_id=team_id)
            continue
        cache.set(marker_key, True, PROCESSED_MARKER_TTL_SECONDS)


def _process_team_transition(
    team: Team, latest: Mapping[str, Any], previous: Optional[Mapping[str, Any]], suspended: bool
) -> None:
    latest_state = latest["state"]
    previous_state = previous["state"] if previous else None

    if latest_state == EmailReputationSnapshot.State.CRITICAL:
        if previous_state != EmailReputationSnapshot.State.CRITICAL:
            _notify_customer(team, latest)
        if not suspended:
            _send_slack_critical_alert(team, latest)
    elif latest_state == EmailReputationSnapshot.State.WARNING and previous_state not in (
        EmailReputationSnapshot.State.WARNING,
        EmailReputationSnapshot.State.CRITICAL,
    ):
        _notify_customer(team, latest)


def _notify_customer(team: Team, snapshot: Mapping[str, Any]) -> None:
    is_critical = snapshot["state"] == EmailReputationSnapshot.State.CRITICAL
    send_email_reputation_degraded.delay(
        team_id=team.id,
        state=snapshot["state"],
        bounce_rate=snapshot["bounce_rate"],
        complaint_rate=snapshot["complaint_rate"],
        evaluated_at=snapshot["evaluated_at"].isoformat(),
    )
    create_notification(
        NotificationData(
            team_id=team.id,
            notification_type=NotificationType.EMAIL_REPUTATION,
            priority=Priority.CRITICAL if is_critical else Priority.NORMAL,
            title=(
                "Email sending is at risk of suspension" if is_critical else "Your email reputation needs attention"
            ),
            body=(
                f"Your recent hard bounce rate is {snapshot['bounce_rate']:.2%} and spam complaint rate is "
                f"{snapshot['complaint_rate']:.2%}. Check the Reputation tab to find the workflow responsible."
            ),
            target_type=TargetType.TEAM,
            target_id=str(team.id),
            source_url=REPUTATION_TAB_PATH,
        )
    )


def _send_slack_critical_alert(team: Team, snapshot: Mapping[str, Any]) -> None:
    webhook_url = settings.EMAIL_REPUTATION_SLACK_WEBHOOK_URL
    if not webhook_url:
        logger.warning("No Slack webhook configured for email reputation alerts", team_id=team.id)
        return

    admin_url = f"{settings.SITE_URL}/admin/posthog/team/{team.id}/change/"
    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f":rotating_light: *Email reputation critical* for team `{team.id}` ({team.name})\n"
                    f"Hard bounce rate: *{snapshot['bounce_rate']:.2%}* · "
                    f"Complaint rate: *{snapshot['complaint_rate']:.2%}* · "
                    f"Emails evaluated: *{snapshot['emails_sent']}*\n"
                    f"Evaluated at {snapshot['evaluated_at'].isoformat()} — sending is NOT suspended yet.\n"
                    f"<{admin_url}|Review and suspend in Django admin>"
                ),
            },
        }
    ]
    response = requests.post(webhook_url, json={"blocks": blocks}, timeout=10)
    response.raise_for_status()
