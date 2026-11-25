from typing import Any, cast

from drf_spectacular.utils import OpenApiResponse, extend_schema_serializer
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from posthog.api.integration import github_rate_limited_response
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.egress.github.transport import GitHubRateLimitError
from posthog.egress.transport.transport import EgressBudgetExhausted
from posthog.models import User
from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.oauth_provenance import is_sandbox_origin_request
from posthog.permissions import APIScopePermission, get_authenticator_scopes

from products.signals.backend.facade.monitor_pr import (
    REPORT_STATUS_CHOICES,
    InvalidPullRequest,
    PRMonitoringLimitExceeded,
    PRMonitoringUnavailable,
    PRState,
    list_authored_prs,
    request_pr_monitoring,
)
from products.signals.backend.presentation.scout_permissions import ScoutCanonicalTeamAccessPermission


class MonitorPRBurstThrottle(UserRateThrottle):
    scope = "signals_monitor_pr"
    rate = "10/minute"


class MonitorPRRequestSerializer(serializers.Serializer):
    pr_url = serializers.URLField(
        max_length=500,
        help_text="GitHub pull request URL for a branch in a repository connected to this project's GitHub integration. Open, draft, and merged PRs within the last 90 days are supported.",
    )
    note = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=4000,
        help_text="Optional team-visible steering context about what to monitor, such as a conversion step, error rate, or affected audience. Omit when the research agent should identify the key metric from the pull request and project data.",
    )


@extend_schema_serializer(many=False)
class MonitorPRResponseSerializer(serializers.Serializer):
    report_id = serializers.UUIDField(help_text="The report assigned to the person who requested monitoring.")
    report_url = serializers.URLField(help_text="Open the report to follow research and monitoring.")
    status = serializers.ChoiceField(
        choices=REPORT_STATUS_CHOICES,
        help_text="Current report status. Research runs asynchronously; monitoring starts after research and PR merge.",
    )
    idempotent_replay = serializers.BooleanField(
        help_text="True when this person already requested monitoring for this PR in this project."
    )


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
    monitoring_disabled_reason = serializers.CharField(
        allow_null=True,
        required=False,
        default=None,
        help_text="Why monitoring or retrying is unavailable for this pull request, or null when eligible.",
    )


@extend_schema_serializer(many=False)
class PRBrowserPageSerializer(serializers.Serializer):
    results = PRBrowserItemSerializer(
        many=True, help_text="Recent authored pull requests ordered by creation time, newest first."
    )
    github_login = serializers.CharField(
        allow_null=True, help_text="The caller’s connected GitHub identity, or null if not connected."
    )
    has_integration = serializers.BooleanField(help_text="Whether the project has a GitHub installation.")


class _BasePRViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission, ScoutCanonicalTeamAccessPermission]
    scope_object = "inbox"
    pagination_class = None

    def initial(self, request: Any, *args: Any, **kwargs: Any) -> None:
        super().initial(request, *args, **kwargs)
        if is_sandbox_origin_request(request):
            raise exceptions.PermissionDenied("Use a person’s session or API credential for pull request monitoring.")

    def handle_exception(self, exc: Exception) -> Response:
        if isinstance(exc, PermissionError):
            exc = exceptions.PermissionDenied(str(exc))
        elif isinstance(exc, PRMonitoringLimitExceeded):
            exc = exceptions.Throttled(detail=str(exc), wait=exc.retry_after)
        elif isinstance(exc, PRMonitoringUnavailable):
            payload = {"detail": str(exc), **({"report_id": str(exc.report_id)} if exc.report_id else {})}
            return Response(payload, status=status.HTTP_503_SERVICE_UNAVAILABLE)
        elif isinstance(exc, GitHubRateLimitError):
            return github_rate_limited_response(exc)
        elif isinstance(exc, (GitHubIntegrationError, EgressBudgetExhausted)):
            return Response(
                {"detail": "GitHub is temporarily unavailable. Try again shortly."},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return super().handle_exception(exc)


class MonitorPRViewSet(_BasePRViewSet):
    serializer_class = MonitorPRResponseSerializer
    required_scopes = ["inbox:write", "task:write", "query:read", "event_definition:read"]
    throttle_classes = [MonitorPRBurstThrottle]

    @validated_request(
        request_serializer=MonitorPRRequestSerializer,
        responses={
            200: OpenApiResponse(response=MonitorPRResponseSerializer, description="Existing monitoring request"),
            202: OpenApiResponse(response=MonitorPRResponseSerializer, description="PR research accepted"),
        },
        summary="Monitor a pull request",
    )
    def create(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        scopes = get_authenticator_scopes(request.successful_authenticator)
        try:
            result = request_pr_monitoring(
                team=self.team,
                user=cast(User, request.user),
                pr_url=request.validated_data["pr_url"],
                note=request.validated_data["note"],
                token_scopes=tuple(scopes) if scopes is not None else None,
            )
        except InvalidPullRequest as error:
            raise exceptions.ValidationError({"pr_url": str(error)}) from error
        return Response(
            MonitorPRResponseSerializer(result).data,
            status=status.HTTP_200_OK if result.idempotent_replay else status.HTTP_202_ACCEPTED,
        )


class PRBrowserViewSet(_BasePRViewSet):
    serializer_class = PRBrowserPageSerializer

    @validated_request(
        responses={200: PRBrowserPageSerializer},
        summary="List recent authored pull requests",
    )
    def list(self, request: ValidatedRequest, **kwargs: Any) -> Response:
        page = list_authored_prs(team=self.team, user=cast(User, request.user))
        return Response(PRBrowserPageSerializer(page).data)
