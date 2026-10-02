from django.db.models import QuerySet
from django.utils import timezone

from drf_spectacular.utils import extend_schema, extend_schema_serializer
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.permissions import APIScopePermission

from products.signals.backend.inbox_summary import INBOX_SUMMARY_PERIOD, generated_pull_requests
from products.signals.backend.models import SignalReportPullRequest


@extend_schema_serializer(many=False)
class InboxSummarySerializer(serializers.Serializer):
    period_start = serializers.DateTimeField(help_text="Inclusive start of the rolling seven-day period.")
    period_end = serializers.DateTimeField(help_text="Exclusive end of the rolling seven-day period.")
    merged_pr_count = serializers.IntegerField(
        help_text="Distinct verified Self-driving implementation PRs merged in the period."
    )
    people_count = serializers.IntegerField(
        allow_null=True, help_text="Distinct human approvers and mergers, or null while incomplete."
    )
    participation_complete = serializers.BooleanField(
        help_text="Whether every counted PR has a complete participant snapshot."
    )


class InboxSummaryViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    serializer_class = InboxSummarySerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission]
    scope_object = "task"
    requires_resource_level_access = True
    pagination_class = None
    queryset = SignalReportPullRequest.objects.unscoped()

    def safely_get_queryset(self, queryset: QuerySet) -> QuerySet[SignalReportPullRequest]:
        if getattr(self, "swagger_fake_view", False):
            return SignalReportPullRequest.objects.for_team(0).none()
        return generated_pull_requests(self.team_id)

    @extend_schema(responses=InboxSummarySerializer)
    def list(self, request: Request, **kwargs: object) -> Response:
        period_end = timezone.now()
        period_start = period_end - INBOX_SUMMARY_PERIOD
        rows = (
            self.get_queryset()
            .filter(state="merged", merged_at__gte=period_start, merged_at__lt=period_end)
            .values_list("participant_ids", "participants_synced_at")
        )
        merged_pr_count = 0
        participation_complete = True
        people: set[int] = set()
        for participant_ids, synced_at in rows.iterator():
            merged_pr_count += 1
            if participant_ids is None or synced_at is None:
                participation_complete = False
            else:
                people.update(participant_ids)
        return Response(
            InboxSummarySerializer(
                {
                    "period_start": period_start,
                    "period_end": period_end,
                    "merged_pr_count": merged_pr_count,
                    "people_count": len(people) if participation_complete else None,
                    "participation_complete": participation_complete,
                }
            ).data
        )
