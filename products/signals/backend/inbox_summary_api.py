from django.db.models import QuerySet
from django.utils import timezone

from drf_spectacular.utils import extend_schema, extend_schema_serializer
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.permissions import APIScopePermission, is_service_auth

from products.signals.backend.artefact_schemas import TASK_RUN_TYPE_IMPLEMENTATION
from products.signals.backend.inbox_summary import INBOX_SUMMARY_PERIOD, generated_pull_requests
from products.signals.backend.models import SignalReportPullRequest, SignalReportTask
from products.tasks.backend.facade import api as tasks_facade


class InboxSummaryPullRequestSerializer(serializers.Serializer):
    repository = serializers.CharField(help_text="GitHub repository in owner/name format.")
    number = serializers.IntegerField(help_text="GitHub pull request number.")
    url = serializers.URLField(help_text="URL of the GitHub pull request.")


class InboxSummaryPersonSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="Stable GitHub user ID.")
    login = serializers.CharField(help_text="Current GitHub login from the participant snapshot.")


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
    pull_requests = InboxSummaryPullRequestSerializer(
        many=True, help_text="Verified Self-driving implementation PRs merged in the period."
    )
    people = InboxSummaryPersonSerializer(
        many=True,
        allow_null=True,
        help_text="Distinct human approvers and mergers, or null while participation is incomplete.",
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
        if is_service_auth(self.request):
            return generated_pull_requests(self.team_id)
        candidate_task_ids = list(
            SignalReportTask.objects.filter(
                team_id=self.team_id, relationship=TASK_RUN_TYPE_IMPLEMENTATION
            ).values_list("task_id", flat=True)
        )
        accessible_task_ids = tasks_facade.filter_accessible_task_ids(
            team_id=self.team_id, user=self.request.user, task_ids=candidate_task_ids
        )
        return generated_pull_requests(self.team_id, task_ids=accessible_task_ids)

    @extend_schema(responses=InboxSummarySerializer)
    def list(self, request: Request, **kwargs: object) -> Response:
        period_end = timezone.now()
        period_start = period_end - INBOX_SUMMARY_PERIOD
        rows = (
            self.get_queryset()
            .filter(state="merged", merged_at__gte=period_start, merged_at__lt=period_end)
            .values(
                "number",
                "participant_ids",
                "participant_logins",
                "participants_synced_at",
                "repository",
                "url",
            )
            .order_by("-merged_at", "repository", "number")
        )
        participation_complete = True
        people_by_id: dict[int, str] = {}
        pull_requests: list[dict[str, object]] = []
        for row in rows.iterator():
            pull_requests.append({"repository": row["repository"], "number": row["number"], "url": row["url"]})
            participant_ids = row["participant_ids"]
            participant_logins = row["participant_logins"]
            if (
                participant_ids is None
                or participant_logins is None
                or row["participants_synced_at"] is None
                or len(participant_ids) != len(participant_logins)
            ):
                participation_complete = False
            else:
                for participant_id, login in zip(participant_ids, participant_logins, strict=True):
                    people_by_id.setdefault(participant_id, login)
        people = [
            {"id": participant_id, "login": login}
            for participant_id, login in sorted(people_by_id.items(), key=lambda item: (item[1].lower(), item[0]))
        ]
        return Response(
            InboxSummarySerializer(
                {
                    "period_start": period_start,
                    "period_end": period_end,
                    "merged_pr_count": len(pull_requests),
                    "people_count": len(people) if participation_complete else None,
                    "participation_complete": participation_complete,
                    "pull_requests": pull_requests,
                    "people": people if participation_complete else None,
                }
            ).data
        )
