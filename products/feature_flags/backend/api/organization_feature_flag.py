import re
import copy
from dataclasses import dataclass
from typing import Any, NamedTuple, cast

from django.db import IntegrityError, transaction
from django.db.models import Case, IntegerField, Q, QuerySet, Value, When

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.utils.urls import replace_query_param

from posthog.api.cohort import CohortSerializer
from posthog.api.documentation import _FallbackSerializer, extend_schema
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import ErrorResponseSerializer, action
from posthog.constants import AvailableFeature
from posthog.models import Team, User
from posthog.models.filters.filter import Filter
from posthog.rbac.user_access_control import UserAccessControl, access_level_satisfied_for_resource
from posthog.user_permissions import UserPermissions
from posthog.utils import safe_int

from products.approvals.backend.exceptions import ApprovalRequired, PolicyConflict
from products.approvals.backend.scheduled_changes import gate_scheduled_change
from products.cohorts.backend.models.cohort import Cohort, CohortOrEmpty
from products.cohorts.backend.models.util import get_all_cohort_dependencies, sort_cohorts_topologically
from products.feature_flags.backend.api.feature_flag import FeatureFlagSerializer
from products.feature_flags.backend.encrypted_flag_payloads import (
    get_decrypted_flag_payloads,
    get_decrypted_flag_payloads_protected,
)
from products.feature_flags.backend.flag_analytics import get_cached_evaluations_7d_by_team
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.models.scheduled_change import ScheduledChange

MAX_COPY_DEPENDENCY_FLAGS = 50
RESTRICTED_TARGET_DEPENDENCY_WARNING = (
    "Cannot automatically copy dependencies because one or more matching target dependency flags are restricted."
)
RESTRICTED_TARGET_DEPENDENCY_REMAP_WARNING = (
    "Removed one or more flag dependencies because matching target flags are restricted in the target project."
)
TARGET_COPY_PERMISSION_ERROR = "You do not have permission to copy flags to this project."
SOURCE_DEPENDENCY_COPY_PERMISSION_ERROR = "You do not have permission to copy one or more dependency flags."
SCHEDULED_DEPENDENCY_COPY_PERMISSION_ERROR = (
    "You do not have permission to copy one or more scheduled flag dependencies."
)
TARGET_DEPENDENCY_CREATE_PERMISSION_WARNING = "Cannot automatically copy dependencies because you do not have permission to create feature flags in one or more target projects."
EXISTING_TARGET_SCHEDULE_DEPENDENCY_WARNING = "Pending scheduled changes already attached to the target flag were left unchanged and may change this copied flag later."


@dataclass(frozen=True)
class DependencyCopyGraph:
    dependency_flags: list[FeatureFlag]
    root_dependency_flag_ids: list[int]
    dependency_edges: dict[int, set[int]]


@dataclass(frozen=True)
class DependencyCopyTargetRequirements:
    can_copy_dependencies: bool
    copied_dependency_keys: list[str]
    reused_dependency_keys: list[str]
    warnings: list[str]
    reason: str


@dataclass(frozen=True)
class TargetFlagAccessContext:
    flags_by_key: dict[str, FeatureFlag]
    restricted_keys: set[str]


class _DependencyCopyDecision(NamedTuple):
    can_copy: bool
    keys_to_copy: set[str]
    keys_to_reuse: set[str]


@dataclass(frozen=True)
class ScheduledChangeDependencyContext:
    source_dependency_keys: dict[str, str]
    disabled_source_dependency_keys: set[str]
    error_message: str | None = None


@dataclass(frozen=True)
class FeatureFlagCopySourceContext:
    source_dependency_keys: dict[str, str]
    disabled_source_dependency_keys: set[str]
    seen_cohorts_cache: dict[int, CohortOrEmpty]
    sorted_cohort_ids: list[int]
    source_schedules: list[ScheduledChange]
    schedule_dependency_contexts_by_id: dict[int, ScheduledChangeDependencyContext]


class CopyFlagsRequestSerializer(serializers.Serializer):
    feature_flag_key = serializers.CharField(required=True, help_text="Key of the feature flag to copy")
    from_project = serializers.IntegerField(required=True, help_text="Source project ID to copy the flag from")
    target_project_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=True,
        max_length=50,
        min_length=1,
        help_text="List of target project IDs to copy the flag to",
    )
    copy_schedule = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Whether to also copy scheduled changes for this flag",
    )
    disable_copied_flag = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Whether to force the copied flag to be disabled in target projects, ignoring the source flag's enabled status",
    )
    copy_dependencies = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Whether to also copy missing feature flags that this flag depends on",
    )


class CopyFlagsResultSerializer(serializers.Serializer):
    project_id = serializers.IntegerField(required=False, help_text="Project ID (present on failure)")
    error_message = serializers.CharField(required=False, help_text="Error message (present on failure)")


class CopyFlagsSuccessItemSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="ID of the created feature flag")
    key = serializers.CharField(help_text="Key of the feature flag")
    name = serializers.CharField(help_text="Name of the feature flag")
    active = serializers.BooleanField(help_text="Whether the flag is active")
    team_id = serializers.IntegerField(help_text="Team ID the flag was copied to")
    flag_dependency_warnings = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Warnings for flag dependencies that were dropped because no matching active flag exists in the target project",
    )
    schedule_copy_warning = serializers.CharField(
        required=False,
        help_text="Warning emitted when schedules failed to copy or existing target schedules may affect the copied flag",
    )
    copied_dependency_keys = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Dependency flag keys that were copied before this flag",
    )
    dependency_copy_warnings = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Warnings emitted while copying dependency flags",
    )


class CopyFlagsResponseSerializer(serializers.Serializer):
    success = CopyFlagsSuccessItemSerializer(many=True, help_text="List of successfully copied flags")
    failed = CopyFlagsResultSerializer(many=True, help_text="List of failed copy attempts")


class CopyFlagsDependencyRequirementsRequestSerializer(serializers.Serializer):
    feature_flag_key = serializers.CharField(required=True, help_text="Key of the feature flag to check")
    from_project = serializers.IntegerField(required=True, help_text="Source project ID to copy the flag from")
    target_project_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=True,
        max_length=50,
        min_length=1,
        help_text="List of target project IDs to check dependency copy eligibility for",
    )


class CopyFlagsDependencyRequirementsResponseSerializer(serializers.Serializer):
    can_copy_dependencies = serializers.BooleanField(help_text="Whether dependencies can be automatically copied")
    dependency_count = serializers.IntegerField(help_text="Total number of transitive source dependency flags")
    copied_dependency_keys = serializers.ListField(
        child=serializers.CharField(),
        help_text="Dependency flag keys that would be copied because they are missing from a target project",
    )
    reused_dependency_keys = serializers.ListField(
        child=serializers.CharField(),
        help_text="Dependency flag keys that already have an active same-key flag in every target project",
    )
    warnings = serializers.ListField(
        child=serializers.CharField(),
        help_text="Reasons dependency copying is unavailable or needs user attention",
    )
    reason = serializers.CharField(allow_blank=True, help_text="Primary human-readable eligibility result")


class OrganizationFeatureFlagRowSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="ID of the representative feature flag for this key")
    team_id = serializers.IntegerField(help_text="Team ID the representative feature flag belongs to")
    key = serializers.CharField(help_text="Feature flag key, unique within the compared projects")
    name = serializers.CharField(allow_blank=True, help_text="Human-readable name of the representative feature flag")
    active = serializers.BooleanField(help_text="Whether the representative feature flag is enabled")
    filters = serializers.JSONField(help_text="Release condition filters of the representative feature flag")


class OrganizationFeatureFlagKeysResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField(help_text="Total number of distinct flag keys across the compared projects")
    next = serializers.CharField(allow_null=True, help_text="URL for the next page of results, or null if none")
    previous = serializers.CharField(allow_null=True, help_text="URL for the previous page of results, or null if none")
    results = OrganizationFeatureFlagRowSerializer(
        many=True, help_text="One representative flag per distinct key across the compared projects"
    )


logger = structlog.get_logger(__name__)


class OrganizationFeatureFlagView(
    TeamAndOrgViewSetMixin,
    viewsets.ViewSet,
    mixins.RetrieveModelMixin,
):
    scope_object = "INTERNAL"
    serializer_class = _FallbackSerializer
    """
    Retrieves all feature flags for a given organization and key.
    """

    lookup_field = "feature_flag_key"

    @staticmethod
    def _redact_encrypted_payloads(request, flag: FeatureFlag) -> None:
        """Replace encrypted remote-config payload ciphertext with a redacted placeholder, in place.

        Mirrors the project-scoped flag read paths: only requests authenticated with a personal API
        key get decrypted values; everyone else (session, OAuth) sees the redacted placeholder, so the
        ciphertext is never returned over the org-wide endpoints.
        """
        if flag.has_encrypted_payloads:
            flag.filters["payloads"] = get_decrypted_flag_payloads_protected(request, flag.filters.get("payloads", {}))

    @extend_schema(
        operation_id="org_feature_flags_retrieve",
        parameters=[OpenApiParameter("feature_flag_key", OpenApiTypes.STR, OpenApiParameter.PATH)],
    )
    def retrieve(self, request, *args, **kwargs):
        feature_flag_key = kwargs.get(self.lookup_field)

        # Only return flags from teams the user has access to
        user_permissions = UserPermissions(user=request.user)
        accessible_team_ids = user_permissions.team_ids_visible_for_user
        org_team_ids = set(self.organization.teams.values_list("id", flat=True))
        team_ids = list(org_team_ids & set(accessible_team_ids))

        flags_qs = FeatureFlag.objects.filter(
            key=feature_flag_key,
            team_id__in=team_ids,
        )
        flags_qs = self._filter_flags_by_rbac(flags_qs, team_ids)
        flags = list(flags_qs)
        for flag in flags:
            self._redact_encrypted_payloads(request, flag)

        counts_by_team = get_cached_evaluations_7d_by_team(
            cast(str, feature_flag_key), [flag.team_id for flag in flags]
        )

        flags_data = [
            {
                "flag_id": flag.id,
                "team_id": flag.team_id,
                "created_by": UserBasicSerializer(flag.created_by).data
                if hasattr(flag, "created_by") and flag.created_by
                else None,
                "filters": flag.get_filters(),
                "created_at": flag.created_at,
                "active": flag.active,
                "evaluations_7d": counts_by_team.get(flag.team_id) if counts_by_team is not None else None,
            }
            for flag in flags
        ]

        return Response(flags_data)

    @extend_schema(
        operation_id="org_feature_flags_keys",
        parameters=[
            OpenApiParameter("search", OpenApiTypes.STR, OpenApiParameter.QUERY, description="Filter by key or name"),
            OpenApiParameter("limit", OpenApiTypes.INT, OpenApiParameter.QUERY, description="Page size (max 100)"),
            OpenApiParameter("offset", OpenApiTypes.INT, OpenApiParameter.QUERY, description="Pagination offset"),
            OpenApiParameter(
                "team_ids",
                OpenApiTypes.INT,
                OpenApiParameter.QUERY,
                many=True,
                description="Teams to compare, in priority order. Defaults to all accessible teams in the org.",
            ),
        ],
        responses={200: OrganizationFeatureFlagKeysResponseSerializer},
    )
    @action(detail=False, methods=["get"], url_path="keys")
    def keys(self, request, *args, **kwargs):
        """Paginated, de-duplicated list of feature flag keys across the org's compared projects.

        Unlike the project-scoped flag list, this enumerates the union of flag keys across every
        compared project, so flags that exist only in another project still appear as rows.
        """
        # Restrict to teams in this org that the user can access.
        user_permissions = UserPermissions(user=request.user)
        accessible_team_ids = set(user_permissions.team_ids_visible_for_user)
        org_team_ids = set(self.organization.teams.values_list("id", flat=True))
        allowed_team_ids = org_team_ids & accessible_team_ids

        # Accept team_ids as repeated params (?team_ids=1&team_ids=2) or comma-separated (?team_ids=1,2).
        try:
            requested_team_ids = [
                int(part) for value in request.query_params.getlist("team_ids") for part in value.split(",") if part
            ]
            limit = max(min(int(request.query_params.get("limit") or 25), 100), 1)
            offset = max(int(request.query_params.get("offset") or 0), 0)
        except ValueError:
            return Response({"error": "Invalid query parameter."}, status=status.HTTP_400_BAD_REQUEST)

        # Preserve the caller's team ordering, de-duplicated (used to pick the representative per key).
        ordered_team_ids: list[int] = []
        seen_teams: set[int] = set()
        for team_id in requested_team_ids:
            if team_id in allowed_team_ids and team_id not in seen_teams:
                seen_teams.add(team_id)
                ordered_team_ids.append(team_id)
        if not ordered_team_ids:
            ordered_team_ids = sorted(allowed_team_ids)
        if not ordered_team_ids:
            return Response({"count": 0, "next": None, "previous": None, "results": []})

        search = (request.query_params.get("search") or "").strip()
        flags_qs = FeatureFlag.objects.filter(team_id__in=ordered_team_ids, deleted=False)
        flags_qs = self._filter_flags_by_rbac(flags_qs, ordered_team_ids)
        if search:
            flags_qs = flags_qs.filter(Q(key__icontains=search) | Q(name__icontains=search))

        distinct_keys_qs = flags_qs.order_by("key").values_list("key", flat=True).distinct()
        count = distinct_keys_qs.count()
        page_keys = list(distinct_keys_qs[offset : offset + limit])

        # Choose one representative flag per key, preferring earlier teams in the requested order.
        # Select from the search-filtered queryset so the representative always matches the search,
        # and let Postgres do the per-key dedup (DISTINCT ON key, ordered by team rank) so we load
        # one row per key instead of every team's copy. Ordering by key matches page_keys' order.
        rank_whens = [When(team_id=team_id, then=Value(rank)) for rank, team_id in enumerate(ordered_team_ids)]
        representatives = list(
            flags_qs.filter(key__in=page_keys)
            .annotate(_rank=Case(*rank_whens, output_field=IntegerField()))
            .order_by("key", "_rank")
            .distinct("key")
        )
        for flag in representatives:
            self._redact_encrypted_payloads(request, flag)
        # OrganizationFeatureFlagRowSerializer is the single source of truth for the row shape.
        results = OrganizationFeatureFlagRowSerializer(representatives, many=True).data

        next_url = (
            replace_query_param(request.build_absolute_uri(), "offset", offset + limit)
            if offset + limit < count
            else None
        )
        previous_url = (
            replace_query_param(request.build_absolute_uri(), "offset", max(offset - limit, 0)) if offset > 0 else None
        )

        return Response({"count": count, "next": next_url, "previous": previous_url, "results": results})

    @extend_schema(
        request=CopyFlagsDependencyRequirementsRequestSerializer,
        responses={
            200: CopyFlagsDependencyRequirementsResponseSerializer,
            400: OpenApiResponse(response=ErrorResponseSerializer),
            403: OpenApiResponse(response=ErrorResponseSerializer),
        },
    )
    @action(
        detail=False,
        methods=["post"],
        url_path="copy_flags/dependency_requirements",
        required_scopes=["feature_flag:write"],
    )
    def copy_flags_dependency_requirements(self, request, *args, **kwargs):
        serializer = CopyFlagsDependencyRequirementsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        body = serializer.validated_data
        feature_flag_key = body.get("feature_flag_key")
        from_project = body.get("from_project")
        target_project_ids = body.get("target_project_ids")
        user = cast(User, request.user)
        user_permissions = UserPermissions(user=user)
        accessible_team_ids = set(user_permissions.team_ids_visible_for_user)

        try:
            flag_to_copy = self._get_source_flag(feature_flag_key, from_project, accessible_team_ids)
        except FeatureFlag.DoesNotExist:
            return Response({"error": "Feature flag to copy does not exist."}, status=status.HTTP_400_BAD_REQUEST)

        if not self._user_can_edit_flag(user, flag_to_copy):
            return Response(
                {"error": "You do not have permission to copy this flag."}, status=status.HTTP_403_FORBIDDEN
            )

        try:
            dependency_graph = self._resolve_dependency_copy_graph(flag_to_copy, user)
        except (PermissionError, ValueError) as error:
            return Response(
                self._dependency_requirements_unavailable_response(str(error)),
                status=status.HTTP_200_OK,
            )

        return Response(
            self._dependency_requirements_response(dependency_graph, target_project_ids),
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        request=CopyFlagsRequestSerializer,
        responses={
            200: CopyFlagsResponseSerializer,
            400: OpenApiResponse(response=ErrorResponseSerializer),
            403: OpenApiResponse(response=ErrorResponseSerializer),
        },
    )
    @action(detail=False, methods=["post"], url_path="copy_flags", required_scopes=["feature_flag:write"])
    def copy_flags(self, request, *args, **kwargs):
        serializer = CopyFlagsRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        body = serializer.validated_data
        feature_flag_key = body.get("feature_flag_key")
        from_project = body.get("from_project")
        target_project_ids = body.get("target_project_ids")
        copy_schedule = body.get("copy_schedule", False)  # Optional parameter to copy schedules
        disable_copied_flag = body.get("disable_copied_flag", False)
        copy_dependencies = body.get("copy_dependencies", False)
        user = cast(User, request.user)
        user_permissions = UserPermissions(user=user)
        accessible_team_ids = set(user_permissions.team_ids_visible_for_user)

        try:
            flag_to_copy = self._get_source_flag(feature_flag_key, from_project, accessible_team_ids)
        except FeatureFlag.DoesNotExist:
            return Response({"error": "Feature flag to copy does not exist."}, status=status.HTTP_400_BAD_REQUEST)

        if not self._user_can_edit_flag(user, flag_to_copy):
            return Response(
                {"error": "You do not have permission to copy this flag."}, status=status.HTTP_403_FORBIDDEN
            )

        dependency_graph = DependencyCopyGraph(dependency_flags=[], root_dependency_flag_ids=[], dependency_edges={})
        if copy_dependencies:
            try:
                dependency_graph = self._resolve_dependency_copy_graph(flag_to_copy, user)
            except PermissionError as error:
                return Response({"error": str(error)}, status=status.HTTP_403_FORBIDDEN)
            except ValueError as error:
                return Response({"error": str(error)}, status=status.HTTP_400_BAD_REQUEST)

        copy_source_flags = [*dependency_graph.dependency_flags, flag_to_copy]
        copy_source_contexts = {
            source_flag.id: self._get_feature_flag_copy_source_context(
                source_flag,
                copy_schedule,
                user,
            )
            for source_flag in copy_source_flags
        }

        successful_projects = []
        failed_projects = []

        for target_project_id in target_project_ids:
            target_team = self._get_accessible_target_team(target_project_id, accessible_team_ids)
            if target_team is None:
                failed_projects.append(
                    {
                        "project_id": target_project_id,
                        "error_message": "Project not found.",
                    }
                )
                continue

            try:
                with transaction.atomic():
                    target_flag_access_context = (
                        self._get_accessible_target_flags_by_key(
                            [source_flag.key for source_flag in copy_source_flags],
                            target_team,
                        )
                        if dependency_graph.dependency_flags
                        else None
                    )

                    copied_dependency_keys, dependency_copy_warnings = self._copy_dependency_flags_to_target(
                        request,
                        dependency_graph,
                        target_team,
                        target_project_id,
                        copy_schedule,
                        accessible_team_ids,
                        copy_source_contexts,
                        target_flag_access_context,
                    )

                    result = self._copy_feature_flag_to_target(
                        request,
                        flag_to_copy,
                        target_team,
                        target_project_id,
                        copy_schedule,
                        disable_copied_flag,
                        source_context=copy_source_contexts[flag_to_copy.id],
                        target_flag_access_context=target_flag_access_context,
                    )
                    if copied_dependency_keys:
                        result["copied_dependency_keys"] = copied_dependency_keys
                    if dependency_copy_warnings:
                        result["dependency_copy_warnings"] = dependency_copy_warnings
                    successful_projects.append(result)
            except Exception as e:
                failed_projects.append(
                    {
                        "project_id": target_project_id,
                        "error_message": str(e),
                    }
                )

        return Response(
            {"success": successful_projects, "failed": failed_projects},
            status=status.HTTP_200_OK,
        )

    def _copy_dependency_flags_to_target(
        self,
        request: Request,
        dependency_graph: DependencyCopyGraph,
        target_team: Team,
        target_project_id: int,
        copy_schedule: bool,
        accessible_team_ids: set[int],
        copy_source_contexts: dict[int, FeatureFlagCopySourceContext],
        target_flag_access_context: TargetFlagAccessContext | None,
    ) -> tuple[list[str], list[str]]:
        if not dependency_graph.dependency_flags:
            return [], []
        if target_flag_access_context is None:
            target_flag_access_context = self._get_accessible_target_flags_by_key(
                [dependency_flag.key for dependency_flag in dependency_graph.dependency_flags],
                target_team,
            )

        target_requirements = self._get_dependency_target_requirements(
            dependency_graph,
            [target_project_id],
            accessible_team_ids=accessible_team_ids,
            target_teams_by_project_id={target_project_id: target_team},
            target_flag_access_contexts_by_project_id={target_project_id: target_flag_access_context},
        )
        keys_to_copy = set(target_requirements.copied_dependency_keys)
        copied_dependency_keys: list[str] = []
        dependency_copy_warnings: list[str] = []

        for dependency_flag in dependency_graph.dependency_flags:
            if dependency_flag.key not in keys_to_copy:
                continue
            dependency_result = self._copy_feature_flag_to_target(
                request,
                dependency_flag,
                target_team,
                target_project_id,
                copy_schedule,
                False,
                update_existing_target=False,
                source_context=copy_source_contexts[dependency_flag.id],
                target_flag_access_context=target_flag_access_context,
            )
            copied_dependency_keys.append(dependency_flag.key)
            dependency_copy_warnings.extend(dependency_result.get("flag_dependency_warnings") or [])
            if dependency_result.get("schedule_copy_warning"):
                dependency_copy_warnings.append(dependency_result["schedule_copy_warning"])

        return copied_dependency_keys, dependency_copy_warnings

    def _get_source_flag(self, feature_flag_key: str, from_project: int, accessible_team_ids: set[int]) -> FeatureFlag:
        return FeatureFlag.objects.get(
            key=feature_flag_key,
            team__project_id=from_project,
            team__organization_id=self.organization_id,
            team_id__in=accessible_team_ids,
        )

    def _user_can_edit_flag(self, user: User, flag: FeatureFlag) -> bool:
        user_access_control = UserAccessControl(user, flag.team)
        user_access_level = user_access_control.get_user_access_level(flag)
        return bool(
            user_access_level and access_level_satisfied_for_resource("feature_flag", user_access_level, "editor")
        )

    def _user_can_create_feature_flags(self, user: User, target_team: Team) -> bool:
        if not self.organization.is_feature_available(AvailableFeature.ACCESS_CONTROL):
            return True

        user_access_control = UserAccessControl(user, target_team)
        return user_access_control.check_access_level_for_object(
            target_team, required_level="member"
        ) and user_access_control.check_access_level_for_resource("feature_flag", required_level="editor")

    def _get_accessible_target_team(self, target_project_id: int, accessible_team_ids: set[int]) -> Team | None:
        target_team = Team.objects.filter(
            project_id=target_project_id,
            organization_id=self.organization_id,
        ).first()
        if target_team is None or target_team.id not in accessible_team_ids:
            return None
        return target_team

    def _get_target_teams_by_project_id(self, target_project_ids: list[int]) -> dict[int, Team]:
        return {
            team.project_id: team
            for team in Team.objects.filter(
                project_id__in=target_project_ids,
                organization_id=self.organization_id,
            )
        }

    def _get_existing_target_flag_for_copy(
        self, user: User, source_flag: FeatureFlag, target_team: Team, update_existing_target: bool = True
    ) -> FeatureFlag | None:
        existing_flag = FeatureFlag.objects.filter(key=source_flag.key, team=target_team, deleted=False).first()
        return self._validate_target_flag_for_copy(
            user, source_flag, target_team, existing_flag, update_existing_target=update_existing_target
        )

    def _validate_target_flag_for_copy(
        self,
        user: User,
        source_flag: FeatureFlag,
        target_team: Team,
        existing_flag: FeatureFlag | None,
        update_existing_target: bool = True,
    ) -> FeatureFlag | None:
        if existing_flag:
            if not update_existing_target:
                raise ValueError(
                    f"Dependency flag '{source_flag.key}' already exists in the target project. It was left unchanged."
                )
            if not self._user_can_edit_flag(user, existing_flag):
                raise PermissionError(TARGET_COPY_PERMISSION_ERROR)
            return existing_flag
        if not self._user_can_create_feature_flags(user, target_team):
            raise PermissionError(TARGET_COPY_PERMISSION_ERROR)
        return None

    def _dependency_requirements_unavailable_response(self, reason: str) -> dict[str, Any]:
        return {
            "can_copy_dependencies": False,
            "dependency_count": 0,
            "copied_dependency_keys": [],
            "reused_dependency_keys": [],
            "warnings": [reason],
            "reason": reason,
        }

    def _dependency_requirements_response(
        self, dependency_graph: DependencyCopyGraph, target_project_ids: list[int]
    ) -> dict[str, Any]:
        target_requirements = self._get_dependency_target_requirements(dependency_graph, target_project_ids)
        response = {
            "can_copy_dependencies": target_requirements.can_copy_dependencies,
            "dependency_count": len(dependency_graph.dependency_flags),
            "copied_dependency_keys": target_requirements.copied_dependency_keys,
            "reused_dependency_keys": target_requirements.reused_dependency_keys,
            "warnings": target_requirements.warnings,
            "reason": target_requirements.reason,
        }
        return response

    def _get_dependency_target_requirements(
        self,
        dependency_graph: DependencyCopyGraph,
        target_project_ids: list[int],
        accessible_team_ids: set[int] | None = None,
        target_teams_by_project_id: dict[int, Team] | None = None,
        target_flag_access_contexts_by_project_id: dict[int, TargetFlagAccessContext] | None = None,
    ) -> DependencyCopyTargetRequirements:
        dependency_flags = dependency_graph.dependency_flags
        dependency_keys = [flag.key for flag in dependency_flags]
        if not dependency_keys:
            return DependencyCopyTargetRequirements(
                can_copy_dependencies=False,
                copied_dependency_keys=[],
                reused_dependency_keys=[],
                warnings=[],
                reason="This feature flag doesn't have dependencies to copy.",
            )

        dependency_flags_by_id = {flag.id: flag for flag in dependency_flags}
        dependency_flag_ids = set(dependency_flags_by_id)
        dependency_order_by_id = {flag.id: index for index, flag in enumerate(dependency_flags)}
        dependency_ids_by_flag_id = {
            flag.id: dependency_graph.dependency_edges.get(flag.id, set()) & dependency_flag_ids
            for flag in dependency_flags
        }
        root_dependency_flag_ids = sorted(
            [flag_id for flag_id in dependency_graph.root_dependency_flag_ids if flag_id in dependency_flags_by_id],
            key=lambda flag_id: dependency_order_by_id[flag_id],
        )

        if accessible_team_ids is None:
            user_permissions = UserPermissions(user=cast(User, self.request.user))
            accessible_team_ids = set(user_permissions.team_ids_visible_for_user)
        if target_teams_by_project_id is None:
            target_teams_by_project_id = self._get_target_teams_by_project_id(target_project_ids)

        copied_dependency_keys: set[str] = set()
        reused_dependency_keys: set[str] | None = None
        warnings: list[str] = []
        has_unreachable_target = False

        for target_project_id in target_project_ids:
            target_team = target_teams_by_project_id.get(target_project_id)
            if target_team is None or target_team.id not in accessible_team_ids:
                has_unreachable_target = True
                warnings.append("Project not found.")
                if reused_dependency_keys is None:
                    reused_dependency_keys = set()
                else:
                    reused_dependency_keys.clear()
                continue

            target_flag_access_context = (
                target_flag_access_contexts_by_project_id.get(target_project_id)
                if target_flag_access_contexts_by_project_id is not None
                else None
            )
            if target_flag_access_context is None:
                target_flag_access_context = self._get_accessible_target_flags_by_key(
                    dependency_keys,
                    target_team,
                )

            can_create_feature_flags = self._user_can_create_feature_flags(cast(User, self.request.user), target_team)
            target_reused_dependency_keys: set[str] = set()
            dependency_copy_requirements_by_id: dict[int, _DependencyCopyDecision] = {}
            for root_dependency_flag_id in root_dependency_flag_ids:
                decision = self._collect_dependency_copy_requirements(
                    root_dependency_flag_id,
                    dependency_flags_by_id,
                    dependency_ids_by_flag_id,
                    dependency_order_by_id,
                    target_flag_access_context.flags_by_key,
                    target_flag_access_context.restricted_keys,
                    can_create_feature_flags,
                    dependency_copy_requirements_by_id,
                    warnings,
                )
                copied_dependency_keys.update(decision.keys_to_copy)
                target_reused_dependency_keys.update(decision.keys_to_reuse)
            reused_dependency_keys = (
                target_reused_dependency_keys
                if reused_dependency_keys is None
                else reused_dependency_keys & target_reused_dependency_keys
            )

        ordered_copied_dependency_keys = [key for key in dependency_keys if key in copied_dependency_keys]
        ordered_reused_dependency_keys = [
            key
            for key in dependency_keys
            if key in (reused_dependency_keys or set()) and key not in copied_dependency_keys
        ]
        deduped_warnings = list(dict.fromkeys(warnings))

        if has_unreachable_target:
            ordered_copied_dependency_keys = []
            ordered_reused_dependency_keys = []
            reason = "Project not found."
            can_copy_dependencies = False
        elif ordered_copied_dependency_keys:
            count = len(ordered_copied_dependency_keys)
            reason = f"{count} dependency flag{'s' if count != 1 else ''} can be copied."
            if deduped_warnings:
                reason = f"{reason} Some dependencies will be left unchanged."
            can_copy_dependencies = True
        elif deduped_warnings:
            reason = deduped_warnings[0]
            can_copy_dependencies = False
        else:
            reason = "No dependency flags need to be copied because existing active target flags satisfy this flag's dependencies."
            can_copy_dependencies = False

        return DependencyCopyTargetRequirements(
            can_copy_dependencies=can_copy_dependencies,
            copied_dependency_keys=ordered_copied_dependency_keys,
            reused_dependency_keys=ordered_reused_dependency_keys,
            warnings=deduped_warnings,
            reason=reason,
        )

    def _collect_dependency_copy_requirements(
        self,
        dependency_flag_id: int,
        dependency_flags_by_id: dict[int, FeatureFlag],
        dependency_ids_by_flag_id: dict[int, set[int]],
        dependency_order_by_id: dict[int, int],
        target_flags_by_key: dict[str, FeatureFlag],
        restricted_target_dependency_keys: set[str],
        can_create_feature_flags: bool,
        dependency_copy_requirements_by_id: dict[int, _DependencyCopyDecision],
        warnings: list[str],
    ) -> _DependencyCopyDecision:
        cached_result = dependency_copy_requirements_by_id.get(dependency_flag_id)
        if cached_result is not None:
            return cached_result
        source_dependency = dependency_flags_by_id.get(dependency_flag_id)
        if source_dependency is None:
            return _DependencyCopyDecision(True, set(), set())

        if not source_dependency.active:
            return self._deny_dependency_copy(
                dependency_flag_id,
                dependency_copy_requirements_by_id,
                warnings,
                f"Cannot automatically copy dependency flag '{source_dependency.key}' because it is disabled in the source project.",
            )

        target_flag = target_flags_by_key.get(source_dependency.key)
        if target_flag and target_flag.active:
            decision = _DependencyCopyDecision(True, set(), {source_dependency.key})
            dependency_copy_requirements_by_id[dependency_flag_id] = decision
            return decision
        if target_flag and not target_flag.active:
            return self._deny_dependency_copy(
                dependency_flag_id,
                dependency_copy_requirements_by_id,
                warnings,
                f"Dependency copying isn't available because flag '{source_dependency.key}' is disabled in the target project. Copy this flag without dependencies to leave that target flag unchanged.",
            )
        if source_dependency.key in restricted_target_dependency_keys:
            return self._deny_dependency_copy(
                dependency_flag_id,
                dependency_copy_requirements_by_id,
                warnings,
                RESTRICTED_TARGET_DEPENDENCY_WARNING,
            )
        if not can_create_feature_flags:
            return self._deny_dependency_copy(
                dependency_flag_id,
                dependency_copy_requirements_by_id,
                warnings,
                TARGET_DEPENDENCY_CREATE_PERMISSION_WARNING,
            )

        dependency_keys_to_copy = set()
        dependency_keys_to_reuse = set()
        can_copy_dependency = True
        for child_dependency_id in sorted(
            dependency_ids_by_flag_id[source_dependency.id],
            key=lambda flag_id: dependency_order_by_id[flag_id],
        ):
            child_decision = self._collect_dependency_copy_requirements(
                child_dependency_id,
                dependency_flags_by_id,
                dependency_ids_by_flag_id,
                dependency_order_by_id,
                target_flags_by_key,
                restricted_target_dependency_keys,
                can_create_feature_flags,
                dependency_copy_requirements_by_id,
                warnings,
            )
            can_copy_dependency = child_decision.can_copy and can_copy_dependency
            dependency_keys_to_copy.update(child_decision.keys_to_copy)
            dependency_keys_to_reuse.update(child_decision.keys_to_reuse)

        if not can_copy_dependency:
            return self._deny_dependency_copy(dependency_flag_id, dependency_copy_requirements_by_id, warnings)

        dependency_keys_to_copy.add(source_dependency.key)
        decision = _DependencyCopyDecision(True, dependency_keys_to_copy, dependency_keys_to_reuse)
        dependency_copy_requirements_by_id[dependency_flag_id] = decision
        return decision

    def _deny_dependency_copy(
        self,
        flag_id: int,
        cache: dict[int, _DependencyCopyDecision],
        warnings: list[str],
        warning: str | None = None,
    ) -> _DependencyCopyDecision:
        if warning is not None:
            warnings.append(warning)
        decision = _DependencyCopyDecision(False, set(), set())
        cache[flag_id] = decision
        return decision

    def _resolve_dependency_copy_graph(self, source_flag: FeatureFlag, user: User) -> DependencyCopyGraph:
        visited: set[int] = set()
        visiting: set[int] = set()
        discovered_dependency_ids: set[int] = set()
        dependency_flags: list[FeatureFlag] = []
        dependency_edges: dict[int, set[int]] = {}

        # Keep this separate from cohort sorting because flag copy enforces permissions and the cap during discovery.
        def visit(flag: FeatureFlag) -> None:
            if flag.id in visiting:
                raise ValueError(
                    "A circular flag dependency was detected, so dependencies can't be copied automatically. Copy the flag without dependencies or remove the cycle first."
                )
            if flag.id in visited:
                return

            visiting.add(flag.id)
            dependency_references = self._extract_direct_flag_dependency_references_from_filters(flag.get_filters())
            dependencies_by_reference = self._get_source_dependency_flags_by_reference(
                source_flag.team, dependency_references
            )
            direct_dependency_ids: set[int] = set()
            for dependency_reference in dependency_references:
                dependency_flag = dependencies_by_reference.get(dependency_reference)
                if dependency_flag is None:
                    raise ValueError(
                        f"Removed a flag dependency (source flag reference {dependency_reference}) because the dependency flag could not be resolved in the source project."
                    )
                if not self._user_can_edit_flag(user, dependency_flag):
                    raise PermissionError(SOURCE_DEPENDENCY_COPY_PERMISSION_ERROR)
                if dependency_flag.id != source_flag.id:
                    direct_dependency_ids.add(dependency_flag.id)
                if (
                    dependency_flag.id != source_flag.id
                    and dependency_flag.id not in visited
                    and dependency_flag.id not in visiting
                    and dependency_flag.id not in discovered_dependency_ids
                ):
                    discovered_dependency_ids.add(dependency_flag.id)
                    if len(discovered_dependency_ids) > MAX_COPY_DEPENDENCY_FLAGS:
                        raise ValueError(
                            "This flag depends on more than 50 flags, so dependencies can't be copied automatically. Copy the flag without dependencies or reduce the dependency chain."
                        )
                visit(dependency_flag)

            dependency_edges[flag.id] = direct_dependency_ids
            visiting.remove(flag.id)
            visited.add(flag.id)
            if flag.id != source_flag.id:
                dependency_flags.append(flag)

        visit(source_flag)
        source_dependency_ids = dependency_edges.get(source_flag.id, set())
        root_dependency_flag_ids = [flag.id for flag in dependency_flags if flag.id in source_dependency_ids]

        return DependencyCopyGraph(
            dependency_flags=dependency_flags,
            root_dependency_flag_ids=root_dependency_flag_ids,
            dependency_edges=dependency_edges,
        )

    def _extract_direct_flag_dependency_references_from_filters(self, filters: dict[str, Any]) -> list[str]:
        dependency_references: list[str] = []
        seen_dependency_references: set[str] = set()
        for group in self._iter_filter_groups(filters):
            for prop in self._iter_group_properties(group):
                if prop.get("type") == "flag":
                    dependency_reference = self._normalize_flag_dependency_reference(prop.get("key"))
                    if dependency_reference is not None and dependency_reference not in seen_dependency_references:
                        dependency_references.append(dependency_reference)
                        seen_dependency_references.add(dependency_reference)
        return dependency_references

    def _normalize_flag_dependency_reference(self, dependency_reference: Any) -> str | None:
        if dependency_reference is None or isinstance(dependency_reference, bool):
            return None
        if isinstance(dependency_reference, str):
            dependency_reference = dependency_reference.strip()
            return dependency_reference or None
        if isinstance(dependency_reference, int):
            return str(dependency_reference) if dependency_reference >= 0 else None
        return None

    def _parse_flag_dependency_id_reference(self, dependency_reference: str) -> int | None:
        if not re.fullmatch(r"\d+", dependency_reference):
            return None
        return int(dependency_reference)

    def _get_direct_flag_dependencies(self, flag: FeatureFlag) -> dict[str, FeatureFlag]:
        return self._get_source_dependency_flags_by_reference(
            flag.team,
            self._extract_direct_flag_dependency_references_from_filters(flag.get_filters()),
        )

    def _get_source_dependency_flags_by_reference(
        self, source_team: Team, source_dependency_references: list[str]
    ) -> dict[str, FeatureFlag]:
        if not source_dependency_references:
            return {}

        dependency_flags_by_reference: dict[str, FeatureFlag] = {}
        dependency_ids_by_reference: dict[str, int] = {}
        for dependency_reference in source_dependency_references:
            dependency_id = self._parse_flag_dependency_id_reference(dependency_reference)
            if dependency_id is not None:
                dependency_ids_by_reference[dependency_reference] = dependency_id

        dependency_flags_by_id = {
            flag.id: flag
            for flag in FeatureFlag.objects.filter(
                id__in=dependency_ids_by_reference.values(),
                team=source_team,
                deleted=False,
            )
        }
        key_dependency_references = [
            dependency_reference
            for dependency_reference in source_dependency_references
            if dependency_reference not in dependency_ids_by_reference
            or dependency_ids_by_reference[dependency_reference] not in dependency_flags_by_id
        ]
        dependency_flags_by_key = {
            flag.key: flag
            for flag in FeatureFlag.objects.filter(
                key__in=key_dependency_references,
                team=source_team,
                deleted=False,
            )
        }

        for dependency_reference in source_dependency_references:
            id_match = None
            dependency_id = dependency_ids_by_reference.get(dependency_reference)
            if dependency_id is not None:
                id_match = dependency_flags_by_id.get(dependency_id)
            key_match = dependency_flags_by_key.get(dependency_reference)

            if id_match is not None:
                dependency_flags_by_reference[dependency_reference] = id_match
            elif key_match is not None:
                dependency_flags_by_reference[dependency_reference] = key_match

        return dependency_flags_by_reference

    def _get_source_dependency_context(
        self, source_flag: FeatureFlag, user: User | None = None
    ) -> tuple[dict[str, str], set[str]]:
        source_dependency_references = self._extract_direct_flag_dependency_references_from_filters(
            source_flag.get_filters()
        )
        return self._get_source_dependency_context_for_references(
            source_flag.team, source_dependency_references, user=user
        )

    def _get_source_dependency_context_for_references(
        self,
        source_team: Team,
        source_dependency_references: list[str],
        user: User | None = None,
        raise_on_access_denied: bool = False,
    ) -> tuple[dict[str, str], set[str]]:
        if not source_dependency_references:
            return {}, set()
        flags_by_reference = self._get_source_dependency_flags_by_reference(source_team, source_dependency_references)
        flags_by_id = {flag.id: flag for flag in flags_by_reference.values()}
        if user is not None:
            allowed_flag_ids = {flag.id for flag in flags_by_id.values() if self._user_can_edit_flag(user, flag)}
            if raise_on_access_denied and len(allowed_flag_ids) != len(flags_by_id):
                raise PermissionError(SCHEDULED_DEPENDENCY_COPY_PERMISSION_ERROR)
            flags_by_reference = {
                dependency_reference: flag
                for dependency_reference, flag in flags_by_reference.items()
                if flag.id in allowed_flag_ids
            }
        disabled_source_dependency_keys = {flag.key for flag in flags_by_reference.values() if not flag.active}
        return (
            {dependency_reference: flag.key for dependency_reference, flag in flags_by_reference.items()},
            disabled_source_dependency_keys,
        )

    def _get_source_dependency_context_from_payload(
        self, payload: dict[str, Any], source_team: Team, user: User
    ) -> tuple[dict[str, str], set[str]]:
        filters = self._get_schedule_payload_filters(payload)
        if filters is None:
            return {}, set()
        return self._get_source_dependency_context_for_references(
            source_team,
            self._extract_direct_flag_dependency_references_from_filters(filters),
            user=user,
            raise_on_access_denied=True,
        )

    def _get_feature_flag_copy_source_context(
        self, source_flag: FeatureFlag, copy_schedule: bool, user: User
    ) -> FeatureFlagCopySourceContext:
        source_dependency_keys, disabled_source_dependency_keys = self._get_source_dependency_context(
            source_flag, user=user
        )
        seen_cohorts_cache: dict[int, CohortOrEmpty] = {}
        sorted_cohort_ids = source_flag.get_cohort_ids(
            seen_cohorts_cache=seen_cohorts_cache, sort_by_topological_order=True
        )
        source_schedules: list[ScheduledChange] = []
        schedule_dependency_contexts_by_id: dict[int, ScheduledChangeDependencyContext] = {}
        if copy_schedule:
            source_schedules = list(
                ScheduledChange.objects.filter(
                    record_id=str(source_flag.id),
                    model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
                    executed_at__isnull=True,
                    team=source_flag.team,
                )
            )
            for source_schedule in source_schedules:
                schedule_id = cast(int, source_schedule.id)
                try:
                    schedule_source_dependency_keys, schedule_disabled_source_dependency_keys = (
                        self._get_source_dependency_context_from_payload(
                            source_schedule.payload,
                            source_flag.team,
                            user,
                        )
                    )
                except PermissionError as error:
                    schedule_dependency_contexts_by_id[schedule_id] = ScheduledChangeDependencyContext(
                        source_dependency_keys={},
                        disabled_source_dependency_keys=set(),
                        error_message=str(error),
                    )
                    continue

                schedule_dependency_contexts_by_id[schedule_id] = ScheduledChangeDependencyContext(
                    source_dependency_keys=schedule_source_dependency_keys,
                    disabled_source_dependency_keys=schedule_disabled_source_dependency_keys,
                )
            schedule_cohort_ids = self._extract_cohort_ids_from_schedules(
                source_schedules, source_flag.team, seen_cohorts_cache
            )
            seen_sorted_cohort_ids = set(sorted_cohort_ids)
            for cohort_id in schedule_cohort_ids:
                if cohort_id not in seen_sorted_cohort_ids:
                    sorted_cohort_ids.append(cohort_id)
                    seen_sorted_cohort_ids.add(cohort_id)
        return FeatureFlagCopySourceContext(
            source_dependency_keys=source_dependency_keys,
            disabled_source_dependency_keys=disabled_source_dependency_keys,
            seen_cohorts_cache=seen_cohorts_cache,
            sorted_cohort_ids=sorted_cohort_ids,
            source_schedules=source_schedules,
            schedule_dependency_contexts_by_id=schedule_dependency_contexts_by_id,
        )

    def _copy_feature_flag_to_target(
        self,
        request,
        source_flag: FeatureFlag,
        target_team: Team,
        target_project_id: int,
        copy_schedule: bool,
        disable_copied_flag: bool,
        update_existing_target: bool = True,
        source_context: FeatureFlagCopySourceContext | None = None,
        target_flag_access_context: TargetFlagAccessContext | None = None,
    ) -> dict:
        user = cast(User, request.user)
        if target_flag_access_context is not None:
            if source_flag.key in target_flag_access_context.restricted_keys:
                raise PermissionError(TARGET_COPY_PERMISSION_ERROR)
            existing_flag = self._validate_target_flag_for_copy(
                user,
                source_flag,
                target_team,
                target_flag_access_context.flags_by_key.get(source_flag.key),
                update_existing_target=update_existing_target,
            )
        else:
            existing_flag = self._get_existing_target_flag_for_copy(
                user, source_flag, target_team, update_existing_target=update_existing_target
            )
        if source_context is None:
            source_context = self._get_feature_flag_copy_source_context(source_flag, copy_schedule, user)
        source_dependency_keys = source_context.source_dependency_keys
        disabled_source_dependency_keys = source_context.disabled_source_dependency_keys
        seen_cohorts_cache = source_context.seen_cohorts_cache
        sorted_cohort_ids = source_context.sorted_cohort_ids
        source_schedules = source_context.source_schedules

        # Cohorts are mapped by name because IDs differ across projects. This is fragile
        # if cohort names change or aren't unique, but it's the only identifier we can use
        # to match cohorts across projects.
        # destination cohort id is different from original cohort id - create mapping
        name_to_dest_cohort_id: dict[str, int] = {}
        # create cohorts in the destination project
        if len(sorted_cohort_ids):
            for cohort_id in sorted_cohort_ids:
                original_cohort = seen_cohorts_cache[cohort_id]

                if not original_cohort:
                    continue

                # search in destination project by name
                destination_cohort = Cohort.objects.filter(
                    name=original_cohort.name, team=target_team, deleted=False
                ).first()

                # create new cohort in the destination project
                if not destination_cohort:
                    prop_group = Filter(
                        data={"properties": original_cohort.properties.to_dict(), "is_simplified": True}
                    ).property_groups

                    for prop in prop_group.flat:
                        if prop.type == "cohort" and not isinstance(prop.value, list):
                            try:
                                original_child_cohort_id = int(prop.value)
                                original_child_cohort = seen_cohorts_cache[original_child_cohort_id]

                                if not original_child_cohort or original_child_cohort.name is None:
                                    continue
                                prop.value = name_to_dest_cohort_id[original_child_cohort.name]
                            except (ValueError, TypeError):
                                continue

                    destination_cohort_serializer = CohortSerializer(
                        data={
                            "team": target_team,
                            "name": original_cohort.name,
                            "groups": [],
                            "filters": {"properties": prop_group.to_dict()},
                            "description": original_cohort.description,
                            "is_static": original_cohort.is_static,
                        },
                        context={
                            "request": request,
                            "team_id": target_team.id,
                        },
                    )
                    destination_cohort_serializer.is_valid(raise_exception=True)
                    destination_cohort = destination_cohort_serializer.save()

                if destination_cohort is not None and original_cohort.name is not None:
                    name_to_dest_cohort_id[original_cohort.name] = destination_cohort.id

        # Deep-copy the filters per iteration before remapping the cohort and flag-dependency
        # references, whose target IDs are project-specific. Both remaps mutate this dict, so
        # working on a per-target copy keeps one target's IDs from leaking into the next.
        filters = copy.deepcopy(source_flag.get_filters())

        # reference correct destination cohort ids in the flag
        for group in filters.get("groups", []) or []:
            props = group.get("properties", [])
            for prop in props:
                if isinstance(prop, dict) and prop.get("type") == "cohort":
                    try:
                        original_cohort_id = int(prop["value"])
                        original_cohort_ref = seen_cohorts_cache[original_cohort_id]
                        if not original_cohort_ref or original_cohort_ref.name is None:
                            continue
                        cohort_name = original_cohort_ref.name
                        prop["value"] = name_to_dest_cohort_id[cohort_name]
                    except (ValueError, TypeError):
                        continue

        if target_flag_access_context is not None:
            flag_dependency_warnings = self._remap_flag_dependencies_with_target_context(
                filters,
                source_dependency_keys,
                target_flag_access_context.flags_by_key,
                target_flag_access_context.restricted_keys,
                disabled_source_dependency_keys,
            )
        else:
            flag_dependency_warnings = self._remap_flag_dependencies(
                filters, source_dependency_keys, target_team, disabled_source_dependency_keys
            )
        if source_flag.has_encrypted_payloads:
            # Decrypt payloads before copying to ensure the new flag has unencrypted payloads
            # that will be re-encrypted by the serializer if needed
            encrypted_payloads = filters.get("payloads", {})
            filters["payloads"] = get_decrypted_flag_payloads(encrypted_payloads, should_decrypt=True)

        flag_data = {
            "key": source_flag.key,
            "name": source_flag.name,
            "filters": filters,
            # Dropping a flag dependency leaves its condition group ungated (an empty-property
            # group matches everyone), so a copy with dropped dependencies must never land
            # enabled — force it inactive for review.
            "active": False if (disable_copied_flag or flag_dependency_warnings) else source_flag.active,
            "ensure_experience_continuity": source_flag.ensure_experience_continuity,
            "deleted": False,
            "evaluation_runtime": source_flag.evaluation_runtime,
            "bucketing_identifier": source_flag.bucketing_identifier,
            "is_remote_configuration": source_flag.is_remote_configuration,
            "has_encrypted_payloads": source_flag.has_encrypted_payloads,
        }
        context = {
            "request": request,
            "team_id": target_project_id,
            "project_id": target_project_id,
        }

        original_request_method = request.method
        try:
            # FeatureFlagSerializer validates create/update semantics from the request method.
            request.method = "PATCH" if existing_flag else "POST"
            if existing_flag:
                feature_flag_serializer = FeatureFlagSerializer(
                    existing_flag, data=flag_data, partial=True, context=context
                )
            else:
                feature_flag_serializer = FeatureFlagSerializer(data=flag_data, context=context)

            try:
                feature_flag_serializer.is_valid(raise_exception=True)
                saved_flag = feature_flag_serializer.save(team_id=target_project_id)
                if target_flag_access_context is not None:
                    target_flag_access_context.flags_by_key[source_flag.key] = saved_flag
            except IntegrityError as e:
                if not update_existing_target:
                    raise ValueError(
                        f"Dependency flag '{source_flag.key}' already exists in the target project. "
                        "It was left unchanged."
                    ) from e
                raise
            except Exception as e:
                if feature_flag_serializer.errors:
                    raise ValueError(feature_flag_serializer.errors) from e
                raise
        finally:
            request.method = original_request_method

        # Copy schedules if requested
        schedule_copy_error = None
        schedule_dependency_warnings: list[str] = []
        if existing_flag:
            has_pending_target_schedules = ScheduledChange.objects.filter(
                record_id=str(saved_flag.id),
                model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
                executed_at__isnull=True,
                team=target_team,
            ).exists()
            if has_pending_target_schedules:
                schedule_dependency_warnings.append(EXISTING_TARGET_SCHEDULE_DEPENDENCY_WARNING)
        if copy_schedule and flag_dependency_warnings:
            schedule_dependency_warnings.append(
                "Skipped scheduled changes because one or more current flag dependencies could not be safely remapped."
            )
        elif copy_schedule:
            try:
                with transaction.atomic():
                    copied_schedule_dependency_warnings = self._copy_feature_flag_schedules(
                        source_schedules,
                        saved_flag,
                        request.user,
                        name_to_dest_cohort_id,
                        seen_cohorts_cache,
                        source_context.schedule_dependency_contexts_by_id,
                        source_dependency_keys,
                        disabled_source_dependency_keys,
                        target_team,
                    )
                    schedule_dependency_warnings.extend(copied_schedule_dependency_warnings)
            except Exception as e:
                logger.exception(
                    "Failed to copy feature flag schedules",
                    source_flag_id=source_flag.id,
                    target_flag_id=saved_flag.id,
                )
                schedule_copy_error = str(e)

        result = dict(feature_flag_serializer.data)
        result["team_id"] = saved_flag.team_id
        if schedule_copy_error:
            result["schedule_copy_warning"] = f"Flag copied but schedules failed: {schedule_copy_error}"
        if schedule_dependency_warnings:
            schedule_dependency_warning = "Flag copied but scheduled changes had dependency warnings: " + "; ".join(
                schedule_dependency_warnings
            )
            if result.get("schedule_copy_warning"):
                result["schedule_copy_warning"] = f"{result['schedule_copy_warning']}; {schedule_dependency_warning}"
            else:
                result["schedule_copy_warning"] = schedule_dependency_warning
        if flag_dependency_warnings:
            result["flag_dependency_warnings"] = flag_dependency_warnings
        return result

    def _remap_flag_dependencies(
        self,
        filters: dict[str, Any],
        source_dependency_keys: dict[str, str],
        target_team: Team,
        disabled_source_dependency_keys: set[str] | None = None,
    ) -> list[str]:
        """Remap flag-dependency references to the matching flag in the target project.

        Flag dependencies store the parent flag's ID, which differs across projects, so we match by
        key — the same approach used for cohorts. When no active flag with that key exists in the
        target project, the dependency is dropped and a warning is returned rather than failing the
        whole copy (the validator would otherwise reject a dangling or disabled dependency).
        """
        if source_dependency_keys:
            target_flag_access_context = self._get_accessible_target_flags_by_key(
                list(source_dependency_keys.values()),
                target_team,
            )
        else:
            target_flag_access_context = TargetFlagAccessContext(flags_by_key={}, restricted_keys=set())
        return self._remap_flag_dependencies_with_target_context(
            filters,
            source_dependency_keys,
            target_flag_access_context.flags_by_key,
            target_flag_access_context.restricted_keys,
            disabled_source_dependency_keys,
        )

    def _remap_flag_dependencies_with_target_context(
        self,
        filters: dict[str, Any],
        source_dependency_keys: dict[str, str],
        target_flags_by_key: dict[str, FeatureFlag],
        restricted_target_dependency_keys: set[str],
        disabled_source_dependency_keys: set[str] | None = None,
    ) -> list[str]:
        warnings: list[str] = []
        has_flag_dependency_property = any(
            prop.get("type") == "flag"
            for group in self._iter_filter_groups(filters)
            for prop in self._iter_group_properties(group)
        )
        if not has_flag_dependency_property:
            return warnings
        disabled_source_dependency_keys = disabled_source_dependency_keys or set()

        for group in self._iter_filter_groups(filters):
            # Leave groups without a properties key untouched so we don't change the filter shape
            # (an injected empty list would otherwise alter every copied flag's serialized filters).
            properties = group.get("properties")
            if not properties:
                continue
            if not isinstance(properties, list):
                continue
            kept_properties = []
            dropped_dependency = False
            for prop in properties:
                if not (isinstance(prop, dict) and prop.get("type") == "flag"):
                    kept_properties.append(prop)
                    continue

                source_dependency_reference = self._normalize_flag_dependency_reference(prop.get("key"))
                source_key = (
                    source_dependency_keys.get(source_dependency_reference)
                    if source_dependency_reference is not None
                    else None
                )

                if source_key is None:
                    # The source dependency itself couldn't be resolved (e.g. it was soft-deleted), so
                    # there's no key to match in the target — drop it and name the unresolved source reference.
                    dropped_dependency = True
                    warnings.append(
                        f"Removed a flag dependency (source flag reference {prop.get('key')}) because the dependency flag could not be resolved in the source project."
                    )
                    continue

                if source_key in disabled_source_dependency_keys:
                    dropped_dependency = True
                    warnings.append(
                        f"Removed dependency on flag '{source_key}' because that flag is disabled in the source project."
                    )
                    continue

                target_flag = target_flags_by_key.get(source_key)
                if target_flag and target_flag.active:
                    prop["key"] = str(target_flag.id)
                    kept_properties.append(prop)
                elif target_flag and not target_flag.active:
                    dropped_dependency = True
                    warnings.append(
                        f"Removed dependency on flag '{source_key}' because that flag is disabled in the target project."
                    )
                elif source_key in restricted_target_dependency_keys:
                    dropped_dependency = True
                    warnings.append(RESTRICTED_TARGET_DEPENDENCY_REMAP_WARNING)
                else:
                    dropped_dependency = True
                    warnings.append(
                        f"Removed dependency on flag '{source_key}' because no flag with that key exists in the target project."
                    )
            # Dropping a dependency that leaves a group with no other constraints turns it into a
            # 100%-rollout group that matches everyone, so flag it for review before re-enabling.
            if dropped_dependency and not kept_properties:
                warnings.append(
                    "A condition group now has no remaining constraints and will match all users at its rollout percentage — review and re-gate it before re-enabling this flag."
                )
            group["properties"] = kept_properties
        return warnings

    def _copy_feature_flag_schedules(
        self,
        source_schedules: list[ScheduledChange],
        target_flag: FeatureFlag,
        user: User,
        cohort_mapping: dict[str, int],
        cohort_cache: dict[int, CohortOrEmpty],
        schedule_dependency_contexts_by_id: dict[int, ScheduledChangeDependencyContext],
        source_dependency_keys: dict[str, str],
        disabled_source_dependency_keys: set[str],
        target_team: Team,
    ) -> list[str]:
        """Copy pending schedules, remapping cohort IDs and flag dependencies for the target project."""
        # Validate user has permission to create schedules in target project
        user_access_control = UserAccessControl(user, target_flag.team)
        user_access_level = user_access_control.get_user_access_level(target_flag)

        if not user_access_level or not access_level_satisfied_for_resource(
            "feature_flag", user_access_level, "editor"
        ):
            return (
                [
                    "Skipped scheduled changes because you do not have permission to create schedules in the target project."
                ]
                if source_schedules
                else []
            )

        schedule_dependency_warnings: list[str] = []
        source_dependency_key_values = set(source_dependency_keys.values())
        if source_dependency_keys:
            target_flag_access_context = self._get_accessible_target_flags_by_key(
                list(source_dependency_key_values),
                target_team,
            )
        else:
            target_flag_access_context = TargetFlagAccessContext(flags_by_key={}, restricted_keys=set())

        # Copy each schedule to the target flag
        for schedule in source_schedules:
            # Remap cohort IDs in schedule payload
            updated_payload = self._remap_cohort_ids_in_payload(schedule.payload, cohort_mapping, cohort_cache)
            schedule_dependency_context = schedule_dependency_contexts_by_id.get(cast(int, schedule.id))
            if schedule_dependency_context is None:
                schedule_dependency_context = ScheduledChangeDependencyContext({}, set())

            if schedule_dependency_context.error_message:
                schedule_dependency_warnings.append(schedule_dependency_context.error_message)
                schedule_dependency_warnings.append(
                    "Skipped scheduled change because one or more flag dependencies could not be safely remapped."
                )
                continue

            schedule_payload_dependency_keys = schedule_dependency_context.source_dependency_keys
            schedule_payload_disabled_dependency_keys = schedule_dependency_context.disabled_source_dependency_keys
            schedule_source_dependency_keys = {
                **source_dependency_keys,
                **schedule_payload_dependency_keys,
            }
            schedule_disabled_source_dependency_keys = (
                disabled_source_dependency_keys | schedule_payload_disabled_dependency_keys
            )

            schedule_target_flags_by_key = target_flag_access_context.flags_by_key
            schedule_restricted_target_dependency_keys = target_flag_access_context.restricted_keys
            extra_dependency_keys = [
                dependency_key
                for dependency_key in schedule_payload_dependency_keys.values()
                if dependency_key not in source_dependency_key_values
            ]
            if extra_dependency_keys:
                extra_target_flag_access_context = self._get_accessible_target_flags_by_key(
                    extra_dependency_keys, target_team
                )
                schedule_target_flags_by_key = {
                    **target_flag_access_context.flags_by_key,
                    **extra_target_flag_access_context.flags_by_key,
                }
                schedule_restricted_target_dependency_keys = (
                    target_flag_access_context.restricted_keys | extra_target_flag_access_context.restricted_keys
                )

            schedule_warnings = self._remap_flag_dependencies_in_payload(
                updated_payload,
                schedule_source_dependency_keys,
                schedule_target_flags_by_key,
                schedule_restricted_target_dependency_keys,
                schedule_disabled_source_dependency_keys,
            )
            if schedule_warnings:
                schedule_dependency_warnings.extend(schedule_warnings)
                schedule_dependency_warnings.append(
                    "Skipped scheduled change because one or more flag dependencies could not be safely remapped."
                )
                continue

            # Gate the copied schedule against the target flag's policies, same as a directly
            # created schedule — a copy that would enable/roll out a flag still needs approval.
            # Gate the CR and create the bound row in one transaction: if the row insert fails after
            # the CR is minted, the CR is orphaned and a later approval auto-applies it immediately,
            # bypassing the schedule (the same invariant create() documents and wraps).
            try:
                with transaction.atomic():
                    change_request = gate_scheduled_change(target_flag, updated_payload, user)
                    ScheduledChange.objects.create(
                        record_id=str(target_flag.id),
                        model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
                        payload=updated_payload,
                        scheduled_at=schedule.scheduled_at,
                        is_recurring=schedule.is_recurring,
                        recurrence_interval=schedule.recurrence_interval,
                        end_date=schedule.end_date,
                        cron_expression=schedule.cron_expression,
                        timezone=schedule.timezone,
                        team=target_flag.team,
                        created_by=user,
                        change_request=change_request,
                    )
            except (PolicyConflict, ApprovalRequired):
                # The copied change can't be gated with a fresh single CR on the target — it either
                # matches multiple policies (PolicyConflict) or would bind an already-approved
                # duplicate (ApprovalRequired). Skip it (fail closed) rather than copy it ungated or
                # riding on an unrelated approval — mirroring the permission skip above, we don't
                # fail the whole copy over one schedule.
                logger.warning(
                    "Skipping copy of scheduled change that cannot be independently gated on the target flag",
                    target_flag_id=target_flag.id,
                )
                continue

        return list(dict.fromkeys(schedule_dependency_warnings))

    def _remap_flag_dependencies_in_payload(
        self,
        payload: dict[str, Any],
        source_dependency_keys: dict[str, str],
        target_flags_by_key: dict[str, FeatureFlag],
        restricted_target_dependency_keys: set[str],
        disabled_source_dependency_keys: set[str] | None = None,
    ) -> list[str]:
        filters = self._get_schedule_payload_filters(payload)
        if filters is None:
            return []
        return self._remap_flag_dependencies_with_target_context(
            filters,
            source_dependency_keys,
            target_flags_by_key,
            restricted_target_dependency_keys,
            disabled_source_dependency_keys,
        )

    def _remap_cohort_ids_in_payload(
        self,
        payload: dict[str, Any],
        cohort_mapping: dict[str, int],
        cohort_cache: dict[int, CohortOrEmpty],
    ) -> dict[str, Any]:
        """Remap cohort IDs in schedule payload to target project cohorts."""
        updated_payload = copy.deepcopy(payload)
        filters = self._get_schedule_payload_filters(updated_payload)

        # Handle filters in payload (for AddReleaseCondition operations)
        if filters is None:
            return updated_payload
        for group in self._iter_filter_groups(filters):
            for prop in self._iter_group_properties(group):
                if prop.get("type") == "cohort":
                    original_cohort_id = safe_int(prop.get("value"))
                    if original_cohort_id is None:
                        continue
                    # Use cached cohort instead of querying database
                    source_cohort = cohort_cache.get(original_cohort_id)
                    if source_cohort and source_cohort.name in cohort_mapping:
                        prop["value"] = cohort_mapping[source_cohort.name]

        return updated_payload

    def _get_accessible_target_flags_by_key(
        self, dependency_keys: list[str], target_team: Team
    ) -> TargetFlagAccessContext:
        target_flags_qs = FeatureFlag.objects.filter(
            key__in=dependency_keys,
            team=target_team,
            deleted=False,
        ).select_related("team", "created_by")
        existing_target_keys = set(target_flags_qs.values_list("key", flat=True))
        accessible_target_flags = list(
            self._filter_flags_by_rbac(target_flags_qs, [target_team.id], teams_by_id={target_team.id: target_team})
        )
        accessible_target_keys = {flag.key for flag in accessible_target_flags}
        return TargetFlagAccessContext(
            flags_by_key={flag.key: flag for flag in accessible_target_flags},
            restricted_keys=existing_target_keys - accessible_target_keys,
        )

    def _filter_flags_by_rbac(
        self, flags_qs: QuerySet, team_ids: list[int], teams_by_id: dict[int, Team] | None = None
    ) -> QuerySet:
        """Apply per-team RBAC object-level filtering to a cross-team flag queryset.

        For each team, instantiate a UserAccessControl scoped to that team and apply
        filter_queryset_by_access_level so that flags the user has been explicitly denied
        (via resource-level or object-level access controls) are excluded.  Org admins
        always pass through — filter_queryset_by_access_level short-circuits for them.
        """
        teams = teams_by_id if teams_by_id is not None else {t.id: t for t in Team.objects.filter(id__in=team_ids)}

        allowed_ids: set[int] = set()
        for team_id in team_ids:
            team = teams.get(team_id)
            if team is None:
                continue
            uac = UserAccessControl(user=cast(User, self.request.user), team=team)
            team_qs = flags_qs.filter(team_id=team_id)
            filtered_qs = uac.filter_queryset_by_access_level(team_qs, include_all_if_admin=True)
            allowed_ids.update(filtered_qs.values_list("id", flat=True))

        return flags_qs.filter(id__in=allowed_ids)

    def _get_schedule_payload_filters(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        value = payload.get("value")
        if payload.get("operation") == ScheduledChange.OperationType.ADD_RELEASE_CONDITION and isinstance(value, dict):
            return value

        filters = payload.get("filters")
        if isinstance(filters, dict):
            return filters

        return None

    def _iter_filter_groups(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        groups = filters.get("groups")
        if not isinstance(groups, list):
            return []
        return [group for group in groups if isinstance(group, dict)]

    def _iter_group_properties(self, group: dict[str, Any]) -> list[dict[str, Any]]:
        properties = group.get("properties")
        if not isinstance(properties, list):
            return []
        return [prop for prop in properties if isinstance(prop, dict)]

    def _extract_cohort_ids_from_schedules(
        self,
        schedules: list[ScheduledChange],
        source_team: Team,
        seen_cohorts_cache: dict[int, CohortOrEmpty],
    ) -> list[int]:
        """Extract all cohort IDs referenced in pending scheduled changes."""
        cohort_ids: set[int] = set()

        for schedule in schedules:
            payload = schedule.payload
            filters = self._get_schedule_payload_filters(payload)
            if filters is None:
                continue
            # Check for cohorts in AddReleaseCondition operations
            for group in self._iter_filter_groups(filters):
                for prop in self._iter_group_properties(group):
                    if prop.get("type") != "cohort":
                        continue
                    cohort_id = safe_int(prop.get("value"))
                    if cohort_id is None:
                        continue

                    cohort = seen_cohorts_cache.get(cohort_id)
                    if cohort_id not in seen_cohorts_cache:
                        cohort = Cohort.objects.filter(id=cohort_id, team=source_team, deleted=False).first()
                        seen_cohorts_cache[cohort_id] = cohort or ""
                    if not cohort:
                        continue

                    cohort_ids.add(cohort.id)
                    cohort_ids.update(
                        dependency_cohort.id
                        for dependency_cohort in get_all_cohort_dependencies(
                            cohort, seen_cohorts_cache=seen_cohorts_cache
                        )
                    )

        return sort_cohorts_topologically(cohort_ids, seen_cohorts_cache)
