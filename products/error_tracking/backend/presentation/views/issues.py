from uuid import UUID

from django.http import JsonResponse

import structlog
import posthoganalytics
from drf_spectacular.utils import OpenApiResponse
from rest_framework import request, serializers, status, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from posthog.api.documentation import extend_schema, extend_schema_field
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.helpers.impersonation import is_impersonated
from posthog.models.activity_logging.activity_log import load_activity
from posthog.models.activity_logging.activity_page import activity_page_response

from products.error_tracking.backend.facade import (
    api as facade_api,
    issues as issues_facade,
)
from products.error_tracking.backend.presentation.pagination import paginate_via_facade
from products.error_tracking.backend.presentation.views.external_references import (
    ErrorTrackingExternalReferenceSerializer,
)

IssueNotFoundError = facade_api.IssueNotFoundError

logger = structlog.get_logger(__name__)

# Statuses a client may set. Deprecated archived/pending_release values are rejected
# by being absent from the choices; reads of legacy rows still pass through.
WRITABLE_ISSUE_STATUSES = ["active", "resolved", "suppressed"]


class ErrorTrackingIssueAssigneeReadSerializer(serializers.Serializer):
    # User assignees carry an integer id, role assignees a UUID string. `CharField` would
    # coerce the user id to a string, which the frontend assignee resolver compares with
    # `===` against the numeric member id — failing to resolve and rendering "Unassigned".
    id = serializers.SerializerMethodField()
    type = serializers.CharField()

    @extend_schema_field({"oneOf": [{"type": "integer"}, {"type": "string"}], "nullable": True})
    def get_id(self, obj) -> int | str | None:
        return obj.id


class ErrorTrackingIssueCohortReadSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class ErrorTrackingIssueReadSerializer(serializers.Serializer):
    """Read-only serializer for issue contract types returned by the facade."""

    id = serializers.UUIDField()
    status = serializers.CharField()
    name = serializers.CharField(allow_null=True)
    description = serializers.CharField(allow_null=True)
    first_seen = serializers.DateTimeField(allow_null=True)
    fingerprint = serializers.CharField(
        allow_null=True,
        help_text="Deterministic current fingerprint used for issue links, selected by earliest creation time and ID.",
    )
    assignee = ErrorTrackingIssueAssigneeReadSerializer(allow_null=True)
    external_issues = ErrorTrackingExternalReferenceSerializer(many=True)
    cohort = ErrorTrackingIssueCohortReadSerializer(allow_null=True)


class ErrorTrackingIssueWriteSerializer(serializers.Serializer):
    status = serializers.ChoiceField(
        choices=WRITABLE_ISSUE_STATUSES,
        required=False,
        help_text="Issue status to set. Deprecated archived and pending_release values are rejected.",
    )
    name = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Optional issue display name.",
    )
    description = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        help_text="Optional issue description.",
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


class ErrorTrackingIssueViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.GenericViewSet):
    scope_object = "error_tracking"
    # These override the base defaults, so keep the standard DRF actions too.
    scope_object_read_actions = ["list", "retrieve", "values", "exists"]
    scope_object_write_actions = [
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
    serializer_class = ErrorTrackingIssueReadSerializer

    def list(self, request: request.Request, *args: object, **kwargs: object) -> Response:
        return paginate_via_facade(
            self,
            request,
            lambda limit, offset: facade_api.list_issues_detailed(self.team.id, limit=limit, offset=offset),
        )

    def retrieve(self, request: request.Request, *args: object, **kwargs: object) -> Response | JsonResponse:
        try:
            issue_id = UUID(str(kwargs["pk"]))
        except ValueError:
            raise NotFound("Issue not found")
        fingerprint = self.request.GET.get("fingerprint")

        if fingerprint:
            resolved_id = facade_api.get_issue_id_for_fingerprint(team_id=self.team.id, fingerprint=fingerprint)
            if resolved_id and resolved_id != issue_id:
                return JsonResponse({"issue_id": resolved_id}, status=status.HTTP_308_PERMANENT_REDIRECT)

        try:
            issue = facade_api.get_issue(issue_id=issue_id, team_id=self.team.id)
        except IssueNotFoundError:
            raise NotFound("Issue not found")

        return Response(ErrorTrackingIssueReadSerializer(issue).data)

    @extend_schema(request=ErrorTrackingIssueWriteSerializer, responses={200: ErrorTrackingIssueReadSerializer})
    def update(self, request: request.Request, *args: object, **kwargs: object) -> Response:
        return self._update_issue(request, kwargs["pk"])

    @extend_schema(request=ErrorTrackingIssueWriteSerializer, responses={200: ErrorTrackingIssueReadSerializer})
    def partial_update(self, request: request.Request, *args: object, **kwargs: object) -> Response:
        return self._update_issue(request, kwargs["pk"])

    def _update_issue(self, request: request.Request, pk: object) -> Response:
        request_serializer = ErrorTrackingIssueWriteSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        try:
            issue = issues_facade.update_issue(
                self.team.id,
                UUID(str(pk)),
                fields=dict(request_serializer.validated_data),
                user=request.user,
                was_impersonated=is_impersonated(request),
            )
        except IssueNotFoundError:
            raise NotFound("Issue not found")
        return Response(ErrorTrackingIssueReadSerializer(issue).data)

    @action(methods=["GET"], detail=False)
    def exists(self, request: request.Request, **kwargs: object) -> Response:
        return Response({"exists": facade_api.issue_exists(self.team.id)})

    @validated_request(
        request_serializer=ErrorTrackingIssueMergeRequestSerializer,
        responses={200: OpenApiResponse(response=ErrorTrackingIssueMergeResponseSerializer)},
    )
    @action(methods=["POST"], detail=True)
    def merge(self, request: ValidatedRequest, *args: object, pk: object = None, **kwargs: object) -> Response:
        ids = [str(issue_id) for issue_id in request.validated_data["ids"]]
        try:
            merge_result = issues_facade.merge_issues(self.team.id, UUID(str(pk)), ids)
        except IssueNotFoundError:
            raise NotFound("Issue not found")
        if merge_result == issues_facade.ErrorTrackingIssueMergeResult.STALE_ISSUES:
            raise NotFound("Issue not found")
        if merge_result == issues_facade.ErrorTrackingIssueMergeResult.STALE_FINGERPRINTS:
            raise ValidationError("Issue fingerprints changed before merge. Please retry.")
        return Response({"success": merge_result == issues_facade.ErrorTrackingIssueMergeResult.MERGED})

    @validated_request(
        request_serializer=ErrorTrackingIssueSplitRequestSerializer,
        responses={200: OpenApiResponse(response=ErrorTrackingIssueSplitResponseSerializer)},
    )
    @action(methods=["POST"], detail=True)
    def split(self, request: ValidatedRequest, *args: object, pk: object = None, **kwargs: object) -> Response:
        fingerprints = request.validated_data["fingerprints"]
        try:
            new_issue_ids = issues_facade.split_issue(self.team.id, UUID(str(pk)), fingerprints)
        except IssueNotFoundError:
            raise NotFound("Issue not found")
        return Response({"success": True, "new_issue_ids": [str(i) for i in new_issue_ids]})

    @action(methods=["PATCH"], detail=True)
    def assign(self, request: request.Request, *args: object, pk: object = None, **kwargs: object) -> Response:
        assignee = request.data.get("assignee", None)
        try:
            issues_facade.assign_issue(
                self.team.id,
                UUID(str(pk)),
                assignee,
                user=request.user,
                was_impersonated=is_impersonated(request),
            )
        except IssueNotFoundError:
            raise NotFound("Issue not found")
        except issues_facade.AssigneeValidationError as err:
            raise ValidationError(str(err))
        return Response({"success": True})

    @action(methods=["PUT"], detail=True)
    def cohort(self, request: request.Request, *args: object, pk: object = None, **kwargs: object) -> Response:
        cohort_id = request.data.get("cohortId", None)
        if cohort_id is None:
            raise ValidationError("Please provide a cohort id")

        try:
            issues_facade.set_issue_cohort(self.team.id, UUID(str(pk)), cohort_id)
        except IssueNotFoundError:
            raise NotFound("Issue not found")
        except issues_facade.CohortNotFoundError:
            raise NotFound("Cohort not found")
        except Exception as e:
            posthoganalytics.capture_exception(
                e, distinct_id=self.request.user.pk, properties={"issue_id": str(pk), "cohort_id": cohort_id}
            )
            raise ValidationError("An error occurred while assigning this cohort")

        return Response({"success": True})

    @action(methods=["GET"], detail=False)
    def values(self, request: request.Request, **kwargs: object) -> Response:
        value = request.GET.get("value", None)
        key = request.GET.get("key")
        issue_values = facade_api.get_issue_values(self.team.id, key, value)
        return Response({"results": [{"name": value} for value in issue_values], "refreshing": False})

    @action(methods=["POST"], detail=False)
    def bulk(self, request: request.Request, **kwargs: object) -> Response:
        try:
            issues_facade.bulk_update_issues(
                self.team.id,
                request.data.get("ids", []),
                action=request.data.get("action"),
                status=request.data.get("status"),
                assignee=request.data.get("assignee", None),
                user=request.user,
                was_impersonated=is_impersonated(request),
            )
        except issues_facade.InvalidIssueStatusError:
            raise ValidationError("Invalid status")
        except issues_facade.AssigneeValidationError as err:
            raise ValidationError(str(err))
        return Response({"success": True})

    @extend_schema(operation_id="error_tracking_issues_all_activity_retrieve")
    @action(methods=["GET"], url_path="activity", detail=False, required_scopes=["activity_log:read"])
    def all_activity(self, request: request.Request, **kwargs: object) -> Response:
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        activity_page = load_activity(scope="ErrorTrackingIssue", team_id=self.team_id, limit=limit, page=page)
        return activity_page_response(activity_page, limit, page, request)

    @action(methods=["GET"], detail=True, required_scopes=["activity_log:read"])
    def activity(self, request: request.Request, *args: object, pk: object = None, **kwargs: object) -> Response:
        limit = int(request.query_params.get("limit", "10"))
        page = int(request.query_params.get("page", "1"))

        if not facade_api.issue_exists_by_id(self.team_id, str(pk)):
            return Response(status=status.HTTP_404_NOT_FOUND)

        activity_page = load_activity(
            scope="ErrorTrackingIssue",
            team_id=self.team_id,
            item_ids=[str(pk)],
            limit=limit,
            page=page,
        )
        return activity_page_response(activity_page, limit, page, request)
