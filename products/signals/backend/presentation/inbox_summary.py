from dataclasses import asdict

from drf_spectacular.utils import extend_schema, extend_schema_serializer
from rest_framework import serializers, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.permissions import APIScopePermission, is_service_auth

from products.signals.backend.facade import api as signals_facade


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

    @extend_schema(responses=InboxSummarySerializer)
    def list(self, request: Request, **kwargs: object) -> Response:
        summary = signals_facade.get_inbox_summary(
            team_id=self.team_id,
            user=request.user,
            service_auth=is_service_auth(request),
        )
        return Response(InboxSummarySerializer(asdict(summary)).data)
