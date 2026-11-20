from typing import cast

from drf_spectacular.utils import OpenApiResponse, extend_schema_serializer
from rest_framework import exceptions, serializers, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle

from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.auth import OAuthAccessTokenAuthentication, PersonalAPIKeyAuthentication, SessionAuthentication
from posthog.models import User
from posthog.oauth_provenance import is_sandbox_origin_request
from posthog.permissions import APIScopePermission

from products.signals.backend.facade.monitor_pr import (
    REPORT_STATUS_CHOICES,
    InvalidPullRequest,
    PRMonitoringLimitExceeded,
    PRMonitoringUnavailable,
    request_pr_monitoring,
)
from products.signals.backend.presentation.scout_permissions import ScoutCanonicalTeamAccessPermission


class MonitorPRBurstThrottle(UserRateThrottle):
    scope = "signals_monitor_pr"
    rate = "10/minute"


class MonitorPRRequestSerializer(serializers.Serializer):
    pr_url = serializers.URLField(
        max_length=500,
        help_text="GitHub pull request URL. The project must have a GitHub integration with access to its repository. Open and merged PRs are supported, regardless of author.",
    )
    note = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
        max_length=4000,
        help_text="Optional context about what the person wants monitored, such as a conversion, error rate, or affected audience. Omit when the research agent should identify the key metric from the PR and project data.",
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
        help_text="True when this person already requested monitoring for this PR in this project. The original note is retained."
    )


class MonitorPRUnavailableSerializer(serializers.Serializer):
    detail = serializers.CharField(help_text="Why PR research could not start and whether to retry.")
    report_id = serializers.UUIDField(
        required=False, help_text="The saved report, if creation succeeded before dispatch failed."
    )


class MonitorPRViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    serializer_class = MonitorPRResponseSerializer
    authentication_classes = [SessionAuthentication, PersonalAPIKeyAuthentication, OAuthAccessTokenAuthentication]
    permission_classes = [IsAuthenticated, APIScopePermission, ScoutCanonicalTeamAccessPermission]
    scope_object = "inbox"
    required_scopes = ["inbox:write", "task:write", "query:read", "event_definition:read"]
    requires_resource_level_access = True
    pagination_class = None
    throttle_classes = [MonitorPRBurstThrottle]

    @validated_request(
        request_serializer=MonitorPRRequestSerializer,
        responses={
            200: OpenApiResponse(response=MonitorPRResponseSerializer, description="Existing monitoring request"),
            202: OpenApiResponse(response=MonitorPRResponseSerializer, description="PR research accepted"),
            503: OpenApiResponse(
                response=MonitorPRUnavailableSerializer, description="PR research temporarily unavailable"
            ),
        },
        summary="Monitor a pull request",
    )
    def create(self, request, **kwargs):
        user = cast(User, request.user)
        if is_sandbox_origin_request(request):
            raise exceptions.PermissionDenied("Start PR monitoring from a person’s session or API credential.")
        try:
            result = request_pr_monitoring(
                team=self.team,
                user=user,
                pr_url=request.validated_data["pr_url"],
                note=request.validated_data["note"],
            )
        except InvalidPullRequest as error:
            raise exceptions.ValidationError({"pr_url": str(error)}) from error
        except PermissionError as error:
            raise exceptions.PermissionDenied(str(error)) from error
        except PRMonitoringLimitExceeded as error:
            raise exceptions.Throttled(detail=str(error), wait=error.retry_after) from error
        except PRMonitoringUnavailable as error:
            return Response(
                {"detail": str(error), **({"report_id": str(error.report_id)} if error.report_id else {})},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return Response(
            MonitorPRResponseSerializer(result).data,
            status=status.HTTP_200_OK if result.idempotent_replay else status.HTTP_202_ACCEPTED,
        )
