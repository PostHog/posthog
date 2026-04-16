import hashlib
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Protocol, TypeVar, override

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.db.models.query import QuerySet
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

import requests
import structlog
import posthoganalytics
from drf_spectacular.utils import (
    OpenApiResponse,
    extend_schema as extend_schema_tags,
)
from loginas.utils import is_impersonated_session
from pydantic import ValidationError as PydanticValidationError
from rest_framework import mixins, request, status, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FileUploadParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from posthog.schema import ProductKey, PropertyGroupFilterValue

from posthog.hogql import ast
from posthog.hogql.compiler.bytecode import create_bytecode
from posthog.hogql.property import property_to_expr

from posthog.api.documentation import extend_schema
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.mixins import ValidatedRequest, validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.event_usage import groups
from posthog.models.activity_logging.activity_log import Change, Detail, load_activity, log_activity
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.models.cohort.cohort import Cohort
from posthog.models.integration import GitHubIntegration, GitLabIntegration, Integration
from posthog.models.organization import OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.utils import UUIDT, uuid7
from posthog.rate_limit import SymbolSetUploadBurstRateThrottle, SymbolSetUploadSustainedRateThrottle
from posthog.storage import object_storage
from posthog.tasks.email import send_error_tracking_issue_assigned

from products.error_tracking.backend.hogvm_stl import RUST_HOGVM_STL
from products.error_tracking.backend.models import (
    ErrorTrackingAssignmentRule,
    ErrorTrackingExternalReference,
    ErrorTrackingGroupingRule,
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueCohort,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingRelease,
    ErrorTrackingSpikeDetectionConfig,
    ErrorTrackingSpikeEvent,
    ErrorTrackingStackFrame,
    ErrorTrackingSuppressionRule,
    ErrorTrackingSymbolSet,
    sync_issues_to_clickhouse,
)
from products.error_tracking.backend.presentation.serializers import (
    ErrorTrackingAssignmentRuleSerializer,
    ErrorTrackingExternalReferenceSerializer,
    ErrorTrackingFingerprintSerializer,
    ErrorTrackingGroupingRuleSerializer,
    ErrorTrackingIssueAssignmentSerializer,
    ErrorTrackingIssueFullSerializer,
    ErrorTrackingIssueMergeRequestSerializer,
    ErrorTrackingIssueMergeResponseSerializer,
    ErrorTrackingReleaseSerializer,
    ErrorTrackingSpikeDetectionConfigSerializer,
    ErrorTrackingSpikeEventSerializer,
    ErrorTrackingStackFrameSerializer,
    ErrorTrackingSuppressionRuleSerializer,
    ErrorTrackingSymbolSetSerializer,
    ErrorTrackingSymbolSetUploadSerializer,
    SymbolSetUpload,
)

from common.hogvm.python.operation import Operation

DEFAULT_EMBEDDING_MODEL_NAME = "text-embedding-3-large"
DEFAULT_EMBEDDING_VERSION = 1
DEFAULT_MIN_DISTANCE_THRESHOLD = 0.10

ONE_HUNDRED_MEGABYTES = 1024 * 1024 * 100
JS_DATA_MAGIC = b"posthog_error_tracking"
JS_DATA_VERSION = 1
JS_DATA_TYPE_SOURCE_AND_MAP = 2
PRESIGNED_MULTIPLE_UPLOAD_TIMEOUT = 60 * 5

logger = structlog.get_logger(__name__)


class HasGetQueryset(Protocol):
    def get_queryset(self): ...


T = TypeVar("T", bound=HasGetQueryset)


class RuleReorderingMixin:
    @action(methods=["PATCH"], detail=False)
    def reorder(self: T, request, **kwargs):
        orders: dict[str, int] = request.data.get("orders", {})
        rules = self.get_queryset().filter(id__in=orders.keys())

        for rule in rules:
            rule.order_key = orders[str(rule.id)]

        self.get_queryset().bulk_update(rules, ["order_key"])

        return Response({"ok": True}, status=status.HTTP_204_NO_CONTENT)


def generate_byte_code(team: Team, props: PropertyGroupFilterValue):
    expr = property_to_expr(props, team, strict=True)
    # The rust HogVM expects a return statement, so we wrap the compiled filter expression in one
    with_return = ast.ReturnStatement(expr=expr)
    bytecode = create_bytecode(with_return).bytecode
    validate_bytecode(bytecode)
    return bytecode


def generate_match_all_bytecode():
    """Generate bytecode that always returns true (matches all events)."""
    with_return = ast.ReturnStatement(expr=ast.Constant(value=True))
    return create_bytecode(with_return).bytecode


def validate_bytecode(bytecode: list[Any]) -> None:
    for i, op in enumerate(bytecode):
        if not isinstance(op, Operation):
            continue
        if op == Operation.CALL_GLOBAL:
            name = bytecode[i + 1]
            if not isinstance(name, str):
                raise ValidationError(f"Expected string for global function name, got {type(name)}")
            if name not in RUST_HOGVM_STL:
                raise ValidationError(f"Unknown global function: {name}")


class ErrorTrackingFingerprintViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ReadOnlyModelViewSet):
    scope_object = "error_tracking"
    queryset = ErrorTrackingIssueFingerprintV2.objects.all()
    serializer_class = ErrorTrackingFingerprintSerializer

    def safely_get_queryset(self, queryset):
        params = self.request.GET.dict()
        queryset = queryset.filter(team_id=self.team.id)
        if params.get("issue_id"):
            queryset = queryset.filter(issue_id=params["issue_id"])
        return queryset


class ErrorTrackingExternalReferenceViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
    scope_object = "INTERNAL"
    queryset = ErrorTrackingExternalReference.objects.all()
    serializer_class = ErrorTrackingExternalReferenceSerializer


class ErrorTrackingAssignmentRuleViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet, RuleReorderingMixin):
    scope_object = "error_tracking"
    queryset = ErrorTrackingAssignmentRule.objects.order_by("order_key").all()
    serializer_class = ErrorTrackingAssignmentRuleSerializer

    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team.id)

    def update(self, request, *args, **kwargs) -> Response:
        assignment_rule = self.get_object()
        assignee = request.data.get("assignee")
        json_filters = request.data.get("filters")

        if json_filters:
            parsed_filters = PropertyGroupFilterValue(**json_filters)
            assignment_rule.filters = json_filters
            assignment_rule.bytecode = generate_byte_code(self.team, parsed_filters)

        if assignee:
            assignment_rule.user_id = None if assignee["type"] != "user" else assignee["id"]
            assignment_rule.role_id = None if assignee["type"] != "role" else assignee["id"]

        assignment_rule.disabled_data = None
        assignment_rule.save()

        posthoganalytics.capture(
            "error_tracking_assignment_rule_edited",
            groups=groups(self.team.organization, self.team),
        )

        return Response({"ok": True}, status=status.HTTP_204_NO_CONTENT)

    def partial_update(self, request, *args, **kwargs) -> Response:
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs) -> Response:
        response = super().destroy(request, *args, **kwargs)

        posthoganalytics.capture(
            "error_tracking_assignment_rule_deleted",
            groups=groups(self.team.organization, self.team),
        )

        return response

    def create(self, request, *args, **kwargs) -> Response:
        json_filters = request.data.get("filters")
        assignee = request.data.get("assignee", None)

        if not json_filters:
            return Response({"error": "Filters are required"}, status=status.HTTP_400_BAD_REQUEST)
        if not assignee:
            return Response({"error": "Assignee is required"}, status=status.HTTP_400_BAD_REQUEST)

        parsed_filters = PropertyGroupFilterValue(**json_filters)

        bytecode = generate_byte_code(self.team, parsed_filters)

        assignment_rule = ErrorTrackingAssignmentRule.objects.create(
            team=self.team,
            filters=json_filters,
            bytecode=bytecode,
            order_key=0,
            user_id=None if assignee["type"] != "user" else assignee["id"],
            role_id=None if assignee["type"] != "role" else assignee["id"],
        )

        posthoganalytics.capture(
            "error_tracking_assignment_rule_created",
            groups=groups(self.team.organization, self.team),
        )

        serializer = ErrorTrackingAssignmentRuleSerializer(assignment_rule)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


def _build_issue_map(team_id: int, rule_ids: list[str]) -> dict:
    """Build a mapping of rule_id -> ErrorTrackingIssue for grouping rules."""
    if not rule_ids:
        return {}
    fingerprints = (
        ErrorTrackingIssueFingerprintV2.objects.select_related("issue")
        .filter(
            team_id=team_id,
            fingerprint__in=[f"custom-rule:{rid}" for rid in rule_ids],
        )
        .only("fingerprint", "issue_id", "issue__id", "issue__name")
    )
    return {fp.fingerprint.removeprefix("custom-rule:"): fp.issue for fp in fingerprints}


class ErrorTrackingGroupingRuleViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet, RuleReorderingMixin):
    scope_object = "error_tracking"
    queryset = ErrorTrackingGroupingRule.objects.order_by("order_key").all()
    serializer_class = ErrorTrackingGroupingRuleSerializer

    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team.id)

    def list(self, request, *args, **kwargs) -> Response:
        queryset = list(self.filter_queryset(self.get_queryset()))
        rule_ids = [str(r.id) for r in queryset]
        issue_map = _build_issue_map(self.team.id, rule_ids)
        context = {**self.get_serializer_context(), "issue_map": issue_map}
        serializer = self.get_serializer(queryset, many=True, context=context)
        return Response({"results": serializer.data})

    def update(self, request, *args, **kwargs) -> Response:
        grouping_rule = self.get_object()
        assignee = request.data.get("assignee")
        json_filters = request.data.get("filters")
        description = request.data.get("description")

        if json_filters:
            parsed_filters = PropertyGroupFilterValue(**json_filters)
            grouping_rule.filters = json_filters
            grouping_rule.bytecode = generate_byte_code(self.team, parsed_filters)

        if assignee:
            grouping_rule.user_id = None if assignee["type"] != "user" else assignee["id"]
            grouping_rule.role_id = None if assignee["type"] != "role" else assignee["id"]

        if description:
            grouping_rule.description = description

        grouping_rule.disabled_data = None
        grouping_rule.save()

        posthoganalytics.capture(
            "error_tracking_grouping_rule_edited",
            groups=groups(self.team.organization, self.team),
        )

        return Response({"ok": True}, status=status.HTTP_204_NO_CONTENT)

    def partial_update(self, request, *args, **kwargs) -> Response:
        return self.update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs) -> Response:
        response = super().destroy(request, *args, **kwargs)

        posthoganalytics.capture(
            "error_tracking_grouping_rule_deleted",
            groups=groups(self.team.organization, self.team),
        )

        return response

    def create(self, request, *args, **kwargs) -> Response:
        json_filters = request.data.get("filters")
        assignee = request.data.get("assignee", None)
        description = request.data.get("description", None)

        if not json_filters:
            return Response({"error": "Filters are required"}, status=status.HTTP_400_BAD_REQUEST)

        parsed_filters = PropertyGroupFilterValue(**json_filters)
        bytecode = generate_byte_code(self.team, parsed_filters)

        grouping_rule = ErrorTrackingGroupingRule.objects.create(
            team=self.team,
            filters=json_filters,
            bytecode=bytecode,
            order_key=0,
            user_id=None if (not assignee or assignee["type"] != "user") else assignee["id"],
            role_id=None if (not assignee or assignee["type"] != "role") else assignee["id"],
            description=description,
        )

        posthoganalytics.capture(
            "error_tracking_grouping_rule_created",
            groups=groups(self.team.organization, self.team),
        )

        serializer = ErrorTrackingGroupingRuleSerializer(grouping_rule)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


@extend_schema(tags=[ProductKey.ERROR_TRACKING])
class ErrorTrackingIssueViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ModelViewSet):
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
    queryset = ErrorTrackingIssue.objects.with_first_seen().all()
    serializer_class = ErrorTrackingIssueFullSerializer

    def safely_get_queryset(self, queryset):
        return (
            queryset.select_related("assignment")
            .prefetch_related("external_issues__integration")
            .prefetch_related("cohorts__cohort")
            .filter(team_id=self.team.id)
        )

    @action(methods=["GET"], detail=False)
    def exists(self, request, **kwargs):
        has_issues = ErrorTrackingIssue.objects.filter(team_id=self.team.id).exists()
        return Response({"exists": has_issues})

    def retrieve(self, request, *args, **kwargs):
        fingerprint = self.request.GET.get("fingerprint")
        if fingerprint:
            fingerprint_queryset = ErrorTrackingIssueFingerprintV2.objects.select_related("issue").filter(
                team=self.team
            )
            record = fingerprint_queryset.filter(fingerprint=fingerprint).first()

            if record:
                if str(record.issue_id) != self.kwargs.get("pk"):
                    return JsonResponse({"issue_id": record.issue_id}, status=status.HTTP_308_PERMANENT_REDIRECT)

                issue = (
                    ErrorTrackingIssue.objects.with_first_seen()
                    .select_related("assignment")
                    .prefetch_related("external_issues__integration")
                    .get(id=record.issue_id, team=self.team)
                )
                serializer = self.get_serializer(issue)
                return Response(serializer.data)

        return super().retrieve(request, *args, **kwargs)

    @validated_request(
        request_serializer=ErrorTrackingIssueMergeRequestSerializer,
        responses={200: OpenApiResponse(response=ErrorTrackingIssueMergeResponseSerializer)},
    )
    @action(methods=["POST"], detail=True)
    def merge(self, request: ValidatedRequest, **kwargs):
        issue: ErrorTrackingIssue = self.get_object()
        ids = [str(issue_id) for issue_id in request.validated_data["ids"]]
        # Make sure we don't delete the issue being merged into (defensive of frontend bugs)
        ids = [x for x in ids if x != str(issue.id)]
        issue.merge(issue_ids=ids)
        sync_issues_to_clickhouse(issue_ids=[issue.id], team_id=issue.team_id)
        return Response({"success": True})

    @action(methods=["POST"], detail=True)
    def split(self, request, **kwargs):
        issue: ErrorTrackingIssue = self.get_object()
        fingerprints = request.data.get("fingerprints", [])
        if not isinstance(fingerprints, list) or not all(
            isinstance(entry, dict) and isinstance(entry.get("fingerprint"), str) for entry in fingerprints
        ):
            raise ValidationError("fingerprints must be a list of objects with a 'fingerprint' string field")
        new_issues = issue.split(fingerprints=fingerprints)
        sync_issues_to_clickhouse(issue_ids=[issue.id] + [i.id for i in new_issues], team_id=issue.team_id)
        return Response({"success": True, "new_issue_ids": [str(i.id) for i in new_issues]})

    @action(methods=["PATCH"], detail=True)
    def assign(self, request, **kwargs):
        assignee = request.data.get("assignee", None)
        instance = self.get_object()

        assign_issue(
            instance, assignee, self.organization, request.user, self.team_id, is_impersonated_session(request)
        )
        sync_issues_to_clickhouse(issue_ids=[instance.id], team_id=instance.team_id)

        return Response({"success": True})

    @action(methods=["PUT"], detail=True)
    def cohort(self, request, **kwargs):
        cohort_id = request.data.get("cohortId", None)
        if cohort_id is None:
            raise ValidationError("Please provide a cohort id")

        issue: ErrorTrackingIssue = self.get_object()
        cohort = Cohort.objects.filter(team=self.team, id=cohort_id).first()
        if cohort is None:
            raise NotFound("Cohort not found")

        try:
            ## Upsert cohort_id as a cohort might have been soft deleted
            # nosemgrep: idor-lookup-without-team (cohort scoped to team before use)
            _ = ErrorTrackingIssueCohort.objects.update_or_create(issue=issue, defaults={"cohort_id": cohort.id})
        except Exception as error:
            posthoganalytics.capture_exception(
                error, distinct_id=self.request.user.pk, properties={"issue_id": issue.id, "cohort_id": cohort.id}
            )
            raise ValidationError("An error occurred while assigning this cohort")

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

        return Response({"results": [{"name": item} for item in issue_values], "refreshing": False})

    @action(methods=["POST"], detail=False)
    def bulk(self, request, **kwargs):
        bulk_action = request.data.get("action")
        issue_status = request.data.get("status")
        issues = self.get_queryset().filter(id__in=request.data.get("ids", []))

        with transaction.atomic():
            if bulk_action == "set_status":
                new_status = get_status_from_string(issue_status)
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
            elif bulk_action == "assign":
                assignee = request.data.get("assignee", None)

                for issue in issues:
                    assign_issue(
                        issue, assignee, self.organization, request.user, self.team_id, is_impersonated_session(request)
                    )

        sync_issues_to_clickhouse(issue_ids=[issue.id for issue in issues], team_id=self.team_id)

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
        if assignee["type"] == "user":
            if not OrganizationMembership.objects.filter(user_id=assignee["id"], organization=organization).exists():
                raise ValidationError("Assignee user does not belong to this organization.")
        elif assignee["type"] == "role":
            from ee.models.rbac.role import Role

            if not Role.objects.filter(id=assignee["id"], organization=organization).exists():
                raise ValidationError("Assignee role does not belong to this organization.")

        # nosemgrep: idor-lookup-without-team (assignee validated against org above)
        assignment_after, _ = ErrorTrackingIssueAssignment.objects.update_or_create(
            issue_id=issue.id,
            defaults={
                "team_id": issue.team_id,
                "user_id": None if assignee["type"] != "user" else assignee["id"],
                "role_id": None if assignee["type"] != "role" else assignee["id"],
            },
        )

        send_error_tracking_issue_assigned.delay(assignment_after.id, user.id)

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


def get_status_from_string(issue_status: str) -> ErrorTrackingIssue.Status | None:
    match issue_status:
        case "active":
            return ErrorTrackingIssue.Status.ACTIVE
        case "resolved":
            return ErrorTrackingIssue.Status.RESOLVED
        case "suppressed":
            return ErrorTrackingIssue.Status.SUPPRESSED
    return None


@extend_schema_tags(tags=[ProductKey.ERROR_TRACKING])
class ErrorTrackingReleaseViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "error_tracking"
    queryset = ErrorTrackingRelease.objects.all()
    scope_object_read_actions = ["list", "retrieve", "by_hash"]
    serializer_class = ErrorTrackingReleaseSerializer

    def safely_get_queryset(self, queryset):
        queryset = queryset.filter(team_id=self.team.id).order_by("-created_at")

        return queryset

    def validate_hash_id(self, hash_id: str, assert_new: bool) -> str:
        if len(hash_id) > 128:
            raise ValidationError("Hash id length cannot exceed 128 bytes")

        if assert_new and ErrorTrackingRelease.objects.filter(team=self.team, hash_id=hash_id).exists():
            raise ValidationError(f"Hash id {hash_id} already in use")

        return hash_id

    def update(self, request, *args, **kwargs) -> Response:
        release = self.get_object()

        metadata = request.data.get("metadata")
        hash_id = request.data.get("hash_id")
        version = request.data.get("version")
        project = request.data.get("project")

        if metadata:
            release.metadata = metadata

        if version:
            version = str(version)
            release.version = version

        if project:
            project = str(project)
            release.project = project

        if hash_id and hash_id != release.hash_id:
            hash_id = str(hash_id)
            hash_id = self.validate_hash_id(hash_id, True)
            release.hash_id = hash_id

        release.save()
        return Response({"ok": True}, status=status.HTTP_204_NO_CONTENT)

    def create(self, request, *args, **kwargs) -> Response:
        release_id = UUIDT()  # We use this in the hash if one isn't set, and also as the id of the model
        metadata = request.data.get("metadata")
        hash_id = str(request.data.get("hash_id") or release_id)
        hash_id = self.validate_hash_id(hash_id, True)
        version = request.data.get("version")
        project = request.data.get("project")

        if not version:
            raise ValidationError("Version is required")

        if not project:
            raise ValidationError("Project is required")

        version = str(version)

        release = ErrorTrackingRelease.objects.create(
            id=release_id,
            team=self.team,
            hash_id=hash_id,
            metadata=metadata,
            project=project,
            version=version,
        )

        serializer = ErrorTrackingReleaseSerializer(release)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"], url_path="hash/(?P<hash_id>[^/.]+)")
    def by_hash(self, request, hash_id=None, **kwargs):
        obj = get_object_or_404(self.get_queryset(), hash_id=hash_id)
        serializer = self.get_serializer(obj)
        return Response(serializer.data)


@extend_schema_tags(tags=[ProductKey.ERROR_TRACKING])
class ErrorTrackingSpikeDetectionConfigViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "error_tracking"

    def _get_or_create_config(self):
        config, _ = ErrorTrackingSpikeDetectionConfig.objects.get_or_create(team=self.team)
        return config

    def list(self, request, *args, **kwargs):
        config = self._get_or_create_config()
        serializer = ErrorTrackingSpikeDetectionConfigSerializer(config)
        return Response(serializer.data)

    @action(detail=False, methods=["patch"])
    def update_config(self, request, *args, **kwargs):
        config = self._get_or_create_config()
        serializer = ErrorTrackingSpikeDetectionConfigSerializer(config, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data, status=status.HTTP_200_OK)


@extend_schema_tags(tags=[ProductKey.ERROR_TRACKING])
class ErrorTrackingSpikeEventViewSet(TeamAndOrgViewSetMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    scope_object = "error_tracking"
    serializer_class = ErrorTrackingSpikeEventSerializer
    queryset = ErrorTrackingSpikeEvent.objects.all()

    ALLOWED_ORDER_FIELDS = [
        "detected_at",
        "-detected_at",
        "computed_baseline",
        "-computed_baseline",
        "current_bucket_value",
        "-current_bucket_value",
    ]

    def safely_get_queryset(self, queryset):
        qs = queryset.filter(team_id=self.team.id).select_related("issue")

        issue_ids_param = self.request.query_params.get("issue_ids")
        if issue_ids_param:
            ids = [uid.strip() for uid in issue_ids_param.split(",") if uid.strip()]
            if ids:
                qs = qs.filter(issue_id__in=ids)

        date_from = self.request.query_params.get("date_from")
        date_to = self.request.query_params.get("date_to")
        if date_from:
            qs = qs.filter(detected_at__gte=date_from)
        if date_to:
            qs = qs.filter(detected_at__lte=date_to)

        order_by = self.request.query_params.get("order_by")
        if order_by and order_by in self.ALLOWED_ORDER_FIELDS:
            qs = qs.order_by(order_by)
        else:
            qs = qs.order_by("-detected_at")

        return qs


@extend_schema_tags(tags=[ProductKey.ERROR_TRACKING])
class ErrorTrackingStackFrameViewSet(TeamAndOrgViewSetMixin, ForbidDestroyModel, viewsets.ReadOnlyModelViewSet):
    scope_object = "error_tracking"
    scope_object_read_actions = ["list", "retrieve", "batch_get"]
    scope_object_write_actions: list = []
    queryset = ErrorTrackingStackFrame.objects.all()
    serializer_class = ErrorTrackingStackFrameSerializer

    @action(methods=["POST"], detail=False)
    def batch_get(self, request, **kwargs):
        raw_ids = request.data.get("raw_ids", [])
        symbol_set = request.data.get("symbol_set", None)

        queryset = self.queryset.filter(team_id=self.team.id).select_related("symbol_set__release")

        if raw_ids:
            query_id_objects = Q()
            for raw_id in raw_ids:
                hash_id, part = get_raw_id_part(raw_id)
                query_id_objects |= Q(raw_id=hash_id, part=part)

            queryset = queryset.filter(query_id_objects)

        if symbol_set:
            queryset = queryset.filter(symbol_set=symbol_set)

        serializer = self.get_serializer(queryset, many=True)
        return Response({"results": serializer.data})


def get_raw_id_part(raw_id):
    res = raw_id.split("/")
    if len(res) != 2:
        return raw_id, 0
    return res[0], int(res[1])


@extend_schema_tags(tags=[ProductKey.ERROR_TRACKING])
class ErrorTrackingSuppressionRuleViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet, RuleReorderingMixin):
    scope_object = "error_tracking"
    queryset = ErrorTrackingSuppressionRule.objects.order_by("order_key").all()
    serializer_class = ErrorTrackingSuppressionRuleSerializer

    @override
    def safely_get_queryset(self, queryset):
        return queryset.filter(team_id=self.team.id)

    @override
    def update(self, request, *args, **kwargs) -> Response:
        suppression_rule = self.get_object()
        json_filters = request.data.get("filters")

        if json_filters is not None:
            if _has_filter_values(json_filters):
                try:
                    parsed_filters = PropertyGroupFilterValue(**json_filters)
                except (PydanticValidationError, TypeError):
                    return Response({"error": "Invalid filters"}, status=status.HTTP_400_BAD_REQUEST)
                suppression_rule.filters = json_filters
                suppression_rule.bytecode = generate_byte_code(self.team, parsed_filters)
            else:
                suppression_rule.filters = json_filters
                suppression_rule.bytecode = generate_match_all_bytecode()
        if "sampling_rate" in request.data:
            sampling_rate = request.data["sampling_rate"]
            if not isinstance(sampling_rate, (int, float)) or not (0.0 <= sampling_rate <= 1.0):
                return Response(
                    {"error": "sampling_rate must be a number between 0 and 1"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            suppression_rule.sampling_rate = sampling_rate
        suppression_rule.disabled_data = None
        suppression_rule.save()

        posthoganalytics.capture(
            "error_tracking_suppression_rule_edited",
            groups=groups(self.team.organization, self.team),
        )

        return Response({"ok": True}, status=status.HTTP_204_NO_CONTENT)

    @override
    def partial_update(self, request, *args, **kwargs) -> Response:
        return self.update(request, *args, **kwargs)

    @override
    def destroy(self, request, *args, **kwargs) -> Response:
        response = super().destroy(request, *args, **kwargs)

        posthoganalytics.capture(
            "error_tracking_suppression_rule_deleted",
            groups=groups(self.team.organization, self.team),
        )

        return response

    @override
    def create(self, request, *args, **kwargs) -> Response:
        json_filters = request.data.get("filters")

        if json_filters is not None:
            if _has_filter_values(json_filters):
                try:
                    parsed_filters = PropertyGroupFilterValue(**json_filters)
                except (PydanticValidationError, TypeError):
                    return Response({"error": "Invalid filters"}, status=status.HTTP_400_BAD_REQUEST)
                bytecode = generate_byte_code(self.team, parsed_filters)
            elif "values" not in json_filters:
                return Response({"error": "Invalid filters"}, status=status.HTTP_400_BAD_REQUEST)
            else:
                bytecode = generate_match_all_bytecode()
        else:
            json_filters = {"type": "AND", "values": []}
            bytecode = generate_match_all_bytecode()

        sampling_rate = request.data.get("sampling_rate", 1.0)
        if not isinstance(sampling_rate, (int, float)) or not (0.0 <= sampling_rate <= 1.0):
            return Response(
                {"error": "sampling_rate must be a number between 0 and 1"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        suppression_rule = ErrorTrackingSuppressionRule.objects.create(
            team=self.team,
            filters=json_filters,
            bytecode=bytecode,
            order_key=0,
            sampling_rate=sampling_rate,
        )

        posthoganalytics.capture(
            "error_tracking_suppression_rule_created",
            groups=groups(self.team.organization, self.team),
        )

        serializer = ErrorTrackingSuppressionRuleSerializer(suppression_rule)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


# Properties that require server-side symbol resolution to have meaningful
# values. Client-side these will contain minified/bundled names.
SERVER_ONLY_PROPERTIES = frozenset({"$exception_sources", "$exception_functions"})


def _has_filter_values(json_filters: dict) -> bool:
    """Check whether a filter dict contains any actual filter values."""
    values = json_filters.get("values", [])
    if not values:
        return False
    # Check nested groups (the outer group wraps inner groups with actual filters)
    return any(v.get("values") or "key" in v for v in values)


def _get_client_safe_filters(filters: dict) -> dict | None:
    """Return the filters if every leaf is client-safe, otherwise None.

    If any filter in the tree uses a server-only property, the entire rule
    is not evaluated client-side.
    """
    for value in filters.get("values", []):
        if "key" in value:
            if value.get("key") in SERVER_ONLY_PROPERTIES:
                return None
        elif "values" in value:
            if _get_client_safe_filters(value) is None:
                return None
    return filters


def get_client_safe_suppression_rules(team: Team) -> list[dict]:
    rules = list(ErrorTrackingSuppressionRule.objects.filter(team=team).values_list("filters", "sampling_rate"))
    result = []
    for filters, sampling_rate in rules:
        safe = _get_client_safe_filters(filters)
        if safe is not None:
            rule_data = {**safe}
            if sampling_rate < 1.0:
                rule_data["samplingRate"] = sampling_rate
            result.append(rule_data)
    return result


@extend_schema_tags(tags=[ProductKey.ERROR_TRACKING])
class ErrorTrackingSymbolSetViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "error_tracking"
    queryset = ErrorTrackingSymbolSet.objects.all()
    serializer_class = ErrorTrackingSymbolSetSerializer
    parser_classes = [MultiPartParser, FileUploadParser]
    throttle_classes = [SymbolSetUploadBurstRateThrottle, SymbolSetUploadSustainedRateThrottle]
    scope_object_read_actions = ["list", "retrieve"]
    scope_object_write_actions = [
        "bulk_start_upload",
        "bulk_finish_upload",
        "start_upload",
        "finish_upload",
        "destroy",
        "bulk_delete",
        "create",
    ]

    def safely_get_queryset(self, queryset):
        queryset = queryset.filter(team_id=self.team.id).select_related("release")
        params = self.request.GET.dict()
        symbol_set_status = params.get("status")
        order_by = params.get("order_by")

        if symbol_set_status == "valid":
            queryset = queryset.filter(storage_ptr__isnull=False)
        elif symbol_set_status == "invalid":
            queryset = queryset.filter(storage_ptr__isnull=True)

        if order_by:
            allowed_fields = ["created_at", "-created_at", "ref", "-ref", "last_used", "-last_used"]
            if order_by in allowed_fields:
                queryset = queryset.order_by(order_by)

        return queryset

    def destroy(self, request, *args, **kwargs):
        symbol_set = self.get_object()
        symbol_set.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(methods=["POST"], detail=False, parser_classes=[JSONParser])
    def bulk_delete(self, request, **kwargs):
        ids = request.data.get("ids", [])
        if not ids:
            return Response({"detail": "ids is required"}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(ids, list):
            return Response({"detail": "ids must be a list"}, status=status.HTTP_400_BAD_REQUEST)
        symbol_sets = ErrorTrackingSymbolSet.objects.filter(team=self.team, id__in=ids)
        deleted_count, _ = symbol_sets.delete()
        return Response({"deleted": deleted_count}, status=status.HTTP_200_OK)

    def list(self, request, *args, **kwargs) -> Response:
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        # Fallback for non-paginated responses
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    # DEPRECATED: newer versions of the CLI use bulk uploads
    def create(self, request, *args, **kwargs) -> Response:
        # pull the symbol set reference from the query params
        chunk_id = request.query_params.get("chunk_id", None)
        multipart = request.query_params.get("multipart", False)
        release_id = request.query_params.get("release_id", None)

        posthoganalytics.capture(
            "error_tracking_symbol_set_deprecated_endpoint",
            distinct_id=request.user.pk,
            properties={"team_id": self.team.id, "endpoint": "create"},
        )

        if not chunk_id:
            return Response({"detail": "chunk_id query parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

        if multipart:
            data = bytearray()
            for chunk in request.FILES["file"].chunks():
                data.extend(chunk)
        else:
            # legacy: older versions of the CLI did not use multipart uploads
            # file added to the request data by the FileUploadParser
            data = request.data["file"].read()

        (storage_ptr, content_hash) = upload_content(bytearray(data))
        create_symbol_set(chunk_id, self.team, release_id, storage_ptr, content_hash)

        return Response({"ok": True}, status=status.HTTP_201_CREATED)

    @action(methods=["POST"], detail=False)
    # DEPRECATED: we should eventually remove this once everyone is using a new enough version of the CLI
    def start_upload(self, request, **kwargs):
        chunk_id = request.query_params.get("chunk_id", None)
        release_id = request.query_params.get("release_id", None)

        posthoganalytics.capture(
            "error_tracking_symbol_set_deprecated_endpoint",
            distinct_id=request.user.pk,
            properties={"team_id": self.team.id, "endpoint": "start_upload"},
        )

        if not settings.OBJECT_STORAGE_ENABLED:
            raise ValidationError(
                code="object_storage_required",
                detail="Object storage must be available to allow source map uploads.",
            )

        if not chunk_id:
            return Response({"detail": "chunk_id query parameter is required"}, status=status.HTTP_400_BAD_REQUEST)

        file_key = generate_symbol_set_file_key()
        presigned_url = object_storage.get_presigned_post(
            file_key=file_key,
            conditions=[["content-length-range", 0, ONE_HUNDRED_MEGABYTES]],
        )

        symbol_set = create_symbol_set(chunk_id, self.team, release_id, file_key)

        return Response(
            {"presigned_url": presigned_url, "symbol_set_id": str(symbol_set.pk)},
            status=status.HTTP_201_CREATED,
        )

    @action(methods=["PUT"], detail=True, parser_classes=[JSONParser])
    def finish_upload(self, request, **kwargs):
        content_hash = request.data.get("content_hash")

        if not content_hash:
            raise ValidationError(
                code="content_hash_required",
                detail="A content hash must be provided to complete symbol set upload.",
            )

        if not settings.OBJECT_STORAGE_ENABLED:
            raise ValidationError(
                code="object_storage_required",
                detail="Object storage must be available to allow source map uploads.",
            )

        symbol_set = self.get_object()
        s3_upload = object_storage.head_object(file_key=symbol_set.storage_ptr)

        if s3_upload:
            content_length = s3_upload.get("ContentLength")

            if not content_length or content_length > ONE_HUNDRED_MEGABYTES:
                symbol_set.delete()

                raise ValidationError(
                    code="file_too_large",
                    detail="The uploaded symbol set file was too large.",
                )
        else:
            raise ValidationError(
                code="file_not_found",
                detail="No file has been uploaded for the symbol set.",
            )

        if not symbol_set.content_hash:
            symbol_set.content_hash = content_hash
            symbol_set.last_used = timezone.now()
            symbol_set.save()

        return Response({"success": True}, status=status.HTTP_200_OK)

    @action(methods=["POST"], detail=False, parser_classes=[JSONParser])
    def bulk_start_upload(self, request, **kwargs):
        if request.user.pk:
            posthoganalytics.identify_context(request.user.pk)
        # Earlier ones send a list of chunk IDs, all associated with one release
        # Extract a list of chunk IDs from the request json
        chunk_ids: list[str] = request.data.get("chunk_ids") or []
        # Grab the release ID from the request json
        release_id: str | None = request.data.get("release_id", None)

        _ = posthoganalytics.capture(
            "error_tracking_symbol_set_upload_started",
            properties={"team_id": self.team.id, "endpoint": "bulk_start_upload"},
            groups=groups(self.team.organization, self.team),
        )

        # Validate symbol_sets using the serializer
        symbol_sets: list[SymbolSetUpload] = []
        if "symbol_sets" in request.data:
            chunk_serializer = ErrorTrackingSymbolSetUploadSerializer(data=request.data["symbol_sets"], many=True)
            _ = chunk_serializer.is_valid(raise_exception=True)
            symbol_sets = [SymbolSetUpload(**data) for data in chunk_serializer.validated_data]

        symbol_sets.extend([SymbolSetUpload(x, release_id, None) for x in chunk_ids])

        # force=True allows overwriting an existing symbol set whose content has changed.
        # Without it, changed-content re-uploads are silently skipped to prevent
        # accidental overwrites of production symbol sets from a local dev machine.
        force: bool = bool(request.data.get("force", False))

        if not settings.OBJECT_STORAGE_ENABLED:
            raise ValidationError(
                code="object_storage_required",
                detail="Object storage must be available to allow source map uploads.",
            )

        chunk_id_url_map = bulk_create_symbol_sets(
            symbol_sets,
            self.team,
            force=force,
            distinct_id=str(request.user.pk) if request.user.pk else None,
        )
        return Response({"id_map": chunk_id_url_map}, status=status.HTTP_201_CREATED)

    @action(methods=["POST"], detail=False, parser_classes=[JSONParser])
    def bulk_finish_upload(self, request, **kwargs):
        if request.user.pk:
            posthoganalytics.identify_context(request.user.pk)
        # Get the map of symbol_set_id:content_hashes
        content_hashes = request.data.get("content_hashes", {})
        if content_hashes is None:
            return Response({"detail": "content_hashes are required"}, status=status.HTTP_400_BAD_REQUEST)

        if len(content_hashes) == 0:
            # This can happen if someone re-runs an upload against a directory that's already been
            # uploaded - we'll return no new upload keys, they'll upload nothing, and then
            # we can early exit here.
            return Response({"success": True}, status=status.HTTP_201_CREATED)

        if not settings.OBJECT_STORAGE_ENABLED:
            raise ValidationError(
                code="object_storage_required",
                detail="Object storage must be available to allow source map uploads.",
            )

        file_count = len(content_hashes)
        symbol_set_ids = content_hashes.keys()
        symbol_sets = ErrorTrackingSymbolSet.objects.filter(team=self.team, id__in=symbol_set_ids)

        total_file_size = 0
        try:
            for symbol_set in symbol_sets:
                s3_upload = None
                if symbol_set.storage_ptr:
                    s3_upload = object_storage.head_object(file_key=symbol_set.storage_ptr)

                if s3_upload:
                    content_length = s3_upload.get("ContentLength")
                    if content_length:
                        total_file_size += content_length

                    if not content_length or content_length > ONE_HUNDRED_MEGABYTES:
                        symbol_set.delete()

                        raise ValidationError(
                            code="file_too_large",
                            detail="The uploaded symbol set file was too large.",
                        )
                else:
                    raise ValidationError(
                        code="file_not_found",
                        detail="No file has been uploaded for the symbol set.",
                    )

                content_hash = content_hashes[str(symbol_set.id)]
                symbol_set.content_hash = content_hash
                symbol_set.last_used = timezone.now()
            ErrorTrackingSymbolSet.objects.bulk_update(symbol_sets, ["content_hash", "last_used"])
        except Exception as error:
            for symbol_set_id in content_hashes.keys():
                # Try to clean up the symbol sets preemptively if the upload fails
                try:
                    symbol_set = ErrorTrackingSymbolSet.objects.all().filter(id=symbol_set_id, team=self.team).get()
                    symbol_set.delete()
                except Exception:
                    pass

            posthoganalytics.capture(
                "error_tracking_symbol_set_uploaded",
                properties={
                    "file_size": total_file_size,
                    "success": False,
                    "file_count": file_count,
                    "failure_reason": type(error).__name__,
                },
                groups=groups(self.team.organization, self.team),
            )
            raise

        posthoganalytics.capture(
            "error_tracking_symbol_set_uploaded",
            properties={
                "file_size": total_file_size,
                "success": True,
                "file_count": file_count,
            },
            groups=groups(self.team.organization, self.team),
        )

        return Response({"success": True}, status=status.HTTP_201_CREATED)


def create_symbol_set(
    chunk_id: str,
    team: Team,
    release_id: str | None,
    storage_ptr: str,
    content_hash: str | None = None,
):
    if release_id:
        objects = ErrorTrackingRelease.objects.all().filter(team=team, id=release_id)
        if len(objects) < 1:
            raise ValueError(f"Unknown release: {release_id}")
        release = objects[0]
    else:
        release = None

    with transaction.atomic():
        try:
            symbol_set = ErrorTrackingSymbolSet.objects.get(team=team, ref=chunk_id)
            if symbol_set.release is None:
                symbol_set.release = release
            elif symbol_set.release != release:
                raise ValidationError("Symbol set has already been uploaded for a different release")
            symbol_set.storage_ptr = storage_ptr
            symbol_set.content_hash = content_hash
            symbol_set.last_used = timezone.now()
            symbol_set.save()

        except ErrorTrackingSymbolSet.DoesNotExist:
            symbol_set = ErrorTrackingSymbolSet.objects.create(
                team=team,
                ref=chunk_id,
                release=release,
                storage_ptr=storage_ptr,
                content_hash=content_hash,
                last_used=timezone.now(),
            )

        # Delete any existing frames associated with this symbol set
        ErrorTrackingStackFrame.objects.filter(team=team, symbol_set=symbol_set).delete()

        return symbol_set


@posthoganalytics.scoped()
def bulk_create_symbol_sets(
    new_symbol_sets: list[SymbolSetUpload],
    team: Team,
    force: bool = False,
    distinct_id: str | None = None,
) -> dict[str, dict[str, str]]:
    accelerate = bool(
        distinct_id
        and posthoganalytics.feature_enabled(
            "error-tracking-s3-accelerate",
            distinct_id,
            groups={"organization": str(team.organization.id)},
            send_feature_flag_events=False,
        )
    )

    chunk_ids = [x.chunk_id for x in new_symbol_sets]

    # Check for dupes
    duplicates = [x for x in chunk_ids if chunk_ids.count(x) > 1]
    if duplicates:
        raise ValidationError(
            code="invalid_chunk_ids",
            detail=f"Duplicate chunk IDs provided: {', '.join(duplicates)}",
        )

    # Check we're using all valid release IDs
    release_ids = {ss.release_id for ss in new_symbol_sets if ss.release_id}
    fetched_releases = {str(r.id) for r in ErrorTrackingRelease.objects.all().filter(team=team, pk__in=release_ids)}
    for release_id in release_ids:
        if release_id not in fetched_releases:
            raise ValidationError(
                code="invalid_release_id",
                detail=f"Unknown release ID provided: {release_id}",
            )

    id_url_map: dict[str, dict[str, str]] = {}
    new_symbol_set_map = {x.chunk_id: x for x in new_symbol_sets}

    with transaction.atomic():
        existing_symbol_sets = list(ErrorTrackingSymbolSet.objects.filter(team=team, ref__in=chunk_ids))
        existing_symbol_set_refs = [s.ref for s in existing_symbol_sets]
        missing_sets = list(set(chunk_ids) - set(existing_symbol_set_refs))

        symbol_sets_to_be_created = []
        for chunk_id in missing_sets:
            storage_ptr = generate_symbol_set_file_key()
            presigned_url = generate_symbol_set_upload_presigned_url(storage_ptr, accelerate=accelerate)
            id_url_map[chunk_id] = {"presigned_url": presigned_url}
            # Note that on creation, we /do not set/ the content hash. We use content hashes included in
            # the create request only to see if we can skip updated - we set the content hash when we
            # get upload confirmation, during `bulk_finish_upload`, not before
            to_create = ErrorTrackingSymbolSet(
                team=team,
                ref=chunk_id,
                storage_ptr=storage_ptr,
                release_id=new_symbol_set_map[chunk_id].release_id,
                last_used=timezone.now(),
            )
            symbol_sets_to_be_created.append(to_create)

        # create missing symbol sets
        created_symbol_sets = ErrorTrackingSymbolSet.objects.bulk_create(symbol_sets_to_be_created)

        for symbol_set in created_symbol_sets:
            id_url_map[symbol_set.ref]["symbol_set_id"] = str(symbol_set.pk)

        # update existing symbol sets
        to_update = []
        for existing in existing_symbol_sets:
            upload = new_symbol_set_map[existing.ref]
            dirty = False

            # Allow adding an "orphan" symbol set to a release, but not
            # moving symbols sets between releases
            if upload.release_id:
                if existing.release_id is None:
                    existing.release_id = upload.release_id
                    dirty = True
                elif str(existing.release_id) != upload.release_id:
                    raise ValidationError(
                        code="release_id_mismatch",
                        detail=f"Symbol set {existing.ref} already has a release ID",
                    )

            if upload.content_hash is None:
                if existing.content_hash is not None:
                    # Old CLI (no content hash) trying to re-upload a symbol set
                    # that was already fully uploaded. We can't determine safety,
                    # so reject rather than silently overwrite production data.
                    raise ValidationError(
                        code="content_hash_required",
                        detail=f"Symbol set {existing.ref} already has content; provide a content_hash to update it.",
                    )
                # Both sides have no hash: this is a pending upload being restarted.
                # Issue a fresh presigned URL so the client can retry.
                storage_ptr = generate_symbol_set_file_key()
                presigned_url = generate_symbol_set_upload_presigned_url(storage_ptr, accelerate=accelerate)
                id_url_map[existing.ref] = {
                    "presigned_url": presigned_url,
                    "symbol_set_id": str(existing.id),
                }
                existing.storage_ptr = storage_ptr
                dirty = True
            elif existing.content_hash is None:
                # Existing record has no hash (pending upload or uploaded by old CLI
                # without hash support). Allow the new upload to supply one.
                storage_ptr = generate_symbol_set_file_key()
                presigned_url = generate_symbol_set_upload_presigned_url(storage_ptr, accelerate=accelerate)
                id_url_map[existing.ref] = {
                    "presigned_url": presigned_url,
                    "symbol_set_id": str(existing.id),
                }
                existing.storage_ptr = storage_ptr
                dirty = True
            elif existing.content_hash == upload.content_hash:
                # Content is identical — no upload needed.
                # (We may still update the release below if it changed.)
                pass
            elif not force:
                # Content has changed but the caller did not pass force=True.
                # Silently skip to prevent accidental overwrites of production
                # symbol sets from a local development machine.
                logger.warning(
                    "symbol_set_content_changed_skipped",
                    ref=existing.ref,
                    team_id=team.id,
                )
            else:
                # force=True: content has changed and the caller explicitly
                # requested an overwrite. Issue a new presigned URL and clear
                # the old content hash so bulk_finish_upload stores the new one.
                storage_ptr = generate_symbol_set_file_key()
                presigned_url = generate_symbol_set_upload_presigned_url(storage_ptr, accelerate=accelerate)
                id_url_map[existing.ref] = {
                    "presigned_url": presigned_url,
                    "symbol_set_id": str(existing.id),
                }
                existing.storage_ptr = storage_ptr
                existing.content_hash = None  # will be set by bulk_finish_upload
                dirty = True

            if dirty:
                to_update.append(existing)

        # We update only the symbol sets we modified the release of - for all others, this is a no-op (we assume they were uploaded
        # during a prior attempt or something).
        _ = ErrorTrackingSymbolSet.objects.bulk_update(to_update, ["release", "content_hash", "storage_ptr"])

    return id_url_map


def upload_content(content: bytearray) -> tuple[str, str]:
    content_hash = hashlib.sha512(content).hexdigest()

    if not settings.OBJECT_STORAGE_ENABLED:
        raise ValidationError(
            code="object_storage_required",
            detail="Object storage must be available to allow source map uploads.",
        )

    if len(content) > ONE_HUNDRED_MEGABYTES:
        raise ValidationError(
            code="file_too_large",
            detail="Combined source map and symbol set must be less than 100MB",
        )

    upload_path = generate_symbol_set_file_key()
    object_storage.write(upload_path, bytes(content))
    return (upload_path, content_hash)


def construct_js_data_object(minified: bytes, source_map: bytes) -> bytearray:
    # See rust/cymbal/hacks/js_data.rs
    data = bytearray()
    data.extend(JS_DATA_MAGIC)
    data.extend(JS_DATA_VERSION.to_bytes(4, "little"))
    data.extend((JS_DATA_TYPE_SOURCE_AND_MAP).to_bytes(4, "little"))
    # TODO - this doesn't seem right?
    s_bytes = minified.decode("utf-8").encode("utf-8")
    data.extend(len(s_bytes).to_bytes(8, "little"))
    data.extend(s_bytes)
    sm_bytes = source_map.decode("utf-8").encode("utf-8")
    data.extend(len(sm_bytes).to_bytes(8, "little"))
    data.extend(sm_bytes)
    return data


def generate_symbol_set_file_key():
    return f"{settings.OBJECT_STORAGE_ERROR_TRACKING_SOURCE_MAPS_FOLDER}/{str(uuid7())}"


def generate_symbol_set_upload_presigned_url(file_key: str, *, accelerate: bool = False):
    if accelerate:
        return object_storage.get_accelerated_presigned_post(
            file_key=file_key,
            conditions=[["content-length-range", 0, ONE_HUNDRED_MEGABYTES]],
            expiration=PRESIGNED_MULTIPLE_UPLOAD_TIMEOUT,
        )
    return object_storage.get_presigned_post(
        file_key=file_key,
        conditions=[["content-length-range", 0, ONE_HUNDRED_MEGABYTES]],
        expiration=PRESIGNED_MULTIPLE_UPLOAD_TIMEOUT,
    )


def prepare_github_search_query(q: str | None) -> str:
    if not q:
        return ""

    result = []
    in_quotes = False
    quote_char = None

    for char in q:
        if char in ('"', "'", "`") and not in_quotes:
            in_quotes = True
            quote_char = char
            result.append(char)
        elif char == quote_char and in_quotes:
            in_quotes = False
            quote_char = None
            result.append(char)
        elif in_quotes:
            result.append(char)
        elif char in ".,:;/\\=*!?#$&+^|~<>(){}[]":
            result.append(" ")
        else:
            result.append(char)

    return " ".join("".join(result).split())


def prepare_gitlab_search_query(q: str | None) -> str:
    """Sanitize code sample for GitLab search by removing special characters."""
    if not q:
        return ""

    result = []
    for char in q:
        if char in ".,:;/\\=*!?#$&+^|~<>(){}[]\"'`":
            result.append(" ")
        else:
            result.append(char)

    return " ".join("".join(result).split())


def get_github_file_url(code_sample: str, token: str, owner: str, repository: str, file_name: str) -> str | None:
    """Search GitHub code using the Code Search API. Returns URL to first match or None."""
    code_query = prepare_github_search_query(code_sample)
    search_query = f"{code_query} repo:{owner}/{repository} filename:{file_name}"
    encoded_query = urllib.parse.quote(search_query)
    url = f"https://api.github.com/search/code?q={encoded_query}"

    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.text-match+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    try:
        response = requests.get(url, headers=headers, timeout=10)

        if response.status_code == 200:
            data = response.json()
            items = data.get("items", [])
            if items:
                return items[0].get("html_url")
            return None

        logger.warning("github_code_search_failed", status_code=response.status_code)
        return None
    except Exception as error:
        logger.exception("github_code_search_request_failed", error=str(error))
        return None


def get_gitlab_file_url(
    code_sample: str,
    token: str,
    owner: str,
    repository: str,
    file_name: str,
    gitlab_url: str = "https://gitlab.com",
) -> str | None:
    """Search GitLab code using the Search API. Returns URL to first match or None."""
    project_path = f"{owner}/{repository}"
    encoded_project_path = urllib.parse.quote(project_path, safe="")
    search_scope = "blobs"

    headers = {
        "PRIVATE-TOKEN": token,
        "Content-Type": "application/json",
    }

    # GitLab search behavior varies depending on repo visibility and current plan. Seems like under some conditions
    # the search uses different engine - it is not documented so I decided to run multiple searches just to be safe
    search_variants = [
        code_sample.strip(),
        prepare_gitlab_search_query(code_sample),
    ]

    def execute_single_search_variant(search_query: str) -> str | None:
        if not search_query:
            return None

        encoded_search = urllib.parse.quote(search_query)
        url = f"{gitlab_url}/api/v4/projects/{encoded_project_path}/search?scope={search_scope}&search={encoded_search}"

        try:
            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code == 200:
                data = response.json()
                if data:
                    for item in data:
                        item_path = item.get("path", "")
                        if file_name in item_path:
                            ref = item.get("ref", "")
                            if ref and item_path:
                                return f"{gitlab_url}/{owner}/{repository}/-/blob/{ref}/{item_path}"
        except Exception as error:
            logger.exception("gitlab_code_search_request_failed", error=str(error))

        return None

    with ThreadPoolExecutor(max_workers=len(search_variants)) as executor:
        future_to_variant = {
            executor.submit(execute_single_search_variant, variant): variant for variant in search_variants
        }

        for future in as_completed(future_to_variant):
            resolved_url = future.result()
            if resolved_url:
                return resolved_url

    return None


class GitProviderFileLinksViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "error_tracking"

    @action(methods=["GET"], detail=False, url_path="resolve_github")
    def resolve_github(self, request, **kwargs):
        owner = request.GET.get("owner")
        repository = request.GET.get("repository")
        code_sample = request.GET.get("code_sample")
        file_name = request.GET.get("file_name")

        if not owner or not repository or not code_sample or not file_name:
            return Response({"found": False, "error": "owner, repository, code_sample, and file_name are required"})

        url = None

        # Try with posthogs token first (public repos)
        if settings.GITHUB_TOKEN:
            url = get_github_file_url(
                code_sample=code_sample,
                token=settings.GITHUB_TOKEN,
                owner=owner,
                repository=repository,
                file_name=file_name,
            )
            if url:
                return Response({"found": True, "url": url})

        # Try with assigned github integration (private repos)
        integration = Integration.objects.filter(team_id=self.team.id, kind="github").first()

        if integration:
            github = GitHubIntegration(integration)

            if github.access_token_expired():
                github.refresh_access_token()

            token = github.integration.sensitive_config.get("access_token")
            if token:
                url = get_github_file_url(
                    code_sample=code_sample,
                    token=token,
                    owner=owner,
                    repository=repository,
                    file_name=file_name,
                )
                if url:
                    return Response({"found": True, "url": url})

        return Response({"found": False})

    @action(methods=["GET"], detail=False, url_path="resolve_gitlab")
    def resolve_gitlab(self, request, **kwargs):
        owner = request.GET.get("owner")
        repository = request.GET.get("repository")
        code_sample = request.GET.get("code_sample")
        file_name = request.GET.get("file_name")

        if not owner or not repository or not code_sample or not file_name:
            return Response({"found": False, "error": "owner, repository, code_sample, and file_name are required"})

        # Try with PostHog's token first (public repos on gitlab.com)
        if settings.GITLAB_TOKEN:
            url = get_gitlab_file_url(
                code_sample=code_sample,
                token=settings.GITLAB_TOKEN,
                owner=owner,
                repository=repository,
                file_name=file_name,
                gitlab_url="https://gitlab.com",
            )

            if url:
                return Response({"found": True, "url": url})

        # Try with team's GitLab integrations (private repos and self-hosted)
        integrations = Integration.objects.filter(team_id=self.team.id, kind="gitlab")

        if not integrations:
            return Response({"found": False})

        def try_integration(integration: Integration) -> str | None:
            try:
                gitlab = GitLabIntegration(integration)
                hostname = gitlab.hostname
                token = gitlab.integration.sensitive_config.get("access_token")

                if token:
                    return get_gitlab_file_url(
                        code_sample=code_sample,
                        token=token,
                        owner=owner,
                        repository=repository,
                        file_name=file_name,
                        gitlab_url=hostname,
                    )
            except Exception:
                return None
            return None

        with ThreadPoolExecutor(max_workers=min(len(integrations), 5)) as executor:
            future_to_integration = {
                executor.submit(try_integration, integration): integration for integration in integrations
            }

            for future in as_completed(future_to_integration):
                resolved_url = future.result()
                if resolved_url:
                    return Response({"found": True, "url": resolved_url})

        return Response({"found": False})
