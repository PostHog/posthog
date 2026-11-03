from __future__ import annotations

from django.db.models import Q

import posthoganalytics

from posthog.exceptions_capture import capture_exception
from posthog.models import Team, User

from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    TargetType,
    create_notification,
)
from products.signals.backend.first_report_experiment import first_report_outcome_properties
from products.signals.backend.models import SignalFirstReportNotification, SignalScoutRun, SignalTeamConfig
from products.signals.backend.report_access import may_read_reports


def first_report_completion_notifications_enabled(team: Team, user: User) -> bool:
    disabled = (user.partial_notification_settings or {}).get("realtime_notifications_disabled") or {}
    if (disabled.get(NotificationType.FIRST_REPORT_COMPLETED.value) or {}).get(str(team.id)):
        return False
    try:
        return bool(
            posthoganalytics.feature_enabled(
                "real-time-notifications",
                str(team.organization_id),
                groups={"organization": str(team.organization_id)},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        )
    except Exception as error:
        capture_exception(error)
        return False


def complete_first_report_investigation(team_id: int, run_id: str) -> dict[str, str | float | bool | None]:
    properties = first_report_outcome_properties(team_id, run_id)
    try:
        run = SignalScoutRun.objects.for_team(team_id).select_related("team").get(id=run_id)
        onboarding = SignalTeamConfig.objects.filter(team_id=team_id).values_list("onboarding", flat=True).first() or {}
        activation = (
            SignalFirstReportNotification.objects.for_team(onboarding.get("first_report_activation_team_id", team_id))
            .filter(Q(team_id=team_id) | Q(team__parent_team_id=team_id))
            .select_related("team", "activated_by")
            .first()
        )
        if activation is None:
            return properties
        user = activation.activated_by
        if (
            user is None
            or not user.is_active
            or not may_read_reports(user=user, team=run.team)
            or not may_read_reports(user=user, team=activation.team)
        ):
            return properties
        outcome = properties.get("first_report_outcome")
        messages = {
            "report_created": (
                "Your first report is ready",
                "Open Self-Driving to see the finding and its next steps.",
            ),
            "insufficient_data": (
                "Your first investigation needs more data",
                "Open Self-Driving to see what data is missing.",
            ),
            "no_actionable_finding": (
                "Your first investigation is complete",
                "We checked your data and didn’t find anything worth reporting yet.",
            ),
            "incomplete": (
                "Your first investigation couldn’t finish",
                "Open Self-Driving to review the investigation.",
            ),
        }
        title, body = messages.get(str(outcome), messages["incomplete"])
        create_notification(
            NotificationData(
                team_id=activation.team_id,
                notification_type=NotificationType.FIRST_REPORT_COMPLETED,
                title=title,
                body=body,
                target_type=TargetType.USER,
                target_id=str(user.pk),
                source_url=f"/project/{team_id}/inbox",
                idempotency_key=f"first-report:{run_id}",
            )
        )
    except Exception as error:
        capture_exception(error)
    return properties
