from rest_framework import serializers

from posthog.models import Team, User
from posthog.user_permissions import UserPermissions

from products.signals.backend.models import SignalReport
from products.signals.backend.report_access import may_read_reports


class ReportLocationQuerySerializer(serializers.Serializer):
    report_id = serializers.UUIDField(help_text="The report to find.")


class ReportLocationResponseSerializer(serializers.Serializer):
    team_id = serializers.IntegerField(
        allow_null=True,
        help_text="The project that owns the report, or null when the caller can't read the report in any project.",
    )


def locate_report_team_id(*, user: User, report_id: str) -> int | None:
    """The project of a report that the user can read, in any project they can access."""
    visible_team_ids = UserPermissions(user).team_ids_visible_for_user
    team_id = (
        SignalReport.objects.filter(id=report_id, team_id__in=visible_team_ids)
        .exclude(status=SignalReport.Status.DELETED)
        .values_list("team_id", flat=True)
        .first()
    )
    if team_id is None:
        return None
    if not may_read_reports(user=user, team=Team.objects.get(pk=team_id)):
        return None
    return team_id
