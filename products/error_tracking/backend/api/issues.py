from django.db import transaction
from django.db.models.query import QuerySet
from django.http import JsonResponse

import structlog
from loginas.utils import is_impersonated_session
from rest_framework import request, serializers, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models.activity_logging.activity_log import Change, Detail, load_activity, log_activity
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.tasks.email import send_error_tracking_issue_assigned

from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueFingerprintV2,
)

from .external_references import ErrorTrackingExternalReferenceSerializer
from .utils import ErrorTrackingIssueAssignmentSerializer

DEFAULT_EMBEDDING_MODEL_NAME = "text-embedding-3-large"
DEFAULT_EMBEDDING_VERSION = 1
DEFAULT_MIN_DISTANCE_THRESHOLD = 0.10

logger = structlog.get_logger(__name__)


class ErrorTrackingIssueSerializer(serializers.ModelSerializer):
    first_seen = serializers.DateTimeField()
    assignee = ErrorTrackingIssueAssignmentSerializer(source="assignment")
    external_issues = ErrorTrackingExternalReferenceSerializer(many=True)

    class Meta:
        model = ErrorTrackingIssue
        fields = ["id", "status", "name", "description", "first_seen", "assignee", "external_issues"]

    def update(self, instance, validated_data):
        team = instance.team
        status_after = validated_data.get("status")
        status_before = instance.status
        status_updated = "status" in validated_data and status_after != status_before

        name_after = validated_data.get("name")
        name_before = instance.name
        name_updated = "name" in validated_data and name_after != name_before

        updated_instance = super().update(instance, validated_data)

        changes = []
        if status_updated:
            changes.append(
                Change(
                    type="ErrorTrackingIssue",
                    field="status",
                    before=status_before,
                    after=status_after,
                    action="changed",
                )
            )
        if name_updated:
            changes.append(
                Change(type="ErrorTrackingIssue", field="name", before=name_before, after=name_after, action="changed")
            )

        if changes:
            log_activity(
                organization_id=team.organization.id,
                team_id=team.id,
                user=self.context["request"].user,
                was_impersonated=is_impersonated_session(self.context["request"]),
                item_id=str(updated_instance.id),
                scope="ErrorTrackingIssue",
                activity="updated",
                detail=Detail(
                    name=instance.name,
                    changes=changes,
                ),
            )

        return updated_instance


class ErrorTrackingIssueViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = ErrorTrackingIssue.objects.with_first_seen().all()
    serializer_class = ErrorTrackingIssueSerializer

    def safely_get_queryset(self, queryset):
        return (
            queryset.select_related("assignment")
            .prefetch_related("external_issues__integration")
            .filter(team_id=self.team.id)
        )

    def retrieve(self, request, *args, **kwargs):
        fingerprint = self.request.GET.get("fingerprint")
        if fingerprint:
            fingerprint_queryset = ErrorTrackingIssueFingerprintV2.objects.select_related("issue").filter(
                team=self.team
            )
            record = fingerprint_queryset.filter(fingerprint=fingerprint).first()

            if record:
                if not str(record.issue_id) == self.kwargs.get("pk"):
                    return JsonResponse({"issue_id": record.issue_id}, status=status.HTTP_308_PERMANENT_REDIRECT)

                issue = (
                    ErrorTrackingIssue.objects.with_first_seen()
                    .select_related("assignment")
                    .prefetch_related("external_issues__integration")
                    .get(id=record.issue_id)
                )
                serializer = self.get_serializer(issue)
                return Response(serializer.data)

        return super().retrieve(request, *args, **kwargs)

    @action(methods=["POST"], detail=True)
    def merge(self, request, **kwargs):
        issue: ErrorTrackingIssue = self.get_object()
        ids: list[str] = request.data.get("ids", [])
        # Make sure we don't delete the issue being merged into (defensive of frontend bugs)
        ids = [x for x in ids if x != str(issue.id)]
        issue.merge(issue_ids=ids)
        return Response({"success": True})

    @action(methods=["POST"], detail=True)
    def split(self, request, **kwargs):
        issue: ErrorTrackingIssue = self.get_object()
        fingerprints: list[str] = request.data.get("fingerprints", [])
        exclusive: bool = request.data.get("exclusive", True)
        issue.split(fingerprints=fingerprints, exclusive=exclusive)
        return Response({"success": True})

    @action(methods=["PATCH"], detail=True)
    def assign(self, request, **kwargs):
        assignee = request.data.get("assignee", None)
        instance = self.get_object()

        assign_issue(
            instance, assignee, self.organization, request.user, self.team_id, is_impersonated_session(request)
        )

        return Response({"success": True})

    @action(methods=["GET"], detail=False)
    def values(self, request: request.Request, **kwargs):
        queryset = self.get_queryset()
        value = request.GET.get("value", None)
        key = request.GET.get("key")

        issue_values: QuerySet[ErrorTrackingIssue] = QuerySet()
        if key and value:
            if key == "name":
                issue_values = queryset.filter(name__icontains=value).values_list("name", flat=True)
            elif key == "issue_description":
                issue_values = queryset.filter(description__icontains=value).values_list("description", flat=True)

        return Response([{"name": value} for value in issue_values])

    @action(methods=["POST"], detail=False)
    def bulk(self, request, **kwargs):
        action = request.data.get("action")
        status = request.data.get("status")
        issues = self.get_queryset().filter(id__in=request.data.get("ids", []))

        with transaction.atomic():
            if action == "set_status":
                new_status = get_status_from_string(status)
                if new_status is None:
                    raise ValidationError("Invalid status")
                for issue in issues:
                    _ = log_activity(
                        organization_id=self.organization.id,
                        team_id=self.team_id,
                        user=request.user,
                        was_impersonated=is_impersonated_session(request),
                        item_id=issue.id,
                        scope="ErrorTrackingIssue",
                        activity="updated",
                        detail=Detail(
                            name=issue.name,
                            changes=[
                                Change(
                                    type="ErrorTrackingIssue",
                                    action="changed",
                                    field="status",
                                    before=issue.status,
                                    after=new_status,
                                )
                            ],
                        ),
                    )

                issues.update(status=new_status)
            elif action == "assign":
                assignee = request.data.get("assignee", None)

                for issue in issues:
                    assign_issue(
                        issue, assignee, self.organization, request.user, self.team_id, is_impersonated_session(request)
                    )

        return Response({"success": True})

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
        if not ErrorTrackingIssue.objects.filter(id=item_id, team_id=self.team_id).exists():
            return Response(status=status.HTTP_404_NOT_FOUND)

        activity_page = load_activity(
            scope="ErrorTrackingIssue",
            team_id=self.team_id,
            item_ids=[str(item_id)],
            limit=limit,
            page=page,
        )
        return activity_page_response(activity_page, limit, page, request)


def assign_issue(issue: ErrorTrackingIssue, assignee, organization, user, team_id, was_impersonated):
    assignment_before = ErrorTrackingIssueAssignment.objects.filter(issue_id=issue.id).first()
    serialized_assignment_before = (
        ErrorTrackingIssueAssignmentSerializer(assignment_before).data if assignment_before else None
    )

    if assignee:
        assignment_after, _ = ErrorTrackingIssueAssignment.objects.update_or_create(
            issue_id=issue.id,
            defaults={
                "user_id": None if assignee["type"] != "user" else assignee["id"],
                "role_id": None if assignee["type"] != "role" else assignee["id"],
            },
        )

        send_error_tracking_issue_assigned(assignment_after, user)

        serialized_assignment_after = (
            ErrorTrackingIssueAssignmentSerializer(assignment_after).data if assignment_after else None
        )
    else:
        if assignment_before:
            assignment_before.delete()
        serialized_assignment_after = None

    log_activity(
        organization_id=organization.id,
        team_id=team_id,
        user=user,
        was_impersonated=was_impersonated,
        item_id=str(issue.id),
        scope="ErrorTrackingIssue",
        activity="assigned",
        detail=Detail(
            name=issue.name,
            changes=[
                Change(
                    type="ErrorTrackingIssue",
                    field="assignee",
                    before=serialized_assignment_before,
                    after=serialized_assignment_after,
                    action="changed",
                )
            ],
        ),
    )


def get_status_from_string(status: str) -> ErrorTrackingIssue.Status | None:
    match status:
        case "active":
            return ErrorTrackingIssue.Status.ACTIVE
        case "resolved":
            return ErrorTrackingIssue.Status.RESOLVED
        case "suppressed":
            return ErrorTrackingIssue.Status.SUPPRESSED
    return None
