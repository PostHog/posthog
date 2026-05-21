from uuid import UUID

from django.http import JsonResponse

from drf_spectacular.utils import OpenApiResponse
from loginas.utils import is_impersonated_session
from rest_framework import request, serializers, status, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from posthog.schema import ProductKey

from posthog.api.documentation import extend_schema, extend_schema_field
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models.activity_logging.activity_log import load_activity
from posthog.models.activity_logging.activity_page import activity_page_response

from products.error_tracking.backend.facade import (
    api as facade_api,
    types as contracts,
)

from .external_references import ErrorTrackingExternalReferenceSerializer
from .utils import ErrorTrackingIssueAssignmentSerializer

IssueNotFoundError = facade_api.IssueNotFoundError

DEFAULT_EMBEDDING_MODEL_NAME = "text-embedding-3-large"
DEFAULT_EMBEDDING_VERSION = 1
DEFAULT_MIN_DISTANCE_THRESHOLD = 0.10


class ErrorTrackingIssueAssigneeReadSerializer(serializers.Serializer):
    id = serializers.SerializerMethodField()
    type = serializers.CharField()

    @extend_schema_field({"oneOf": [{"type": "integer"}, {"type": "string"}], "nullable": True})
    def get_id(self, assignee: contracts.ErrorTrackingIssueAssignee) -> int | str | None:
        return assignee.id


class ErrorTrackingIssueCohortReadSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class ErrorTrackingIssuePreviewReadSerializer(serializers.Serializer):
    """Read-only serializer for issue preview contract types returned by the facade."""

    id = serializers.UUIDField()
    status = serializers.CharField()
    name = serializers.CharField(allow_null=True)
    description = serializers.CharField(allow_null=True)
    first_seen = serializers.DateTimeField(allow_null=True)
    assignee = ErrorTrackingIssueAssigneeReadSerializer(allow_null=True)


class ErrorTrackingIssueReadSerializer(serializers.Serializer):
    """Read-only serializer for issue contract types returned by the facade."""

    id = serializers.UUIDField()
    status = serializers.CharField()
    name = serializers.CharField(allow_null=True)
    description = serializers.CharField(allow_null=True)
    first_seen = serializers.DateTimeField(allow_null=True)
    assignee = ErrorTrackingIssueAssigneeReadSerializer(allow_null=True)
    external_issues = ErrorTrackingExternalReferenceSerializer(many=True)
    cohort = ErrorTrackingIssueCohortReadSerializer(allow_null=True)


class ErrorTrackingIssuePreviewSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    status = serializers.CharField()
    name = serializers.CharField(allow_null=True)
    description = serializers.CharField(allow_null=True)
    first_seen = serializers.DateTimeField()
    assignee = ErrorTrackingIssueAssignmentSerializer(source="assignment", allow_null=True)


class ErrorTrackingIssueFullSerializer(ErrorTrackingIssueReadSerializer):
    pass


class ErrorTrackingIssueUpdateSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=["archived", "active", "resolved", "pending_release", "suppressed"],
        required=False,
        help_text="Updated issue status.",
    )
    name = serializers.CharField(required=False, allow_null=True, allow_blank=True, help_text="Updated issue name.")
    description = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Updated issue description.",
    )


class ErrorTrackingIssueMergeRequestSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
        help_text="IDs of the issues to merge into the current issue.",
    )


class ErrorTrackingIssueMergeResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField(help_text="Whether the merge completed successfully.")


class ErrorTrackingIssueSplitFingerprintSerializer(serializers.Serializer):
    fingerprint = serializers.CharField(help_text="Fingerprint to split into a new issue.")
    name = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional name for the new issue created from this fingerprint.",
    )
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional description for the new issue created from this fingerprint.",
    )


class ErrorTrackingIssueSplitRequestSerializer(serializers.Serializer):
    fingerprints = serializers.ListField(
        child=ErrorTrackingIssueSplitFingerprintSerializer(),
        required=False,
        default=list,
        help_text="Fingerprints to split into new issues. Each fingerprint becomes its own new issue.",
    )


class ErrorTrackingIssueSplitResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField(help_text="Whether the split completed successfully.")
    new_issue_ids = serializers.ListField(
        child=serializers.UUIDField(),
        help_text="IDs of the new issues created by the split.",
    )


@extend_schema(tags=[ProductKey.ERROR_TRACKING])
class ErrorTrackingIssueViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.GenericViewSet):
    scope_object = "error_tracking"
    # These override the base defaults, so keep the standard DRF actions too.
    scope_object_read_actions = ["list", "retrieve", "values", "exists"]
    scope_object_write_actions = [
        "create",
        "update",
        "partial_update",
        "patch",
        "destroy",
        "merge",
        "split",
        "assign",
        "cohort",
        "bulk",
    ]
    serializer_class = ErrorTrackingIssueFullSerializer

    def list(self, request, *args, **kwargs):
        issues = facade_api.list_issues(team_id=self.team.id)

        page = self.paginate_queryset(issues)
        if page is not None:
            serializer = ErrorTrackingIssuePreviewReadSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = ErrorTrackingIssuePreviewReadSerializer(issues, many=True)
        return Response(serializer.data)

    @action(methods=["GET"], detail=False)
    def exists(self, request, **kwargs):
        return Response({"exists": facade_api.issue_exists(team_id=self.team.id)})

    def retrieve(self, request, *args, **kwargs):
        issue_id = UUID(str(kwargs["pk"]))
        fingerprint = self.request.GET.get("fingerprint")

        if fingerprint:
            resolved_id = facade_api.get_issue_id_for_fingerprint(team_id=self.team.id, fingerprint=fingerprint)
            if resolved_id and resolved_id != issue_id:
                return JsonResponse({"issue_id": resolved_id}, status=status.HTTP_308_PERMANENT_REDIRECT)

        try:
            issue = facade_api.get_issue(issue_id=issue_id, team_id=self.team.id)
        except IssueNotFoundError:
            raise NotFound("Issue not found")

        serializer = ErrorTrackingIssueReadSerializer(issue)
        return Response(serializer.data)

    @validated_request(
        request_serializer=ErrorTrackingIssueUpdateSerializer, responses={200: ErrorTrackingIssueReadSerializer}
    )
    def partial_update(self, request: ValidatedRequest, *args, **kwargs):
        try:
            issue = facade_api.update_issue(
                team_id=self.team.id,
                issue_id=UUID(str(kwargs["pk"])),
                organization_id=self.organization.id,
                user=request.user,
                was_impersonated=is_impersonated_session(request),
                **request.validated_data,
            )
        except IssueNotFoundError:
            raise NotFound("Issue not found")

        serializer = ErrorTrackingIssueReadSerializer(issue)
        return Response(serializer.data)

    @validated_request(
        request_serializer=ErrorTrackingIssueUpdateSerializer, responses={200: ErrorTrackingIssueReadSerializer}
    )
    def update(self, request: ValidatedRequest, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    @validated_request(
        request_serializer=ErrorTrackingIssueMergeRequestSerializer,
        responses={200: OpenApiResponse(response=ErrorTrackingIssueMergeResponseSerializer)},
    )
    @action(methods=["POST"], detail=True)
    def merge(self, request: ValidatedRequest, **kwargs):
        try:
            facade_api.merge_issue(
                team_id=self.team.id,
                issue_id=UUID(str(kwargs["pk"])),
                issue_ids=request.validated_data["ids"],
            )
        except IssueNotFoundError:
            raise NotFound("Issue not found")
        return Response({"success": True})

    @validated_request(
        request_serializer=ErrorTrackingIssueSplitRequestSerializer,
        responses={200: OpenApiResponse(response=ErrorTrackingIssueSplitResponseSerializer)},
    )
    @action(methods=["POST"], detail=True)
    def split(self, request: ValidatedRequest, **kwargs):
        try:
            new_issue_ids = facade_api.split_issue(
                team_id=self.team.id,
                issue_id=UUID(str(kwargs["pk"])),
                fingerprints=request.validated_data["fingerprints"],
            )
        except IssueNotFoundError:
            raise NotFound("Issue not found")
        return Response({"success": True, "new_issue_ids": [str(issue_id) for issue_id in new_issue_ids]})

    @action(methods=["PATCH"], detail=True)
    def assign(self, request, **kwargs):
        try:
            facade_api.assign_issue(
                team_id=self.team_id,
                issue_id=UUID(str(kwargs["pk"])),
                assignee=request.data.get("assignee", None),
                organization=self.organization,
                user=request.user,
                was_impersonated=is_impersonated_session(request),
            )
        except IssueNotFoundError:
            raise NotFound("Issue not found")
        except ValueError as error:
            raise ValidationError(str(error)) from error

        return Response({"success": True})

    @action(methods=["PUT"], detail=True)
    def cohort(self, request, **kwargs):
        cohort_id = request.data.get("cohortId", None)
        if cohort_id is None:
            raise ValidationError("Please provide a cohort id")

        try:
            facade_api.set_issue_cohort(
                team_id=self.team.id,
                issue_id=UUID(str(kwargs["pk"])),
                cohort_id=cohort_id,
                distinct_id=self.request.user.pk,
            )
        except IssueNotFoundError:
            raise NotFound("Issue not found")
        except facade_api.CohortNotFoundError:
            raise NotFound("Cohort not found")
        except facade_api.IssueCohortAssignmentError:
            raise ValidationError("An error occurred while assigning this cohort")

        return Response({"success": True})

    @action(methods=["GET"], detail=False)
    def values(self, request: request.Request, **kwargs):
        issue_values = facade_api.get_issue_values(
            team_id=self.team.id,
            key=request.GET.get("key"),
            value=request.GET.get("value"),
        )

        return Response({"results": [{"name": value} for value in issue_values], "refreshing": False})

    @action(methods=["POST"], detail=False)
    def bulk(self, request, **kwargs):
        try:
            facade_api.bulk_update_issues(
                team_id=self.team_id,
                issue_ids=request.data.get("ids", []),
                action=request.data.get("action"),
                status=request.data.get("status"),
                assignee=request.data.get("assignee", None),
                organization=self.organization,
                user=request.user,
                was_impersonated=is_impersonated_session(request),
            )
        except facade_api.InvalidIssueStatusError:
            raise ValidationError("Invalid status")
        except ValueError as error:
            raise ValidationError(str(error)) from error

        return Response({"success": True})

    @extend_schema(operation_id="error_tracking_issues_all_activity_retrieve")
    @action(methods=["GET"], url_path="activity", detail=False, required_scopes=["activity_log:read"])
    def all_activity(self, request: request.Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        activity_page = load_activity(scope="ErrorTrackingIssue", team_id=self.team_id, limit=limit, page=page)
        return activity_page_response(activity_page, limit, page, request)

    @action(methods=["GET"], detail=True, required_scopes=["activity_log:read"])
    def activity(self, request: request.Request, **kwargs):
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        item_id = kwargs["pk"]
        if not facade_api.issue_exists_by_id(issue_id=UUID(str(item_id)), team_id=self.team_id):
            return Response(status=status.HTTP_404_NOT_FOUND)

        activity_page = load_activity(
            scope="ErrorTrackingIssue",
            team_id=self.team_id,
            item_ids=[str(item_id)],
            limit=limit,
            page=page,
        )
        return activity_page_response(activity_page, limit, page, request)


def assign_issue(issue, assignee, organization, user, team_id, was_impersonated):
    facade_api.assign_issue(
        team_id=team_id,
        issue_id=issue.id,
        assignee=assignee,
        organization=organization,
        user=user,
        was_impersonated=was_impersonated,
    )


def get_status_from_string(status: str) -> str | None:
    return facade_api.get_status_from_string(status)
