from django.db import transaction
from django.utils import timezone

from rest_framework import serializers

from products.signals.backend.models import SignalReportAction


class ReportReadStateRequestSerializer(serializers.Serializer):
    report_ids = serializers.ListField(
        child=serializers.UUIDField(),
        max_length=100,
        allow_empty=False,
        help_text="Reports to read or update, limited to the current project.",
    )
    read = serializers.BooleanField(
        required=False,
        help_text="Set these reports read or unread for the current user. Omit to read their state.",
    )


class ReportReadStateResponseSerializer(serializers.Serializer):
    states = serializers.DictField(child=serializers.BooleanField(), help_text="Read state keyed by report UUID.")


def report_read_states(team_id: int, user_id: int, report_ids: list[str], read: bool | None) -> dict[str, bool]:
    rows = SignalReportAction.objects.for_team(team_id).filter(
        report_id__in=report_ids,
        user_id=user_id,
        type=SignalReportAction.ActionType.READ,
    )
    if read is not None:
        now = timezone.now()
        with transaction.atomic():
            SignalReportAction.objects.for_team(team_id).bulk_create(
                [
                    SignalReportAction(
                        team_id=team_id,
                        report_id=report_id,
                        user_id=user_id,
                        type=SignalReportAction.ActionType.READ,
                        metadata={"read": read},
                        last_at=now,
                    )
                    for report_id in report_ids
                ],
                update_conflicts=True,
                unique_fields=["report", "user", "type"],
                update_fields=["metadata", "last_at"],
            )
    saved = {str(row.report_id): row.metadata.get("read") is True for row in rows}
    return {report_id: saved.get(report_id, False) for report_id in report_ids}
