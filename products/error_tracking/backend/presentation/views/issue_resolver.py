from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action

from products.error_tracking.backend.facade import api as facade_api
from products.error_tracking.backend.presentation.views.issues import ErrorTrackingIssueReadSerializer


class ErrorTrackingIssueResolveQuerySerializer(serializers.Serializer):
    identifier = serializers.CharField(
        allow_blank=False,
        help_text="Exact error fingerprint to resolve. If no fingerprint matches, a UUID is treated as a legacy issue ID.",
    )


class ErrorTrackingIssueResolveResponseSerializer(ErrorTrackingIssueReadSerializer):
    matched_by = serializers.ChoiceField(
        choices=["fingerprint", "issue_id"],
        help_text="Whether the identifier matched an exact fingerprint or fell back to a legacy issue ID.",
    )


class ErrorTrackingIssueResolverViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "error_tracking"
    scope_object_read_actions = ["resolve"]
    serializer_class = ErrorTrackingIssueResolveResponseSerializer
    pagination_class = None

    @validated_request(
        query_serializer=ErrorTrackingIssueResolveQuerySerializer,
        responses={
            200: OpenApiResponse(response=ErrorTrackingIssueResolveResponseSerializer),
            404: OpenApiResponse(description="No issue matches the fingerprint or legacy issue ID."),
        },
        operation_id="error_tracking_issues_resolve_retrieve",
        summary="Resolve an error tracking issue identifier",
        description="Resolve an exact fingerprint to its current issue, falling back to a legacy issue UUID only when no fingerprint matches.",
    )
    @action(methods=["GET"], detail=False, url_path="resolve", required_scopes=["error_tracking:read"])
    def resolve(self, request: ValidatedRequest, *args: object, **kwargs: object) -> Response:
        try:
            issue, matched_by = facade_api.resolve_issue_identifier(
                team_id=self.team.id,
                identifier=request.validated_query_data["identifier"],
            )
        except facade_api.IssueNotFoundError:
            raise NotFound("Issue not found")

        response_data = ErrorTrackingIssueReadSerializer(issue).data
        response_data["matched_by"] = matched_by
        return Response(response_data)
