from typing import Any, cast

from drf_spectacular.utils import extend_schema_serializer
from rest_framework import exceptions, serializers, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.egress.github.transport import GitHubRateLimitError
from posthog.egress.transport.transport import EgressBudgetExhausted
from posthog.models import User
from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.permissions import APIScopePermission

from products.signals.backend.facade.monitor_pr import REPORT_STATUS_CHOICES
from products.signals.backend.facade.pr_browser import (
    InvalidPullRequest,
    PRBrowserMonitoringFilter,
    PRState,
    get_pr_overview,
    list_authored_prs,
)
from products.signals.backend.presentation.scout_permissions import ScoutCanonicalTeamAccessPermission


class PRBrowserReportSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="Monitoring report assigned to the caller.")
    status = serializers.ChoiceField(
        choices=REPORT_STATUS_CHOICES, help_text="Current report status, including research and waiting for merge."
    )


class PRBrowserItemSerializer(serializers.Serializer):
    url = serializers.URLField(help_text="GitHub URL.")
    repository = serializers.CharField(help_text="Repository registered with this project, in owner/name format.")
    number = serializers.IntegerField(help_text="GitHub pull request number.")
    title = serializers.CharField(help_text="Pull request title.")
    state = serializers.ChoiceField(choices=PRState.choices, help_text="Current GitHub pull request state.")
    draft = serializers.BooleanField(help_text="Whether this is a draft pull request.")
    author = serializers.CharField(help_text="GitHub login of the author.")
    created_at = serializers.DateTimeField(help_text="When the PR was opened.")
    updated_at = serializers.DateTimeField(help_text="When GitHub last updated the PR.")
    report = PRBrowserReportSerializer(
        allow_null=True, help_text="The caller’s monitoring report, or null when not requested."
    )


@extend_schema_serializer(many=False)
class PRBrowserPageSerializer(serializers.Serializer):
    results = PRBrowserItemSerializer(
        many=True, help_text="Authored pull requests ordered by creation time, newest first."
    )
    next_cursor = serializers.CharField(
        allow_null=True, help_text="Opaque continuation cursor, or null at the end of the available history."
    )
    github_login = serializers.CharField(
        allow_null=True, help_text="The caller’s connected GitHub identity, or null if not connected."
    )
    has_integration = serializers.BooleanField(help_text="Whether the project has a GitHub installation.")
    incomplete = serializers.BooleanField(
        help_text="Whether GitHub returned incomplete results or its search history limit was reached."
    )


class PRBrowserQuerySerializer(serializers.Serializer):
    monitoring = serializers.ChoiceField(
        choices=PRBrowserMonitoringFilter.choices,
        default="all",
        help_text="Filter by whether the caller has requested monitoring, including research and waiting for merge.",
    )
    cursor = serializers.CharField(
        required=False,
        default="",
        max_length=8000,
        help_text="Continuation cursor from the previous page, bound to this user, project and filter.",
    )


class PRBrowserOverviewQuerySerializer(serializers.Serializer):
    pr_url = serializers.URLField(
        max_length=500, help_text="URL of a pull request in a repository registered with the project."
    )


class PRBrowserCheckSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="GitHub check name.")
    status = serializers.CharField(help_text="Current GitHub check status, such as queued, in_progress or completed.")
    conclusion = serializers.CharField(allow_null=True, help_text="Check conclusion when finished, otherwise null.")
    url = serializers.URLField(allow_null=True, help_text="GitHub URL.")


class PRBrowserOverviewSerializer(serializers.Serializer):
    pull_request = PRBrowserItemSerializer(help_text="Current PR metadata and the caller’s monitoring report.")
    body = serializers.CharField(help_text="Pull request description in Markdown.")
    head_branch = serializers.CharField(help_text="Source branch.")
    base_branch = serializers.CharField(help_text="Target branch.")
    additions = serializers.IntegerField(help_text="Lines added.")
    deletions = serializers.IntegerField(help_text="Lines deleted.")
    changed_files = serializers.IntegerField(help_text="Number of changed files.")
    checks = PRBrowserCheckSerializer(many=True, help_text="Checks and commit statuses for the PR head.")
    checks_available = serializers.BooleanField(
        help_text="False when CI checks could not be read through this installation."
    )
    has_conflicts = serializers.BooleanField(help_text="Whether GitHub reports merge conflicts.")


class PRBrowserUnavailableSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Why the GitHub request could not complete.")


class PRBrowserViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    serializer_class = PRBrowserPageSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission, ScoutCanonicalTeamAccessPermission]
    scope_object = "inbox"
    requires_resource_level_access = True
    pagination_class = None

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, InvalidPullRequest):
            exc = exceptions.ValidationError(str(exc))
        elif isinstance(exc, PermissionError):
            exc = exceptions.PermissionDenied(str(exc))
        elif isinstance(exc, (GitHubIntegrationError, GitHubRateLimitError, EgressBudgetExhausted)):
            return Response({"detail": "GitHub is temporarily unavailable. Try again shortly."}, status=503)
        return super().handle_exception(exc)

    @validated_request(
        query_serializer=PRBrowserQuerySerializer,
        responses={200: PRBrowserPageSerializer, 503: PRBrowserUnavailableSerializer},
    )
    def list(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        page = list_authored_prs(team=self.team, user=cast(User, request.user), **request.validated_query_data)
        return Response(PRBrowserPageSerializer(page).data)

    @validated_request(
        query_serializer=PRBrowserOverviewQuerySerializer,
        responses={200: PRBrowserOverviewSerializer, 503: PRBrowserUnavailableSerializer},
    )
    @action(detail=False, methods=["GET"])
    def overview(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        overview = get_pr_overview(team=self.team, user=cast(User, request.user), **request.validated_query_data)
        return Response(PRBrowserOverviewSerializer(overview).data)
