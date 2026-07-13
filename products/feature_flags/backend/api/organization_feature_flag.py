import copy
from typing import cast

from django.db import transaction
from django.db.models import Case, IntegerField, Q, QuerySet, Value, When

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.response import Response
from rest_framework.utils.urls import replace_query_param

from posthog.api.cohort import CohortSerializer
from posthog.api.documentation import _FallbackSerializer, extend_schema
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.shared import UserBasicSerializer
from posthog.api.utils import action
from posthog.models import Team, User
from posthog.models.filters.filter import Filter
from posthog.rbac.user_access_control import UserAccessControl
from posthog.user_permissions import UserPermissions
from posthog.utils import safe_int

from products.approvals.backend.exceptions import ApprovalRequired, PolicyConflict
from products.approvals.backend.scheduled_changes import gate_scheduled_change
from products.cohorts.backend.models.cohort import Cohort, CohortOrEmpty
from products.feature_flags.backend.api.feature_flag import FeatureFlagSerializer
from products.feature_flags.backend.encrypted_flag_payloads import (
    get_decrypted_flag_payloads,
    get_decrypted_flag_payloads_protected,
)
from products.feature_flags.backend.flag_analytics import get_cached_evaluations_7d_by_team
from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.feature_flags.backend.models.scheduled_change import ScheduledChange


class CopyFlagsRequestSerializer(serializers.Serializer):
    feature_flag_key = serializers.CharField(required=True, help_text="Key of the feature flag to copy")
    from_project = serializers.IntegerField(required=True, help_text="Source project ID to copy the flag from")
    target_project_ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=True,
        max_length=50,
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
        help_text="Warning emitted when the flag was copied but its scheduled changes failed to copy",
    )


class CopyFlagsResponseSerializer(serializers.Serializer):
    success = CopyFlagsSuccessItemSerializer(many=True, help_text="List of successfully copied flags")
    failed = CopyFlagsResultSerializer(many=True, help_text="List of failed copy attempts")


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
        request=CopyFlagsRequestSerializer,
        responses={200: CopyFlagsResponseSerializer},
    )
    @action(detail=False, methods=["post"], url_path="copy_flags", required_scopes=["feature_flag:write"])
    def copy_flags(self, request, *args, **kwargs):
        body = request.data
        feature_flag_key = body.get("feature_flag_key")
        from_project = body.get("from_project")
        target_project_ids = body.get("target_project_ids")
        copy_schedule = body.get("copy_schedule", False)  # Optional parameter to copy schedules
        disable_copied_flag = body.get("disable_copied_flag", False)

        if not feature_flag_key or not from_project or not target_project_ids:
            return Response({"error": "Missing required fields"}, status=status.HTTP_400_BAD_REQUEST)

        # Fetch the flag to copy
        try:
            flag_to_copy = FeatureFlag.objects.get(
                key=feature_flag_key,
                team__project_id=from_project,
                team__organization_id=self.organization_id,
            )
        except FeatureFlag.DoesNotExist:
            return Response({"error": "Feature flag to copy does not exist."}, status=status.HTTP_400_BAD_REQUEST)

        # Check if the user is allowed to edit the flag using new access control
        from posthog.rbac.user_access_control import UserAccessControl, access_level_satisfied_for_resource

        user_access_control = UserAccessControl(request.user, flag_to_copy.team)
        user_access_level = user_access_control.get_user_access_level(flag_to_copy)

        if not user_access_level or not access_level_satisfied_for_resource(
            "feature_flag", user_access_level, "editor"
        ):
            return Response(
                {"error": "You do not have permission to copy this flag."}, status=status.HTTP_403_FORBIDDEN
            )

        successful_projects = []
        failed_projects = []

        # Flag dependencies reference other flags by ID, which differs across projects. Like cohorts,
        # we remap them by the dependency flag's key, so resolve each source dependency ID to its key once.
        source_dependency_keys: dict[int, str] = {}
        for group in flag_to_copy.get_filters().get("groups", []) or []:
            for prop in group.get("properties", []) or []:
                if isinstance(prop, dict) and prop.get("type") == "flag":
                    dependency_id = safe_int(prop.get("key"))
                    if dependency_id is not None and dependency_id not in source_dependency_keys:
                        dependency_flag = (
                            FeatureFlag.objects.filter(id=dependency_id, team__project_id=from_project, deleted=False)
                            .only("key")
                            .first()
                        )
                        if dependency_flag:
                            source_dependency_keys[dependency_id] = dependency_flag.key

        # Get accessible teams for the user
        user_permissions = UserPermissions(user=request.user)
        accessible_team_ids = set(user_permissions.team_ids_visible_for_user)

        for target_project_id in target_project_ids:
            target_team = Team.objects.filter(project_id=target_project_id).first()
            if target_team is None or target_team.id not in accessible_team_ids:
                failed_projects.append(
                    {
                        "project_id": target_project_id,
                        "error_message": "Project not found.",
                    }
                )
                continue

            # get all linked cohorts, sorted by creation order
            seen_cohorts_cache: dict[int, CohortOrEmpty] = {}
            sorted_cohort_ids = flag_to_copy.get_cohort_ids(
                seen_cohorts_cache=seen_cohorts_cache, sort_by_topological_order=True
            )

            # Also include cohorts from scheduled changes if copying schedules
            # Fetch schedules once and reuse for both cohort extraction and copying
            source_schedules = []
            if copy_schedule:
                source_schedules = list(
                    ScheduledChange.objects.filter(
                        record_id=str(flag_to_copy.id),
                        model_name=ScheduledChange.AllowedModels.FEATURE_FLAG,
                        executed_at__isnull=True,
                        team=flag_to_copy.team,
                    )
                )
                schedule_cohort_ids = self._extract_cohort_ids_from_schedules(source_schedules)
                for cohort_id in schedule_cohort_ids:
                    if cohort_id not in seen_cohorts_cache:
                        cohort = Cohort.objects.filter(id=cohort_id, team=flag_to_copy.team, deleted=False).first()
                        if cohort:
                            seen_cohorts_cache[cohort_id] = cohort
                            sorted_cohort_ids.append(cohort_id)

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
                        name=original_cohort.name, team__project_id=target_project_id, deleted=False
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
            filters = copy.deepcopy(flag_to_copy.get_filters())

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

            flag_dependency_warnings = self._remap_flag_dependencies(filters, source_dependency_keys, target_project_id)
            if flag_to_copy.has_encrypted_payloads:
                # Decrypt payloads before copying to ensure the new flag has unencrypted payloads
                # that will be re-encrypted by the serializer if needed
                encrypted_payloads = filters.get("payloads", {})
                filters["payloads"] = get_decrypted_flag_payloads(encrypted_payloads, should_decrypt=True)

            flag_data = {
                "key": flag_to_copy.key,
                "name": flag_to_copy.name,
                "filters": filters,
                # Dropping a flag dependency leaves its condition group ungated (an empty-property
                # group matches everyone), so a copy with dropped dependencies must never land
                # enabled — force it inactive for review.
                "active": False if (disable_copied_flag or flag_dependency_warnings) else flag_to_copy.active,
                "ensure_experience_continuity": flag_to_copy.ensure_experience_continuity,
                "deleted": False,
                "evaluation_runtime": flag_to_copy.evaluation_runtime,
                "bucketing_identifier": flag_to_copy.bucketing_identifier,
                "is_remote_configuration": flag_to_copy.is_remote_configuration,
                "has_encrypted_payloads": flag_to_copy.has_encrypted_payloads,
            }
            existing_flag = FeatureFlag.objects.filter(key=feature_flag_key, team__project_id=target_project_id).first()

            context = {
                "request": request,
                "team_id": target_project_id,
                "project_id": target_project_id,
            }

            # Set method to PATCH for updates, POST for new creations
            # This ensures proper validation scoping for feature flag creation
            if existing_flag:
                request.method = "PATCH"
                feature_flag_serializer = FeatureFlagSerializer(
                    existing_flag, data=flag_data, partial=True, context=context
                )
            # Create new flag
            else:
                request.method = "POST"
                feature_flag_serializer = FeatureFlagSerializer(data=flag_data, context=context)

            try:
                feature_flag_serializer.is_valid(raise_exception=True)
                saved_flag = feature_flag_serializer.save(team_id=target_project_id)

                # Copy schedules if requested
                schedule_copy_error = None
                if copy_schedule:
                    try:
                        self._copy_feature_flag_schedules(
                            source_schedules,
                            saved_flag,
                            request.user,
                            name_to_dest_cohort_id,
                            seen_cohorts_cache,
                        )
                    except Exception as e:
                        logger.exception(
                            "Failed to copy feature flag schedules",
                            source_flag_id=flag_to_copy.id,
                            target_flag_id=saved_flag.id,
                        )
                        schedule_copy_error = str(e)

                result = feature_flag_serializer.data
                if schedule_copy_error:
                    result["schedule_copy_warning"] = f"Flag copied but schedules failed: {schedule_copy_error}"
                if flag_dependency_warnings:
                    result["flag_dependency_warnings"] = flag_dependency_warnings
                successful_projects.append(result)
            except Exception as e:
                failed_projects.append(
                    {
                        "project_id": target_project_id,
                        "error_message": str(e)
                        if not feature_flag_serializer.errors
                        else feature_flag_serializer.errors,
                    }
                )

        return Response(
            {"success": successful_projects, "failed": failed_projects},
            status=status.HTTP_200_OK,
        )

    def _remap_flag_dependencies(
        self, filters: dict, source_dependency_keys: dict[int, str], target_project_id: int
    ) -> list[str]:
        """Remap flag-dependency references to the matching flag in the target project.

        Flag dependencies store the parent flag's ID, which differs across projects, so we match by
        key — the same approach used for cohorts. When no active flag with that key exists in the
        target project, the dependency is dropped and a warning is returned rather than failing the
        whole copy (the validator would otherwise reject a dangling or disabled dependency).
        """
        warnings: list[str] = []
        # Resolve every source dependency key to its target flag in one query per target, rather than
        # querying once per flag-type property (mirrors the batched source-dependency scan upstream).
        target_flags_by_key = {
            flag.key: flag
            for flag in FeatureFlag.objects.filter(
                key__in=source_dependency_keys.values(), team__project_id=target_project_id, deleted=False
            ).only("id", "key", "active")
        }
        for group in filters.get("groups", []) or []:
            # Leave groups without a properties key untouched so we don't change the filter shape
            # (an injected empty list would otherwise alter every copied flag's serialized filters).
            if not group.get("properties"):
                continue
            kept_properties = []
            dropped_dependency = False
            for prop in group.get("properties", []) or []:
                if not (isinstance(prop, dict) and prop.get("type") == "flag"):
                    kept_properties.append(prop)
                    continue

                source_dependency_id = safe_int(prop.get("key"))
                source_key = (
                    source_dependency_keys.get(source_dependency_id) if source_dependency_id is not None else None
                )

                if source_key is None:
                    # The source dependency itself couldn't be resolved (e.g. it was soft-deleted), so
                    # there's no key to match in the target — drop it and name the unresolved source id.
                    dropped_dependency = True
                    warnings.append(
                        f"Removed a flag dependency (source flag id {prop.get('key')}) because the dependency flag could not be resolved in the source project."
                    )
                    continue

                target_flag = target_flags_by_key.get(source_key)
                if target_flag and target_flag.active:
                    # Preserve the original key type (dependencies are typically stored as strings)
                    prop["key"] = str(target_flag.id) if isinstance(prop.get("key"), str) else target_flag.id
                    kept_properties.append(prop)
                elif target_flag and not target_flag.active:
                    dropped_dependency = True
                    warnings.append(
                        f"Removed dependency on flag '{source_key}' because that flag is disabled in the target project."
                    )
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

    def _copy_feature_flag_schedules(self, source_schedules, target_flag, user, cohort_mapping, cohort_cache):
        """
        Copy all scheduled changes from source flag to target flag.

        Args:
            source_schedules: List of ScheduledChange objects to copy (already fetched)
            target_flag: The newly created/updated FeatureFlag instance
            user: The user performing the copy operation
            cohort_mapping: Dict mapping source cohort names to target cohort IDs
            cohort_cache: Dict of cohort_id -> Cohort objects to avoid N+1 queries
        """
        from posthog.rbac.user_access_control import UserAccessControl, access_level_satisfied_for_resource

        # Validate user has permission to create schedules in target project
        user_access_control = UserAccessControl(user, target_flag.team)
        user_access_level = user_access_control.get_user_access_level(target_flag)

        if not user_access_level or not access_level_satisfied_for_resource(
            "feature_flag", user_access_level, "editor"
        ):
            # Skip copying schedules if user lacks permissions, don't fail the entire operation
            return

        # Copy each schedule to the target flag
        for schedule in source_schedules:
            # Remap cohort IDs in schedule payload
            updated_payload = self._remap_cohort_ids_in_payload(schedule.payload, cohort_mapping, cohort_cache)

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

    def _remap_cohort_ids_in_payload(self, payload, cohort_mapping, cohort_cache):
        """Remap cohort IDs in schedule payload to target project cohorts."""
        updated_payload = copy.deepcopy(payload)

        # Handle filters in payload (for AddReleaseCondition operations)
        if "filters" in updated_payload and "groups" in updated_payload["filters"]:
            for group in updated_payload["filters"]["groups"]:
                for prop in group.get("properties", []):
                    if isinstance(prop, dict) and prop.get("type") == "cohort":
                        try:
                            original_cohort_id = int(prop["value"])
                            # Use cached cohort instead of querying database
                            source_cohort = cohort_cache.get(original_cohort_id)
                            if source_cohort and source_cohort.name in cohort_mapping:
                                prop["value"] = cohort_mapping[source_cohort.name]
                        except (ValueError, TypeError):
                            continue

        return updated_payload

    def _filter_flags_by_rbac(self, flags_qs: QuerySet, team_ids: list[int]) -> QuerySet:
        """Apply per-team RBAC object-level filtering to a cross-team flag queryset.

        For each team, instantiate a UserAccessControl scoped to that team and apply
        filter_queryset_by_access_level so that flags the user has been explicitly denied
        (via resource-level or object-level access controls) are excluded.  Org admins
        always pass through — filter_queryset_by_access_level short-circuits for them.
        """
        teams = {t.id: t for t in Team.objects.filter(id__in=team_ids)}

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

    def _extract_cohort_ids_from_schedules(self, schedules):
        """Extract all cohort IDs referenced in pending scheduled changes."""
        cohort_ids = set()

        for schedule in schedules:
            payload = schedule.payload
            # Check for cohorts in AddReleaseCondition operations
            if "filters" in payload and "groups" in payload["filters"]:
                for group in payload["filters"]["groups"]:
                    for prop in group.get("properties", []):
                        if isinstance(prop, dict) and prop.get("type") == "cohort":
                            try:
                                cohort_id = int(prop["value"])
                                cohort_ids.add(cohort_id)
                            except (ValueError, TypeError):
                                continue

        return list(cohort_ids)
