import json
from datetime import datetime
from typing import Any, Optional

from django.db import transaction
from django.http import JsonResponse

import structlog
import posthoganalytics
from loginas.utils import is_impersonated_session
from rest_framework import request, serializers, status, viewsets
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import action
from posthog.models.activity_logging.activity_log import Change, Detail, load_activity, log_activity
from posthog.models.activity_logging.activity_page import activity_page_response
from posthog.models.plugin import sync_execute
from posthog.tasks.email import send_error_tracking_issue_assigned

from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueFingerprintV2,
    resolve_fingerprints_for_issues,
)

from .external_references import ErrorTrackingExternalReferenceSerializer
from .utils import ErrorTrackingIssueAssignmentSerializer

# Error tracking embedding configuration defaults
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

    def _get_issue_embeddings(self, issue_fingerprints: list[str], model_name: str, embedding_version: int):
        """Get embeddings along with model info for given fingerprints."""
        query = """
            SELECT DISTINCT embeddings
            FROM error_tracking_issue_fingerprint_embeddings
            WHERE team_id = %(team_id)s
            AND fingerprint IN %(fingerprints)s
            AND model_name = %(model_name)s
            AND embedding_version = %(embedding_version)s
        """

        issue_embeddings = sync_execute(
            query,
            {
                "team_id": self.team.pk,
                "fingerprints": issue_fingerprints,
                "model_name": model_name,
                "embedding_version": embedding_version,
            },
        )

        return issue_embeddings

    def _get_similar_embeddings(
        self,
        embedding_vector,
        model_name: str,
        embedding_version: int,
        issue_fingerprints: list[str],
        min_distance_threshold: float,
    ):
        """Get similar embeddings using cosine similarity."""
        query = """
              WITH %(target_embedding)s as target
            SELECT fingerprint, MIN(cosineDistance(embeddings, target)) as distance
              FROM error_tracking_issue_fingerprint_embeddings
             WHERE team_id = %(team_id)s
               AND model_name = %(model_name)s
               AND embedding_version = %(embedding_version)s
               AND fingerprint NOT IN %(fingerprints)s
               AND length(embeddings) = length(target)
             GROUP BY fingerprint
            HAVING distance <= %(min_distance_threshold)s
             ORDER BY distance ASC
             LIMIT 10;
        """

        similar_embeddings = sync_execute(
            query,
            {
                "team_id": self.team.pk,
                "target_embedding": embedding_vector,
                "model_name": model_name,
                "embedding_version": embedding_version,
                "fingerprints": issue_fingerprints,
                "min_distance_threshold": min_distance_threshold,
            },
        )
        return similar_embeddings

    def _get_embedding_configuration(self) -> tuple[float, str, int]:
        """Get embedding configuration from feature flag or return defaults."""
        min_distance_threshold = DEFAULT_MIN_DISTANCE_THRESHOLD
        model_name = DEFAULT_EMBEDDING_MODEL_NAME
        embedding_version = DEFAULT_EMBEDDING_VERSION

        # Try to get configuration from feature flag, fall back to defaults if not available
        try:
            team_id = str(self.team.id)
            config_json = posthoganalytics.get_feature_flag_payload("error-tracking-embedding-configuration", team_id)
            if config_json:
                config_payload = json.loads(config_json)

                # Validate that config_payload is a dict
                if config_payload and isinstance(config_payload, dict):
                    min_distance_threshold = config_payload.get(
                        "min_distance_threshold", DEFAULT_MIN_DISTANCE_THRESHOLD
                    )
                    model_name = config_payload.get("model_name", DEFAULT_EMBEDDING_MODEL_NAME)
                    embedding_version = config_payload.get("embedding_version", DEFAULT_EMBEDDING_VERSION)

                    # Validate types
                    if not isinstance(min_distance_threshold, (int | float)):
                        min_distance_threshold = DEFAULT_MIN_DISTANCE_THRESHOLD
                    if not isinstance(model_name, str):
                        model_name = DEFAULT_EMBEDDING_MODEL_NAME
                    if not isinstance(embedding_version, int):
                        embedding_version = DEFAULT_EMBEDDING_VERSION
        except Exception:
            # Fall back to defaults on any error (JSON parsing, network, etc.)
            min_distance_threshold = DEFAULT_MIN_DISTANCE_THRESHOLD
            model_name = DEFAULT_EMBEDDING_MODEL_NAME
            embedding_version = DEFAULT_EMBEDDING_VERSION

        return min_distance_threshold, model_name, embedding_version

    def _get_issues_library_data(
        self,
        fingerprints: list[str],
        earliest_timestamp: Optional[datetime] = None,
        latest_timestamp: Optional[datetime] = None,
    ) -> dict[str, str]:
        """Get library information for fingerprints from ClickHouse events."""
        params: dict[str, Any] = {}
        params["team_id"] = self.team.pk
        params["fingerprints"] = fingerprints

        timestamp_filter = ""
        if earliest_timestamp and latest_timestamp:
            timestamp_filter = "AND timestamp >= %(earliest_timestamp)s AND timestamp <= %(latest_timestamp)s"
            params["earliest_timestamp"] = earliest_timestamp
            params["latest_timestamp"] = latest_timestamp
        elif earliest_timestamp:
            timestamp_filter = "AND timestamp >= %(earliest_timestamp)s"
            params["earliest_timestamp"] = earliest_timestamp
        elif latest_timestamp:
            timestamp_filter = "AND timestamp <= %(latest_timestamp)s"
            params["latest_timestamp"] = latest_timestamp

        query = f"""
            SELECT mat_$exception_fingerprint, MIN(mat_$lib)
              FROM events
             WHERE team_id = %(team_id)s
               AND event = '$exception'
               AND mat_$exception_fingerprint IN %(fingerprints)s
               AND mat_$lib != ''
               {timestamp_filter}
             GROUP BY mat_$exception_fingerprint
        """

        results = sync_execute(
            query,
            params,
        )

        if not results or len(results) == 0:
            return {}
        # Return dict mapping fingerprint to library
        return dict(results)

    def _build_issue_to_library_mapping(
        self, issue_id_to_fingerprint: dict[str, str], fingerprint_to_library: dict[str, str]
    ) -> dict[str, str]:
        """Build mapping from issue_id to library using existing data."""
        if not fingerprint_to_library or len(fingerprint_to_library) == 0:
            return {}

        issue_to_library = {}
        # Map each issue to library data using fingerprints
        for issue_id, fingerprint in issue_id_to_fingerprint.items():
            if fingerprint in fingerprint_to_library:
                issue_to_library[issue_id] = fingerprint_to_library[fingerprint]
        return issue_to_library

    def _get_timestamp_range(self, issues) -> tuple[Optional[datetime], Optional[datetime]]:
        """Calculate timestamp range from issues for query optimization."""
        issue_timestamps = [issue.created_at for issue in issues if issue.created_at is not None]
        if issue_timestamps:
            earliest_timestamp = min(issue_timestamps)
            latest_timestamp = max(issue_timestamps)
        else:
            earliest_timestamp = None
            latest_timestamp = None
        return earliest_timestamp, latest_timestamp

    def _serialize_issues_to_similar_issues(self, issues, library_data: dict[str, str]):
        """Serialize ErrorTrackingIssue objects to similar issues format."""

        return [
            {
                "id": issue.id,
                "title": issue.name,
                "description": issue.description,
                **({} if str(issue.id) not in library_data else {"library": library_data[str(issue.id)]}),
            }
            for issue in issues
        ]

    def _process_embeddings_for_similarity(
        self,
        issue_embeddings,
        issue_fingerprints: list[str],
        min_distance_threshold: float,
        model_name: str,
        embedding_version: int,
    ) -> list[str]:
        """Process all embeddings to find similar fingerprints and return top 10 most similar."""
        similar_fingerprints = []

        # Search for similarities across all embeddings from the current issue
        for _, embedding_row in enumerate(issue_embeddings):
            embedding = embedding_row[0]  # Get the embedding vector

            # Search for similar embeddings using cosine similarity
            similar_embeddings = self._get_similar_embeddings(
                embedding, model_name, embedding_version, issue_fingerprints, min_distance_threshold
            )

            if not similar_embeddings or len(similar_embeddings) == 0:
                continue

            # Collect both fingerprint and distance
            for similar_embedding_row in similar_embeddings:
                fingerprint, distance = similar_embedding_row[0], similar_embedding_row[1]
                similar_fingerprints.append((fingerprint, distance))

        if not similar_fingerprints or len(similar_fingerprints) == 0:
            return []

        # Remove duplicates by fingerprint, keeping the best (smallest) distance for each
        fingerprint_best_distance: dict[str, float] = {}
        for fingerprint, distance in similar_fingerprints:
            if fingerprint not in fingerprint_best_distance or distance < fingerprint_best_distance[fingerprint]:
                fingerprint_best_distance[fingerprint] = distance

        if not fingerprint_best_distance or len(fingerprint_best_distance) == 0:
            return []

        # Sort by distance (ascending - smaller distance = more similar) and take top 10
        sorted_fingerprint_best_distance = sorted(fingerprint_best_distance.items(), key=lambda x: x[1])[:10]
        all_similar_fingerprints = [fingerprint for fingerprint, _ in sorted_fingerprint_best_distance]

        return all_similar_fingerprints

    @action(methods=["GET"], detail=True)
    def similar_issues(self, request: request.Request, **kwargs):
        issue_id = kwargs.get("pk")

        if not issue_id:
            return Response({"error": "issue_id is required"}, status=status.HTTP_400_BAD_REQUEST)

        issue_ids = [issue_id]
        issue_fingerprints = resolve_fingerprints_for_issues(team_id=self.team.pk, issue_ids=issue_ids)

        if not issue_fingerprints or len(issue_fingerprints) == 0:
            return Response([])

        # Get model configuration from feature flag
        min_distance_threshold, model_name, embedding_version = self._get_embedding_configuration()

        issue_embeddings = self._get_issue_embeddings(issue_fingerprints, model_name, embedding_version)

        if not issue_embeddings or len(issue_embeddings) == 0:
            return Response([])

        similar_fingerprints = self._process_embeddings_for_similarity(
            issue_embeddings, issue_fingerprints, min_distance_threshold, model_name, embedding_version
        )

        if not similar_fingerprints or len(similar_fingerprints) == 0:
            return Response([])

        # Get issue IDs that have these fingerprints
        fingerprint_issue_pairs = ErrorTrackingIssueFingerprintV2.objects.filter(
            team_id=self.team.pk, fingerprint__in=similar_fingerprints
        ).values_list("issue_id", "fingerprint")

        if not fingerprint_issue_pairs or len(fingerprint_issue_pairs) == 0:
            return Response([])

        # Create dict with issue_id as key and fingerprint as value
        issue_id_to_fingerprint = {str(issue_id): fingerprint for issue_id, fingerprint in fingerprint_issue_pairs}

        if not issue_id_to_fingerprint or len(issue_id_to_fingerprint) == 0:
            return Response([])

        # Get the actual issues from PostgreSQL
        issues = ErrorTrackingIssue.objects.filter(team=self.team, id__in=issue_id_to_fingerprint.keys())

        if not issues or len(issues) == 0:
            return Response([])

        # Calculate timestamp range from the issues to optimize the ClickHouse query
        earliest_timestamp, latest_timestamp = self._get_timestamp_range(issues)

        # Get library data for the similar fingerprints with timestamp range filter for performance
        fingerprint_to_library = self._get_issues_library_data(
            similar_fingerprints, earliest_timestamp, latest_timestamp
        )

        # Build mapping from issue_id to library using existing data
        issue_to_library = self._build_issue_to_library_mapping(issue_id_to_fingerprint, fingerprint_to_library)

        similar_issues = self._serialize_issues_to_similar_issues(issues, issue_to_library)
        return Response(similar_issues)

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

        issue_values = []
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
