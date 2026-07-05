from __future__ import annotations

import re
import copy
import json
import math
import logging
import functools
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any, Optional, cast

from django.conf import settings
from django.contrib.postgres.aggregates import ArrayAgg
from django.db import transaction
from django.db.models import Count, Prefetch, Q, QuerySet, deletion

import structlog
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse, extend_schema_field
from rest_framework import exceptions, request, serializers, status, viewsets
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

from posthog.schema import ProductKey, PropertyOperator

from posthog.hogql.property import parse_semver

from posthog.api.cohort import CohortSerializer
from posthog.api.documentation import FeatureFlagFiltersSchemaSerializer, extend_schema
from posthog.api.forbid_destroy_model import ForbidDestroyModel
from posthog.api.mixins import validated_request
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.scoped_related_fields import TeamScopedPrimaryKeyRelatedField
from posthog.api.services.flags_service import get_flags_from_service
from posthog.api.shared import UserBasicSerializer
from posthog.api.tagged_item import TaggedItemSerializerMixin, TaggedItemViewSetMixin
from posthog.api.utils import ClassicBehaviorBooleanFieldSerializer, ErrorResponseSerializer, action
from posthog.auth import (
    IDJagAccessTokenAuthentication,
    OAuthAccessTokenAuthentication,
    PersonalAPIKeyAuthentication,
    ProjectSecretAPIKeyAuthentication,
    TeamSecretTokenAuthentication,
)
from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.constants import FlagRequestType
from posthog.event_usage import report_user_action
from posthog.exceptions import Conflict
from posthog.exceptions_capture import capture_exception
from posthog.helpers.dashboard_templates import add_enriched_insights_to_feature_flag_dashboard
from posthog.helpers.impersonation import is_impersonated
from posthog.models import Team
from posthog.models.activity_logging.activity_log import Detail, load_activity, log_activity
from posthog.models.activity_logging.activity_page import ActivityLogPaginatedResponseSerializer, activity_page_response
from posthog.models.activity_logging.model_activity import ImpersonatedContext
from posthog.models.person.point_in_time_properties import (
    build_person_properties_at_time,
    get_person_and_distinct_ids_for_identifier,
)
from posthog.models.property import Property
from posthog.permissions import TeamSecretTokenPermission, get_authenticator_scopes, is_service_auth
from posthog.ph_client import feature_enabled_or_false
from posthog.queries.base import determine_parsed_date_for_property_matching
from posthog.rate_limit import (
    ClickHouseBurstRateThrottle,
    ClickHouseSustainedRateThrottle,
    PersonalOrProjectSecretApiKeyRateThrottle,
    ProjectSecretApiKeyTeamRateThrottle,
)
from posthog.rbac.access_control_api_mixin import AccessControlViewSetMixin
from posthog.rbac.user_access_control import UserAccessControlSerializerMixin
from posthog.settings.feature_flags import REMOTE_CONFIG_RATE_LIMITS
from posthog.utils import is_valid_regex
from posthog.views import format_bytes

from products.approvals.backend.decorators import approval_gate
from products.approvals.backend.mixins import ApprovalHandlingMixin
from products.cohorts.backend.models.cohort import Cohort, CohortType
from products.cohorts.backend.models.util import get_all_cohort_dependencies
from products.dashboards.backend.api.dashboard import Dashboard
from products.experiments.backend.models.experiment import Experiment, flag_has_live_experiment
from products.feature_flags.backend.api.remote_config_shadow import shadow_compare_remote_config
from products.feature_flags.backend.encrypted_flag_payloads import (
    REDACTED_PAYLOAD_VALUE,
    encrypt_flag_payloads,
    get_decrypted_flag_payloads_protected,
)
from products.feature_flags.backend.flag_analytics import increment_request_count
from products.feature_flags.backend.flag_status import (
    FeatureFlagStatusChecker,
    exclude_archived_unless_requested,
    filter_flags_by_active_param,
)
from products.feature_flags.backend.local_evaluation import _get_flag_properties_from_filters
from products.feature_flags.backend.models.evaluation_context import normalize_context_name
from products.feature_flags.backend.models.feature_flag import (
    FeatureFlag,
    FeatureFlagDashboards,
    set_feature_flags_for_team_in_cache,
)
from products.feature_flags.backend.types import PropertyFilterType
from products.feature_flags.backend.user_blast_radius import get_user_blast_radius
from products.feature_flags.backend.version_history import (
    VersionHistoryIncomplete,
    VersionNotFound,
    reconstruct_flag_at_timestamp,
    reconstruct_flag_at_version,
)
from products.product_tours.backend.models import ProductTour
from products.surveys.backend.models import Survey

logger = logging.getLogger(__name__)
# Dedicated logger name (not `__name__`) so the underlying stdlib logger is created
# *after* Django applies `disable_existing_loggers: True`. Using `__name__` here
# results in a disabled logger because `posthog.api.feature_flag` is loaded during
# Django startup. Remove this logger together with the helper once the scope is enforced.
scope_audit_logger = structlog.get_logger("posthog.feature_flag_scope_audit")

BEHAVIOURAL_COHORT_FOUND_ERROR_CODE = "behavioral_cohort_found"

REALTIME_COHORT_FLAG_TARGETING_FLAG = "realtime-cohort-flag-targeting"
EARLY_EXIT_FLAG = "feature-flag-early-exit"

# Gates enforcement of `feature_flag:write` on cross-resource flag mutations
# (Survey / Early Access Feature endpoints). Kept off during the migration grace
# period so we can notify affected customers before flipping it on per-org, then
# to 100%. Remove the gate and make enforcement unconditional once fully rolled out.
ENFORCE_FEATURE_FLAG_WRITE_SCOPE_FLAG = "enforce-feature-flag-write-scope-cross-resource"


def parse_created_by_ids(value: Any) -> list[int]:
    """Parse a `created_by_id` filter value into a list of user IDs.

    Accepts a single int/str, a comma-separated string, or a JSON-encoded list
    (as sent by the frontend creator multi-select). Keeps the original
    single-value query param working for existing API consumers.
    """
    if value is None:
        return []
    if isinstance(value, bool):
        return []
    if isinstance(value, int):
        return [value]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                value = json.loads(text)
            except (json.JSONDecodeError, ValueError, RecursionError):
                # Looks like a JSON list but doesn't parse — treat as no valid IDs
                # rather than comma-splitting, which would half-apply malformed input
                # (e.g. "[1,2" -> ["[1", "2"] -> silently filters by user 2).
                return []
        else:
            value = text.split(",")
    if not isinstance(value, list):
        value = [value]

    ids: list[int] = []
    for item in value:
        try:
            ids.append(int(item))
        except (TypeError, ValueError):
            continue
    return ids


# Fields that Rust's FeatureFlag struct expects for historical evaluation
RUST_FLAG_FIELDS = (
    "name",
    "active",
    "deleted",
    "version",
    "filters",
    "bucketing_identifier",
    "evaluation_runtime",
    "ensure_experience_continuity",
    "evaluation_tags",
)


def _is_enforce_feature_flag_write_scope_enabled(request, *, team_id: int | None) -> bool:
    # Rollout gate for the feature_flag:write enforcement below. Evaluated against the
    # organization that owns the *target* team, not the actor's current organization —
    # otherwise a multi-org user could dodge enforcement by switching their current org
    # to one where the rollout is off. Fails open (returns False) on missing context or
    # any error, so a flag-service outage degrades to warn-only rather than blocking
    # writes; the error is logged so a persistent failure is visible rather than silent.
    user = getattr(request, "user", None)
    if user is None or user.is_anonymous or team_id is None:
        return False
    try:
        organization_id = str(Team.objects.values_list("organization_id", flat=True).get(pk=team_id))
        return feature_enabled_or_false(
            ENFORCE_FEATURE_FLAG_WRITE_SCOPE_FLAG,
            user.distinct_id,
            groups={"organization": organization_id},
            group_properties={"organization": {"id": organization_id}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    except Exception:
        logger.warning("enforce_feature_flag_write_scope_eval_failed", exc_info=True)
        return False


def _scope_audit_identity(authenticator) -> tuple[list[str], str, str | None, str | None] | None:
    # (scopes, auth_kind, auth_id, auth_label) for a scoped token, or None for session and
    # other non-token auth. Scope extraction is single-sourced via get_authenticator_scopes
    # so the enforcement decision can't drift from APIScopePermission; the auth_kind/id/label
    # below are audit-log metadata only.
    scopes = get_authenticator_scopes(authenticator)
    if scopes is None:
        return None
    if isinstance(authenticator, PersonalAPIKeyAuthentication):
        key = authenticator.personal_api_key
        return scopes, "personal_api_key", key.id, key.label
    if isinstance(authenticator, OAuthAccessTokenAuthentication):
        raw_id = getattr(authenticator.access_token, "id", None)
        return scopes, "oauth_access_token", str(raw_id) if raw_id is not None else None, None
    if isinstance(authenticator, IDJagAccessTokenAuthentication):
        return scopes, "id_jag_access_token", None, None
    psak = authenticator.project_secret_api_key
    return scopes, "project_secret_api_key", str(getattr(psak, "id", "")) or None, None


def assert_feature_flag_write_scope(
    request,
    *,
    action: str,
    resource_scope: str,
    team_id: int | None = None,
    feature_flag_id: int | None = None,
) -> None:
    # Survey and Early Access Feature endpoints write FeatureFlag rows under their own
    # scope. Require feature_flag:write for those writes too: always audit-log when it's
    # missing, and raise once the rollout gate is enabled for the org.
    identity = _scope_audit_identity(getattr(request, "successful_authenticator", None))
    if identity is None:
        return  # session / cookie auth has no scopes; access control is handled elsewhere
    scopes, auth_kind, auth_id, auth_label = identity

    if "*" in scopes or "feature_flag:write" in scopes:
        return

    scope_audit_logger.warning(
        "feature_flag_write_via_other_scope",
        action=action,
        team_id=team_id,
        feature_flag_id=feature_flag_id,
        scopes=scopes,
        auth_kind=auth_kind,
        auth_id=auth_id,
        auth_label=auth_label,
        user_id=getattr(getattr(request, "user", None), "id", None),
    )

    if _is_enforce_feature_flag_write_scope_enabled(request, team_id=team_id):
        # Tailor the remediation to the token type — only personal API keys are edited on the
        # user-api-keys settings page; OAuth / ID-JAG / project-secret keys are managed elsewhere.
        if auth_kind == "personal_api_key":
            key_guidance = (
                f"Add `feature_flag:write` to your personal API key at "
                f"{settings.SITE_URL}/settings/user-api-keys (editing its scopes keeps the same key value), "
                f"or use a key with the `*` scope."
            )
        else:
            key_guidance = "Add `feature_flag:write` to the key you're using, or use a key with the `*` scope."
        raise exceptions.PermissionDenied(
            f"This action also modifies a feature flag, which requires the `feature_flag:write` scope "
            f"in addition to `{resource_scope}`. {key_guidance}"
        )


def _is_realtime_cohort_flag_targeting_enabled(request) -> bool:
    """Check whether the realtime cohort flag targeting feature is enabled for this request."""
    try:
        user = getattr(request, "user", None)
        if user is None or user.is_anonymous:
            return False
        return feature_enabled_or_false(
            REALTIME_COHORT_FLAG_TARGETING_FLAG,
            user.distinct_id,
            groups={"organization": str(user.organization.id)},
            group_properties={"organization": {"id": str(user.organization.id)}},
            only_evaluate_locally=False,
            send_feature_flag_events=False,
        )
    except Exception:
        return False


def _validate_behavioral_cohort_for_feature_flag(cohort: Cohort, *, allow_realtime_backfilled: bool = False) -> None:
    """
    Raises a validation error unless the cohort is flag-compatible.

    When allow_realtime_backfilled is True, realtime cohorts that have been backfilled
    are permitted. Otherwise all behavioral cohorts are rejected.
    """
    if allow_realtime_backfilled:
        if cohort.is_flag_compatible:
            return
        if cohort.cohort_type != CohortType.REALTIME:
            raise serializers.ValidationError(
                detail=f"Cohort '{cohort.name}' with filters on events cannot be used in feature flags.",
                code=BEHAVIOURAL_COHORT_FOUND_ERROR_CODE,
            )
        raise serializers.ValidationError(
            detail=f"Cohort '{cohort.name}' is still being backfilled and cannot be used in feature flags yet. It will become available once its initial backfill completes.",
            code=BEHAVIOURAL_COHORT_FOUND_ERROR_CODE,
        )

    raise serializers.ValidationError(
        detail=f"Cohort '{cohort.name}' with filters on events cannot be used in feature flags.",
        code=BEHAVIOURAL_COHORT_FOUND_ERROR_CODE,
    )


# Operators the Rust feature-flag evaluation service supports (OperatorType in property_models.rs).
# None means "no operator specified" which defaults to exact.
FEATURE_FLAG_SUPPORTED_OPERATORS: frozenset[str | None] = frozenset(
    {
        None,
        "exact",
        "is_not",
        "icontains",
        "not_icontains",
        "icontains_multi",
        "not_icontains_multi",
        "regex",
        "not_regex",
        "gt",
        "gte",
        "lt",
        "lte",
        "semver_gt",
        "semver_gte",
        "semver_lt",
        "semver_lte",
        "semver_eq",
        "semver_neq",
        "semver_tilde",
        "semver_caret",
        "semver_wildcard",
        "is_set",
        "is_not_set",
        "is_date_exact",
        "is_date_after",
        "is_date_before",
        "in",
        "not_in",
        "flag_evaluates_to",
    }
)

FEATURE_FLAG_OPERATOR_ALIASES: dict[str, str] = {
    "min": "gte",
    "max": "lte",
}

FEATURE_FLAG_CREATION_CONTEXT_CHOICES = (
    "feature_flags",
    "experiments",
    "surveys",
    "early_access_features",
    "web_experiments",
    "product_tours",
)


def find_dependent_flags(flag_to_check: FeatureFlag) -> list[FeatureFlag]:
    """Find all active flags that depend on the given flag via flag-type filter properties."""
    return list(
        # nosemgrep: python.django.security.audit.query-set-extra.avoid-query-set-extra (parameterized via params)
        FeatureFlag.objects.filter(team=flag_to_check.team, active=True)
        .exclude(id=flag_to_check.id)
        .extra(
            where=[
                """
                    EXISTS (
                        SELECT 1 FROM jsonb_array_elements(filters->'groups') AS grp
                        CROSS JOIN jsonb_array_elements(grp->'properties') AS prop
                        WHERE prop->>'type' = 'flag'
                        AND prop->>'key' = %s
                    )
                    """
            ],
            params=[str(flag_to_check.id)],
        )
        .order_by("key")
    )


def raise_if_flag_has_dependents(flag: FeatureFlag, action: str = "disable") -> None:
    """Raise ValidationError if any active flags depend on *flag*.

    Centralises the format-and-raise logic so every caller (flag serializer,
    experiment service, bulk-delete) stays in sync automatically.
    """
    dependent_flags = find_dependent_flags(flag)
    if not dependent_flags:
        return
    names = ", ".join(f"{f.key} (ID: {f.id})" for f in dependent_flags[:5])
    if len(dependent_flags) > 5:
        names += f", and {len(dependent_flags) - 5} more"
    raise exceptions.ValidationError(
        f"Cannot {action} this feature flag because other flags depend on it: {names}. "
        "Please update or disable the dependent flags first."
    )


def find_dependent_flags_batch(
    flags_to_check: list[FeatureFlag],
) -> dict[int, list[FeatureFlag]]:
    """Find all active flags that depend on any of the given flags via flag-type filter properties.

    Returns a dict mapping each flag ID to its list of dependent flags.
    This is more efficient than calling find_dependent_flags for each flag individually.
    """
    if not flags_to_check:
        return {}

    # All flags should be from the same team
    team = flags_to_check[0].team
    flag_ids = [f.id for f in flags_to_check]

    # Build OR conditions for each flag ID we're checking
    # We need to find any flag that depends on ANY of these flags
    or_conditions = " OR ".join(["prop->>'key' = %s" for _ in flag_ids])

    dependent_flags = list(
        # nosemgrep: python.django.security.audit.query-set-extra.avoid-query-set-extra (parameterized via params)
        FeatureFlag.objects.filter(team=team, active=True)
        .exclude(id__in=flag_ids)
        .extra(
            where=[
                f"""
                    EXISTS (
                        SELECT 1 FROM jsonb_array_elements(filters->'groups') AS grp
                        CROSS JOIN jsonb_array_elements(grp->'properties') AS prop
                        WHERE prop->>'type' = 'flag'
                        AND ({or_conditions})
                    )
                    """
            ],
            params=[str(fid) for fid in flag_ids],
        )
        .order_by("key")
    )

    # Build the result mapping by checking which flags each dependent flag depends on
    result: dict[int, list[FeatureFlag]] = {fid: [] for fid in flag_ids}
    flag_id_strs = {str(fid) for fid in flag_ids}

    for dep_flag in dependent_flags:
        groups = dep_flag.filters.get("groups", [])
        for group in groups:
            properties = group.get("properties", [])
            for prop in properties:
                if prop.get("type") == "flag" and prop.get("key") in flag_id_strs:
                    dep_flag_id = int(prop["key"])
                    if dep_flag_id in result and dep_flag not in result[dep_flag_id]:
                        result[dep_flag_id].append(dep_flag)

    return result


def _get_flag_rollout_info(flag: FeatureFlag, checker: FeatureFlagStatusChecker) -> dict[str, Any]:
    """Compute rollout state for a flag to include in bulk delete response.

    Thin adapter over ``FeatureFlagStatusChecker.get_rollout_summary`` so the
    "fully rolled out" determination has a single source of truth. Maps the
    summary to the bulk-delete vocabulary:
      - rollout_state: "fully_rolled_out", "not_rolled_out", or "partial"
      - active_variant: variant key if a multivariate flag is fully rolled out to one variant
    """
    summary = checker.get_rollout_summary(flag)

    if summary.effectively_full_rollout:
        active_variant = None
        if summary.is_multivariate:
            # summary already established full rollout; this only fetches the winning variant key.
            # Both calls read the same in-memory flag, so they cannot disagree.
            _, active_variant = checker.is_multivariate_flag_fully_rolled_out(flag)
        return {"rollout_state": "fully_rolled_out", "active_variant": active_variant}

    # Effectively at 0%: every release condition is at 0 (max across groups is 0).
    if summary.max_rollout_percentage == 0:
        return {"rollout_state": "not_rolled_out", "active_variant": None}

    return {"rollout_state": "partial", "active_variant": None}


def calculate_filter_size_bytes(filters: dict | None) -> int:
    """Calculate the approximate byte size of a flag's filters JSON.

    Uses sorted keys and compact separators for consistent sizing regardless of
    dict ordering. The result differs slightly from PostgreSQL's JSONB text
    representation (which adds spaces after separators), but exact parity isn't
    needed -- these limits prevent abuse, not enforce precise measurements.
    """
    if not filters:
        return 0
    filter_json = json.dumps(filters, separators=(",", ":"), sort_keys=True, ensure_ascii=False)
    return len(filter_json.encode("utf-8"))


def _filter_person_properties_for_flag(
    filters: dict[str, Any], person_properties: dict[str, Any], flag_key: str | None = None
) -> dict[str, Any]:
    """
    Filter person_properties to only include keys referenced by the given flag filters.

    For historical (timestamp-based) evaluations the caller must pass the
    *reconstructed* filters, not the live record's filters — otherwise the
    response can leak property values that weren't relevant at the requested
    point in time.

    Walks ``groups`` (regular release conditions),
    ``multivariate.override_property_values`` (per-variant property overrides),
    and the ``feature_enrollment`` flag (which implies ``$feature_enrollment/<key>``).
    Cohort-typed conditions reference person properties indirectly
    via the cohort definition; this helper does not resolve cohorts, so a flag
    whose only conditions are cohort lookups returns an empty person_properties
    block.
    """
    referenced_keys: set[str] = set()

    if filters.get("feature_enrollment") and flag_key:
        referenced_keys.add(f"$feature_enrollment/{flag_key}")

    for group in filters.get("groups", []) or []:
        for prop in group.get("properties", []) or []:
            if prop.get("type") == "person" and prop.get("key"):
                referenced_keys.add(prop["key"])

    for override in (filters.get("multivariate", {}) or {}).get("override_property_values", []) or []:
        if override.get("type") == "person" and override.get("key"):
            referenced_keys.add(override["key"])

    return {key: value for key, value in person_properties.items() if key in referenced_keys}


def check_flag_limits_for_team(
    team_id: int,
    is_create: bool = True,
) -> None:
    """
    Check if creating a flag would exceed the team's flag count limit.

    Only enforced on create -- updates to existing flags don't change the count.
    """
    if not is_create:
        return

    count_limit = settings.MAX_FEATURE_FLAGS_PER_TEAM
    flag_count = FeatureFlag.objects.filter(team_id=team_id).count()

    if flag_count >= count_limit:
        raise serializers.ValidationError(
            f"Maximum of {count_limit:,} feature flags allowed per team. "
            f"Please delete unused flags or contact support to increase this limit."
        )


# Default per-key and per-team cap for remote_config. Both throttles below respect
# per-team overrides from REMOTE_CONFIG_RATE_LIMITS.
REMOTE_CONFIG_DEFAULT_RATE = "600/minute"


def _apply_remote_config_team_rate_override(throttle, view) -> None:
    # Raise or lower a specific team's remote_config cap via REMOTE_CONFIG_RATE_LIMITS. On any
    # lookup/parse failure, leave the default rate in place rather than failing the request.
    team_id = throttle.safely_get_team_id_from_view(view)
    if team_id:
        try:
            custom_rate = REMOTE_CONFIG_RATE_LIMITS.get(team_id)
            if custom_rate:
                num_requests, duration = throttle.parse_rate(custom_rate)
                throttle.rate = custom_rate
                throttle.num_requests = num_requests
                throttle.duration = duration
        except Exception:
            logger.exception("Error getting team-specific rate limit for team %s", team_id)


class RemoteConfigThrottle(PersonalOrProjectSecretApiKeyRateThrottle):
    # Per-key throttle; the PSAK-aware base also throttles PSAK requests, which the plain
    # PersonalApiKeyRateThrottle would let through.
    scope = "feature_flag_remote_config"
    rate = REMOTE_CONFIG_DEFAULT_RATE

    def allow_request(self, request, view):
        _apply_remote_config_team_rate_override(self, view)
        return super().allow_request(request, view)


class RemoteConfigProjectSecretApiKeyTeamThrottle(ProjectSecretApiKeyTeamRateThrottle):
    # Per-team aggregate cap stacked alongside the per-key RemoteConfigThrottle so a project can't
    # multiply its budget by minting many keys. Defense-in-depth for the new credential.
    scope = "feature_flag_remote_config_psak_team"
    rate = REMOTE_CONFIG_DEFAULT_RATE

    def allow_request(self, request, view):
        _apply_remote_config_team_rate_override(self, view)
        return super().allow_request(request, view)


class EvaluationTagsChecker:
    """Helper class to check if evaluation contexts feature is enabled.

    This avoids repeated feature flag checks during serialization by computing
    the result once per request.
    """

    @staticmethod
    def is_enabled(request) -> bool:
        """Check if evaluation contexts feature is enabled for the request user."""
        if not hasattr(request, "user") or request.user.is_anonymous:
            return False

        # Check FLAG_EVALUATION_TAGS feature flag
        try:
            return feature_enabled_or_false(
                "flag-evaluation-tags",
                request.user.distinct_id,
                groups={"organization": str(request.user.organization.id)},
                group_properties={"organization": {"id": str(request.user.organization.id)}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        except Exception:
            return False


class EvaluationContextSerializerMixin(serializers.Serializer):
    """
    Serializer mixin that handles evaluation contexts for feature flags.

    Evaluation contexts are independent from organizational tags — they control
    where flags evaluate at runtime (e.g. "production", "staging"). Backed by
    the EvaluationContext model, not the Tag model.
    """

    evaluation_contexts = serializers.ListField(required=False, write_only=True)

    def validate(self, attrs):
        attrs = super().validate(attrs)

        if hasattr(self, "initial_data") and "evaluation_contexts" in self.initial_data:
            raw = self.initial_data["evaluation_contexts"]
            if raw is not None:
                if not isinstance(raw, list) or len(raw) > 50:
                    raise serializers.ValidationError("evaluation_contexts must be a list of at most 50 items.")
                for item in raw:
                    if not isinstance(item, str) or len(item) > 255:
                        raise serializers.ValidationError("Invalid evaluation context name.")
                attrs["evaluation_contexts"] = list(dict.fromkeys(raw))

        return attrs

    def _is_evaluation_contexts_feature_enabled(self):
        """Check if FLAG_EVALUATION_TAGS feature flag is enabled."""
        if "request" not in self.context:
            return False

        return EvaluationTagsChecker.is_enabled(self.context["request"])

    def _attempt_set_evaluation_contexts(self, evaluation_contexts, obj):
        """Update evaluation contexts for a feature flag using efficient diff logic."""
        if not obj:
            return

        if not self._is_evaluation_contexts_feature_enabled():
            return

        from products.feature_flags.backend.models.evaluation_context import (
            EvaluationContext,
            FeatureFlagEvaluationContext,
        )

        seen: set[str] = set()
        deduped_names: list[str] = []
        for t in evaluation_contexts or []:
            name = normalize_context_name(t)
            if name not in seen:
                seen.add(name)
                deduped_names.append(name)
        deduped_set = seen

        current_context_names = set(
            FeatureFlagEvaluationContext.objects.filter(feature_flag=obj)
            .select_related("evaluation_context")
            .values_list("evaluation_context__name", flat=True)
        )

        to_add = deduped_set - current_context_names
        to_remove = current_context_names - deduped_set

        if to_remove:
            FeatureFlagEvaluationContext.objects.filter(
                feature_flag=obj, evaluation_context__name__in=to_remove
            ).delete()

        if to_add:
            for name in to_add:
                ctx, _ = EvaluationContext.objects.get_or_create(name=name, team_id=obj.team_id)
                FeatureFlagEvaluationContext.objects.create(feature_flag=obj, evaluation_context=ctx)

        if to_add or to_remove:
            self._log_evaluation_context_change(
                obj,
                before=sorted(current_context_names),
                after=sorted(deduped_set),
            )

            try:
                set_feature_flags_for_team_in_cache(obj.team.project_id)
            except Exception as e:
                capture_exception(e)

    def _log_evaluation_context_change(self, obj: FeatureFlag, before: list[str], after: list[str]) -> None:

        from posthog.models.activity_logging.activity_log import Change, Detail

        request = self.context.get("request")
        was_impersonated = is_impersonated(request)

        log_activity(
            organization_id=obj.team.organization_id,
            team_id=obj.team_id,
            user=request.user if request else obj.last_modified_by,
            was_impersonated=was_impersonated,
            item_id=obj.id,
            scope="FeatureFlag",
            activity="updated",
            detail=Detail(
                name=obj.key,
                changes=[
                    Change(
                        type="FeatureFlag",
                        field="evaluation_contexts",
                        action="changed",
                        before=before,
                        after=after,
                    )
                ],
            ),
        )

    def to_representation(self, obj):
        ret = super().to_representation(obj)

        context_names: list[str] = []

        if hasattr(obj, "_prefetched_objects_cache") and "flag_evaluation_contexts" in obj._prefetched_objects_cache:
            context_names = [ec.evaluation_context.name for ec in obj.flag_evaluation_contexts.all()]
        elif hasattr(obj, "flag_evaluation_contexts"):
            context_names = [
                ec.evaluation_context.name
                for ec in obj.flag_evaluation_contexts.select_related("evaluation_context").all()
            ]

        ret["evaluation_contexts"] = context_names

        return ret


class FeatureFlagCreateRequestSchemaSerializer(serializers.Serializer):
    key = serializers.CharField(required=False, help_text="Feature flag key.")
    name = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Feature flag description (stored in the `name` field for backwards compatibility).",
    )
    filters = FeatureFlagFiltersSchemaSerializer(required=False, help_text="Feature flag targeting configuration.")
    active = serializers.BooleanField(required=False, help_text="Whether the feature flag is active.")
    archived = serializers.BooleanField(
        required=False,
        help_text="Whether the flag is archived. Archived flags are hidden from the flag list by default and must be disabled (`active: false`).",
    )
    tags = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Organizational tags for this feature flag.",
    )
    evaluation_contexts = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Evaluation contexts that control where this flag evaluates at runtime.",
    )
    is_remote_configuration = serializers.BooleanField(
        required=False,
        allow_null=True,
        help_text="Whether this flag is a remote configuration flag that delivers a payload rather than gating a feature.",
    )
    ensure_experience_continuity = serializers.BooleanField(
        required=False,
        allow_null=True,
        help_text="Whether to persist a user's flag value across the anonymous-to-identified transition "
        "(the 'persist across authentication steps' option). Incompatible with device_id bucketing.",
    )
    evaluation_runtime = serializers.ChoiceField(
        choices=FeatureFlag.EVALUATION_RUNTIME_CHOICES,
        required=False,
        allow_null=True,
        help_text="Where this flag is allowed to evaluate: 'server' (server-side SDKs only), "
        "'client' (client-side SDKs only), or 'all' (both). Defaults to 'all'.",
    )
    bucketing_identifier = serializers.ChoiceField(
        choices=FeatureFlag.BUCKETING_IDENTIFIER_CHOICES,
        required=False,
        allow_null=True,
        help_text="Identifier used to bucket users into rollout percentages and variants: 'distinct_id' "
        "(user ID, the default) or 'device_id'. Using 'device_id' is incompatible with ensure_experience_continuity=True.",
    )


class FeatureFlagPartialUpdateRequestSchemaSerializer(serializers.Serializer):
    key = serializers.CharField(required=False, help_text="Feature flag key.")
    name = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Feature flag description (stored in the `name` field for backwards compatibility).",
    )
    filters = FeatureFlagFiltersSchemaSerializer(required=False, help_text="Feature flag targeting configuration.")
    active = serializers.BooleanField(required=False, help_text="Whether the feature flag is active.")
    archived = serializers.BooleanField(
        required=False,
        help_text="Whether the flag is archived. Archived flags are hidden from the flag list by default and must be disabled (`active: false`).",
    )
    tags = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Organizational tags for this feature flag.",
    )
    evaluation_contexts = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Evaluation contexts that control where this flag evaluates at runtime.",
    )
    is_remote_configuration = serializers.BooleanField(
        required=False,
        allow_null=True,
        help_text="Whether this flag is a remote configuration flag that delivers a payload rather than gating a feature.",
    )
    ensure_experience_continuity = serializers.BooleanField(
        required=False,
        allow_null=True,
        help_text="Whether to persist a user's flag value across the anonymous-to-identified transition "
        "(the 'persist across authentication steps' option). Incompatible with device_id bucketing.",
    )
    evaluation_runtime = serializers.ChoiceField(
        choices=FeatureFlag.EVALUATION_RUNTIME_CHOICES,
        required=False,
        allow_null=True,
        help_text="Where this flag is allowed to evaluate: 'server' (server-side SDKs only), "
        "'client' (client-side SDKs only), or 'all' (both). Defaults to 'all'.",
    )
    bucketing_identifier = serializers.ChoiceField(
        choices=FeatureFlag.BUCKETING_IDENTIFIER_CHOICES,
        required=False,
        allow_null=True,
        help_text="Identifier used to bucket users into rollout percentages and variants: 'distinct_id' "
        "(user ID, the default) or 'device_id'. Using 'device_id' is incompatible with ensure_experience_continuity=True.",
    )


class FeatureFlagExperimentSetMetadataSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="ID of the experiment linked to this flag.")
    name = serializers.CharField(help_text="Name of the experiment linked to this flag.")
    is_running = serializers.BooleanField(
        help_text="Whether the experiment is currently running (started and not yet stopped). "
        "A running experiment blocks deletion of the linked flag."
    )


class FeatureFlagSerializer(
    TaggedItemSerializerMixin,
    EvaluationContextSerializerMixin,
    UserAccessControlSerializerMixin,
    serializers.HyperlinkedModelSerializer,
):
    created_by = UserBasicSerializer(read_only=True)
    version = serializers.IntegerField(required=False, default=0)
    last_modified_by = UserBasicSerializer(read_only=True)

    # :TRICKY: Needed for backwards compatibility
    filters = serializers.DictField(source="get_filters", required=False)
    status = serializers.SerializerMethodField()

    ensure_experience_continuity = ClassicBehaviorBooleanFieldSerializer()
    has_enriched_analytics = ClassicBehaviorBooleanFieldSerializer()

    archived = serializers.BooleanField(
        required=False,
        help_text="Whether the flag is archived. Archived flags are hidden from the flag list by default and must be disabled (`active: false`).",
    )

    experiment_set = serializers.SerializerMethodField()
    experiment_set_metadata = serializers.SerializerMethodField()
    surveys: serializers.SerializerMethodField = serializers.SerializerMethodField()
    features: serializers.SerializerMethodField = serializers.SerializerMethodField()
    usage_dashboard: serializers.PrimaryKeyRelatedField = serializers.PrimaryKeyRelatedField(read_only=True)  # ty: ignore[invalid-assignment]
    analytics_dashboards = TeamScopedPrimaryKeyRelatedField(
        many=True,
        required=False,
        queryset=Dashboard.objects.all(),
    )
    is_used_in_replay_settings = serializers.SerializerMethodField()

    name = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="contains the description for the flag (field name `name` is kept for backwards-compatibility)",
    )
    can_edit = serializers.SerializerMethodField()

    CREATION_CONTEXT_CHOICES = FEATURE_FLAG_CREATION_CONTEXT_CHOICES
    creation_context = serializers.ChoiceField(
        choices=CREATION_CONTEXT_CHOICES,
        write_only=True,
        required=False,
        help_text="Indicates the origin product of the feature flag. Choices: 'feature_flags', 'experiments', 'surveys', 'early_access_features', 'web_experiments', 'product_tours'.",
    )
    _create_in_folder = serializers.CharField(required=False, allow_blank=True, write_only=True)
    _should_create_usage_dashboard = serializers.BooleanField(required=False, write_only=True, default=True)

    class Meta:
        model = FeatureFlag
        fields = [
            "id",
            "name",
            "key",
            "filters",
            "deleted",
            "active",
            "archived",
            "created_by",
            "created_at",
            "updated_at",
            "version",
            "last_modified_by",
            "ensure_experience_continuity",
            "experiment_set",
            "experiment_set_metadata",
            "surveys",
            "features",
            "rollback_conditions",
            "performed_rollback",
            "can_edit",
            "tags",
            "evaluation_contexts",
            "usage_dashboard",
            "analytics_dashboards",
            "has_enriched_analytics",
            "user_access_level",
            "creation_context",
            "is_remote_configuration",
            "has_encrypted_payloads",
            "status",
            "evaluation_runtime",
            "bucketing_identifier",
            "last_called_at",
            "_create_in_folder",
            "_should_create_usage_dashboard",
            "is_used_in_replay_settings",
        ]

    def get_can_edit(self, feature_flag: FeatureFlag) -> bool:
        from typing import cast

        from posthog.rbac.user_access_control import AccessControlLevel, access_level_satisfied_for_resource

        user_access_level = self.get_user_access_level(feature_flag)
        return bool(
            user_access_level
            and access_level_satisfied_for_resource(
                "feature_flag", cast(AccessControlLevel, user_access_level), "editor"
            )
        )

    def get_features(self, feature_flag: FeatureFlag) -> dict:
        from products.early_access_features.backend.api import MinimalEarlyAccessFeatureSerializer

        return MinimalEarlyAccessFeatureSerializer(feature_flag.features, many=True).data

    def get_surveys(self, feature_flag: FeatureFlag) -> dict:
        from products.surveys.backend.api.survey import SurveyAPISerializer

        return SurveyAPISerializer(feature_flag.surveys_linked_flag, many=True).data
        # ignoring type because mypy doesn't know about the surveys_linked_flag `related_name` relationship

    def get_is_used_in_replay_settings(self, feature_flag: FeatureFlag) -> bool:
        """Check if this feature flag is used in any team's session recording linked flag setting."""
        # Use annotated value if available (set by queryset annotation)
        if hasattr(feature_flag, "is_used_in_replay_settings_annotation"):
            return bool(feature_flag.is_used_in_replay_settings_annotation)
        # Return False if team is not available
        if not hasattr(feature_flag, "team") or feature_flag.team is None:
            return False
        # Fallback to database query if annotation is not available
        return Team.objects.filter(
            project_id=feature_flag.team.project_id,
            session_recording_linked_flag__contains={"id": feature_flag.id},
        ).exists()

    def validate(self, attrs):
        """Validate feature flag creation/update including evaluation tag requirements."""
        attrs = super().validate(attrs)

        # Run universal validations before any early returns so they always apply,
        # regardless of creation_context (surveys, etc.) or evaluation contexts.
        self._validate_device_bucketing_with_persist_auth(attrs)
        self._validate_encrypted_payloads_require_remote_config(attrs)
        self._validate_archived_flags_are_disabled(attrs)
        self._validate_flag_limits()

        request = self.context.get("request")
        if not request:
            return attrs

        # Survey flags are exempt from evaluation tag requirements
        # They are created automatically by the survey system and don't need manual tagging
        creation_context = self.initial_data.get("creation_context") if hasattr(self, "initial_data") else None
        if creation_context == "surveys":
            return attrs

        # Get the team to check if evaluation contexts are required
        # The context uses a lambda for lazy evaluation
        get_team = self.context.get("get_team")
        if not get_team:
            return attrs

        team = get_team()
        if not team or not team.require_evaluation_contexts:
            return attrs

        if not self._is_evaluation_contexts_feature_enabled():
            return attrs

        # Note: for creation_context, we use initial_data since it's metadata not part of the model
        evaluation_contexts = attrs.get("evaluation_contexts")

        if request.method == "POST":
            if not evaluation_contexts:
                raise serializers.ValidationError(
                    "At least one evaluation context is required to create a new feature flag."
                )
        elif request.method in ["PUT", "PATCH"] and self.instance:
            # Flags that already have evaluation contexts can't have them all removed,
            # but flags without contexts aren't required to add them on update (only on creation).
            if (
                hasattr(self.instance, "_prefetched_objects_cache")
                and "flag_evaluation_contexts" in self.instance._prefetched_objects_cache
            ):
                existing_context_count = len(self.instance.flag_evaluation_contexts.all())
            else:
                existing_context_count = self.instance.flag_evaluation_contexts.count()

            if existing_context_count > 0:
                if evaluation_contexts is not None and not evaluation_contexts:
                    raise serializers.ValidationError(
                        "Cannot remove all evaluation contexts. At least one evaluation context is required "
                        "because this flag already has evaluation contexts and the team requires them."
                    )

        return attrs

    def _validate_device_bucketing_with_persist_auth(self, attrs):
        """Validate that persist across auth is not enabled with device ID bucketing"""
        # bucketing_identifier is nullable (CharField(null=True)), so we use a sentinel to
        # distinguish "field absent from PATCH" from "field explicitly set to null". A bare
        # `attrs.get(...) is None` fallback would otherwise treat an explicit null as missing
        # and validate against the stale instance value.
        _MISSING: Any = object()
        bucketing_identifier = attrs.get("bucketing_identifier", _MISSING)
        ensure_experience_continuity = attrs.get("ensure_experience_continuity", _MISSING)

        if self.instance:
            if bucketing_identifier is _MISSING:
                bucketing_identifier = self.instance.bucketing_identifier
            if ensure_experience_continuity is _MISSING:
                ensure_experience_continuity = self.instance.ensure_experience_continuity

        # Prevent new combinations of device_id + ensure_experience_continuity=True
        if bucketing_identifier == "device_id" and ensure_experience_continuity is True:
            # Allow if this combination already existed (no change)
            if (
                self.instance
                and self.instance.bucketing_identifier == "device_id"
                and self.instance.ensure_experience_continuity is True
            ):
                pass  # Allow existing combination to be saved without changes
            else:
                raise serializers.ValidationError(
                    "Cannot enable 'persist across authentication steps' when using device ID bucketing. "
                    "These features are incompatible."
                )

    def _validate_archived_flags_are_disabled(self, attrs: dict) -> None:
        """An archived flag must be disabled — archived means "done for good", not paused."""
        # Resolve effective values: use incoming attrs, falling back to instance for updates
        archived = attrs.get("archived", getattr(self.instance, "archived", False) if self.instance else False)
        # On create, fall back to the model default (active=True)
        active = attrs.get("active", getattr(self.instance, "active", True) if self.instance else True)

        if not (archived and active):
            return

        # If this request set archived=True, the user is archiving an enabled flag;
        # otherwise they're enabling an already-archived flag.
        if attrs.get("archived"):
            raise serializers.ValidationError(
                "Cannot archive an enabled feature flag. Disable it first, or send active: false in the same request."
            )
        raise serializers.ValidationError("Cannot enable an archived feature flag. Unarchive it first.")

    def _validate_encrypted_payloads_require_remote_config(self, attrs: dict) -> None:
        """Encrypted payloads are only valid on remote configuration flags."""
        # Resolve effective values: use incoming attrs, falling back to instance for updates
        has_encrypted = attrs.get(
            "has_encrypted_payloads",
            getattr(self.instance, "has_encrypted_payloads", False) if self.instance else False,
        )
        is_remote = attrs.get(
            "is_remote_configuration",
            getattr(self.instance, "is_remote_configuration", False) if self.instance else False,
        )

        if has_encrypted and not is_remote:
            raise serializers.ValidationError("Encrypted payloads require the flag to be a remote configuration.")

    def validate_key(self, value):
        exclude_kwargs = {}
        if self.instance:
            exclude_kwargs = {"pk": cast(FeatureFlag, self.instance).pk}

        if (
            FeatureFlag.objects.filter(key=value, team__project_id=self.context["project_id"])
            .exclude(**exclude_kwargs)
            .exists()
        ):
            raise serializers.ValidationError("There is already a feature flag with this key.", code="unique")

        if not re.match(r"^[a-zA-Z0-9_-]+$", value):
            raise serializers.ValidationError(
                "Only letters, numbers, hyphens (-) & underscores (_) are allowed.",
                code="invalid_key",
            )

        return value

    def _validate_flag_limits(self) -> None:
        """Validate that the team has not exceeded its flag count limit."""
        check_flag_limits_for_team(
            team_id=self.context["team_id"],
            is_create=self.instance is None,
        )

    @functools.cached_property
    def _allow_realtime_backfilled(self) -> bool:
        """Lazily check whether realtime cohort flag targeting is enabled.

        This avoids a potentially expensive feature_enabled() call for flags that don't
        reference any cohort properties.
        """
        return _is_realtime_cohort_flag_targeting_enabled(self.context["request"])

    def validate_filters(self, filters):
        # For some weird internal REST framework reason this field gets validated on a partial PATCH call, even if filters isn't being updatd
        # If we see this, just return the current filters
        if "groups" not in filters and self.context["request"].method == "PATCH":
            # mypy cannot tell that self.instance is a FeatureFlag
            assert isinstance(self.instance, FeatureFlag)
            return self.instance.filters

        filters.setdefault("groups", [])

        # Only validate empty groups for new flag creation (POST), not updates (PUT/PATCH)
        # Existing flags may legitimately have empty groups temporarily during scheduled changes
        if self.context["request"].method == "POST":
            if not filters["groups"]:
                raise serializers.ValidationError("Feature flags must have at least one condition set (group).")

        flag_level_aggregation = filters.get("aggregation_group_type_index", None)

        # Validate filter field types to prevent serde deserialization failures in the
        # Rust flag evaluation service. Non-conforming types poison the entire team's
        # flag cache and cause 500s on every /flags request.
        def _validate_rollout_percentage(value: Any, path: str, *, allow_null: bool = True) -> None:
            if value is None:
                if not allow_null:
                    raise serializers.ValidationError(f"{path} must be a number, got null")
                return
            # Check bool before int/float because bool is a subclass of int
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                expected = "a number or null" if allow_null else "a number"
                raise serializers.ValidationError(f"{path} must be {expected}, got {type(value).__name__}")
            if not math.isfinite(value):
                raise serializers.ValidationError(f"{path} must be finite, got {value}")
            if value < 0 or value > 100:
                raise serializers.ValidationError(f"{path} must be between 0 and 100, got {value}")

        def _validate_integer(value: Any, path: str) -> None:
            # Check bool before int because bool is a subclass of int
            if value is not None and (isinstance(value, bool) or not isinstance(value, int)):
                raise serializers.ValidationError(f"{path} must be an integer or null, got {type(value).__name__}")

        def _validate_regex_pattern(value: Any, path: str, existing_patterns: set[str]) -> None:
            if not isinstance(value, str):
                return
            if value not in existing_patterns and not is_valid_regex(value):
                raise serializers.ValidationError(f"{path}: invalid regex pattern")

        _validate_integer(flag_level_aggregation, "aggregation_group_type_index")

        # Collect existing regex patterns so we don't reject unchanged patterns on
        # PATCH — flags may contain regexes valid in fancy_regex/PG ARE but not Python re.
        existing_patterns: set[str] = set()
        if self.instance is not None:
            for g in (self.instance.filters or {}).get("groups", []) or []:
                for p in g.get("properties", []) or []:
                    if p.get("operator") in ("regex", "not_regex") and isinstance(p.get("value"), str):
                        existing_patterns.add(p["value"])

        early_exit = filters.get("early_exit")
        if early_exit is not None and not isinstance(early_exit, bool):
            raise serializers.ValidationError(f"early_exit must be a boolean or null, got {type(early_exit).__name__}")

        # Gate enabling early_exit behind the feature-flag-early-exit flag. The UI hides
        # the toggle, but the public REST API, MCP tools, and terraform provider all reach
        # this validator — without the gate they could persist early_exit before server-side
        # local evaluation honors it. Only block newly turning it on: leaving an existing
        # truthy value unchanged (or turning it off) always passes, so flags created while
        # the feature was enabled keep working if access is later revoked.
        previously_enabled = (
            bool((self.instance.filters or {}).get("early_exit")) if self.instance is not None else False
        )
        if early_exit and not previously_enabled and not self._is_early_exit_enabled():
            raise serializers.ValidationError("early_exit is not available for this organization.")

        for group_index, group in enumerate(filters.get("groups", [])):
            variant = group.get("variant")
            if variant is not None and not isinstance(variant, str):
                raise serializers.ValidationError(
                    f"groups[{group_index}].variant must be a string or null, got {type(variant).__name__}"
                )

            _validate_rollout_percentage(group.get("rollout_percentage"), f"groups[{group_index}].rollout_percentage")
            _validate_integer(
                group.get("aggregation_group_type_index"),
                f"groups[{group_index}].aggregation_group_type_index",
            )

            for prop_index, prop in enumerate(group.get("properties", [])):
                _validate_integer(
                    prop.get("group_type_index"),
                    f"groups[{group_index}].properties[{prop_index}].group_type_index",
                )

                if prop.get("operator") in ("regex", "not_regex"):
                    _validate_regex_pattern(
                        prop.get("value"),
                        f"groups[{group_index}].properties[{prop_index}].value",
                        existing_patterns,
                    )

        for var_index, variant in enumerate((filters.get("multivariate") or {}).get("variants", [])):
            _validate_rollout_percentage(
                variant.get("rollout_percentage"),
                f"multivariate.variants[{var_index}].rollout_percentage",
                allow_null=False,
            )

        # Normalize: distribute the flag-level aggregation_group_type_index to each
        # condition set that doesn't already have one, so every condition set
        # explicitly carries its aggregation mode (including None for person-aggregated).
        for condition in filters["groups"]:
            if "aggregation_group_type_index" not in condition:
                condition["aggregation_group_type_index"] = flag_level_aggregation

        # Derive the flag-level field from condition sets for backward compatibility.
        # If all condition sets share the same aggregation, use that; when mixed,
        # set to None since the evaluation engine reads per-condition aggregation.
        condition_aggregations = [c.get("aggregation_group_type_index") for c in filters["groups"]]
        if condition_aggregations:
            if all(a == condition_aggregations[0] for a in condition_aggregations):
                filters["aggregation_group_type_index"] = condition_aggregations[0]
            else:
                filters["aggregation_group_type_index"] = None

        # Check Early Access Feature constraint: no condition set can use group
        # aggregation if the flag is linked to an Early Access Feature.
        has_group_condition = any(c.get("aggregation_group_type_index") is not None for c in filters["groups"])
        if (
            has_group_condition
            and self.instance is not None
            and hasattr(self.instance, "features")
            and self.instance.features.exists()
        ):
            raise serializers.ValidationError(
                "Cannot use group aggregation in any condition set when the flag is linked to an Early Access Feature."
            )

        # Validate properties per condition set against that condition set's aggregation.
        for condition in filters["groups"]:
            condition_aggregation = condition.get("aggregation_group_type_index")
            condition_props = condition.get("properties", [])

            for prop_dict in condition_props:
                prop = Property(**prop_dict)

                if condition_aggregation is None:
                    # Person-aggregated condition: allow person, cohort, and flag properties
                    if prop.type not in ["person", "cohort", "flag"]:
                        raise serializers.ValidationError(
                            "Filters are not valid (person-aggregated conditions can only use person, cohort, and flag properties)"
                        )
                    if prop.type == "flag" and prop_dict.get("operator") != "flag_evaluates_to":
                        raise serializers.ValidationError("Flag properties must use the 'flag_evaluates_to' operator")
                else:
                    # Group-aggregated condition: only allow group properties matching the
                    # condition's group type
                    if prop.type != "group":
                        raise serializers.ValidationError(
                            "Filters are not valid (group-aggregated conditions can only use group properties)"
                        )
                    if prop.group_type_index != condition_aggregation:
                        raise serializers.ValidationError(
                            "Filters are not valid (group properties must match the condition set's group type)"
                        )

        # Circular dependency checks only apply to person-aggregated conditions
        # since flag-based property filters only work with person aggregation
        has_person_condition = any(c.get("aggregation_group_type_index") is None for c in filters["groups"])
        if has_person_condition:
            self._check_flag_circular_dependencies(filters)

        variant_list = (filters.get("multivariate") or {}).get("variants", [])
        variants = {variant["key"] for variant in variant_list}

        # Validate rollout percentages for multivariate variants
        if variant_list:
            variant_rollout_sum = sum(variant.get("rollout_percentage", 0) for variant in variant_list)
            if variant_rollout_sum != 100:
                raise serializers.ValidationError(
                    "Invalid variant definitions: Variant rollout percentages must sum to 100.",
                    code="invalid_input",
                )

        for condition in filters["groups"]:
            if condition.get("variant") and condition["variant"] not in variants:
                raise serializers.ValidationError("Filters are not valid (variant override does not exist)")

            for property in condition.get("properties", []):
                if property.get("operator") in FEATURE_FLAG_OPERATOR_ALIASES:
                    property["operator"] = FEATURE_FLAG_OPERATOR_ALIASES[property["operator"]]

                prop = Property(**property)

                if prop.operator is not None and prop.operator not in PropertyOperator.__members__.values():
                    raise serializers.ValidationError(
                        detail=f"Invalid operator: {prop.operator}",
                        code="invalid_operator",
                    )

                if prop.operator not in FEATURE_FLAG_SUPPORTED_OPERATORS:
                    raise serializers.ValidationError(
                        detail=f"Unsupported operator for feature flags: {prop.operator}",
                        code="unsupported_operator",
                    )

                if prop.type == "cohort":
                    try:
                        initial_cohort: Cohort = Cohort.objects.get(
                            pk=cast(str | int, prop.value), team__project_id=self.context["project_id"]
                        )
                        # Static cohorts (including one-time snapshots) hold a
                        # materialised person list.  The populating criteria may
                        # still be stored on the record, but they are inert – the
                        # cohort no longer re-evaluates them, and the Rust engine's
                        # extract_dependencies returns an empty set for them.  Skip
                        # both the behavioural property check and the dependency walk
                        # so snapshot cohorts can be used in flags without an extra
                        # export step, even when their inert criteria reference
                        # another cohort.  See #65270.
                        dependency_cohorts = (
                            []
                            if initial_cohort.is_static
                            else get_all_cohort_dependencies(initial_cohort, stop_traversal_at_static=True)
                        )
                        for cohort in [initial_cohort, *dependency_cohorts]:
                            # Static cohorts have materialized membership, any preserved behavioral
                            # filters are display-only and never evaluated, so skip them.
                            if cohort.is_static:
                                continue
                            if any(cohort_prop.type == "behavioral" for cohort_prop in cohort.properties.flat):
                                _validate_behavioral_cohort_for_feature_flag(
                                    cohort, allow_realtime_backfilled=self._allow_realtime_backfilled
                                )
                    except Cohort.DoesNotExist:
                        raise serializers.ValidationError(
                            detail=f"Cohort with id {prop.value} does not exist",
                            code="cohort_does_not_exist",
                        )

                if prop.operator in (
                    PropertyOperator.IS_DATE_BEFORE,
                    PropertyOperator.IS_DATE_AFTER,
                    PropertyOperator.IS_DATE_EXACT,
                ):
                    parsed_date = determine_parsed_date_for_property_matching(prop.value)

                    if not parsed_date:
                        raise serializers.ValidationError(
                            detail=f"Invalid date value: {prop.value}",
                            code="invalid_date",
                        )

                # make sure regex, icontains, gte, lte, lt, and gt properties have string values
                if prop.operator in [
                    "regex",
                    "icontains",
                    "not_regex",
                    "not_icontains",
                    "gte",
                    "lte",
                    "gt",
                    "lt",
                ] and not isinstance(prop.value, str):
                    raise serializers.ValidationError(
                        detail=f"Invalid value for operator {prop.operator}: {prop.value}",
                        code="invalid_value",
                    )

                if prop.operator in (PropertyOperator.IN_, PropertyOperator.NOT_IN) and prop.type != "cohort":
                    raise serializers.ValidationError(
                        detail=f"The '{prop.operator}' operator is only valid for cohort properties, not '{prop.type}' properties.",
                        code="invalid_operator",
                    )

                # Currently unreachable (between/not_between rejected by FEATURE_FLAG_SUPPORTED_OPERATORS),
                # but kept so value validation is ready if Rust adds support for these operators.
                if prop.operator in (PropertyOperator.BETWEEN, PropertyOperator.NOT_BETWEEN):
                    if not isinstance(prop.value, list) or len(prop.value) != 2:
                        raise serializers.ValidationError(
                            detail=f"{prop.operator} operator requires a two-element array [min, max]",
                            code="invalid_value",
                        )
                    try:
                        min_val = prop.value[0]
                        max_val = prop.value[1]
                        # Type check: ensure both values can be converted to float
                        if not isinstance(min_val, (int, float, str)) or not isinstance(max_val, (int, float, str)):
                            raise ValueError("Values must be numeric")
                        if float(min_val) > float(max_val):
                            raise serializers.ValidationError(
                                detail=f"{prop.operator} operator requires min value to be less than or equal to max value",
                                code="invalid_value",
                            )
                    except (ValueError, TypeError):
                        raise serializers.ValidationError(
                            detail=f"{prop.operator} operator requires numeric values",
                            code="invalid_value",
                        )

                semver_operators = (
                    PropertyOperator.SEMVER_EQ,
                    PropertyOperator.SEMVER_NEQ,
                    PropertyOperator.SEMVER_GT,
                    PropertyOperator.SEMVER_GTE,
                    PropertyOperator.SEMVER_LT,
                    PropertyOperator.SEMVER_LTE,
                    PropertyOperator.SEMVER_TILDE,
                    PropertyOperator.SEMVER_CARET,
                    PropertyOperator.SEMVER_WILDCARD,
                )
                if prop.operator in semver_operators:
                    if not isinstance(prop.value, str):
                        raise serializers.ValidationError(
                            detail=f"Invalid value for operator {prop.operator}: expected a semver string",
                            code="invalid_value",
                        )
                    try:
                        semver_value = prop.value
                        if str(prop.operator) == PropertyOperator.SEMVER_WILDCARD:
                            semver_value = semver_value.rstrip(".*")
                        parse_semver(semver_value)
                    except (ValueError, IndexError):
                        raise serializers.ValidationError(
                            detail=f"Invalid semver value for operator {prop.operator}: {prop.value}",
                            code="invalid_value",
                        )

                if prop.operator in (
                    PropertyOperator.ICONTAINS_MULTI,
                    PropertyOperator.NOT_ICONTAINS_MULTI,
                ):
                    if not isinstance(prop.value, list):
                        raise serializers.ValidationError(
                            detail=f"{prop.operator} operator requires a list of values",
                            code="invalid_value",
                        )

        payloads = filters.get("payloads", {})

        if not isinstance(payloads, dict):
            raise serializers.ValidationError("Payloads must be passed as a dictionary")

        for key, value in payloads.items():
            try:
                if isinstance(value, str):
                    # An incoming string is already the canonical stored form; just check it parses.
                    json.loads(value)
                else:
                    # Normalize any non-string JSON value (objects, arrays, numbers, booleans, null)
                    # to a JSON string, matching what the UI sends.
                    payloads[key] = json.dumps(value)
            except json.JSONDecodeError:
                raise serializers.ValidationError("Payload value is not valid JSON")
            except (TypeError, ValueError):
                # Defensive: request bodies are JSON-parsed, so values are always JSON-native
                # (str/int/float/bool/None/dict/list) and serializable. Unreachable via the API.
                raise serializers.ValidationError("Payload value could not be serialized to JSON")

        if filters.get("multivariate"):
            if not all(key in variants for key in payloads):
                raise serializers.ValidationError("Payload keys must match a variant key for multivariate flags")
        else:
            if len(payloads) > 1 or any(key != "true" for key in payloads):  # only expect one key
                raise serializers.ValidationError("Payload keys must be 'true' for boolean flags")

        # Validate per-flag filter size
        filter_size = calculate_filter_size_bytes(filters)
        per_flag_limit = settings.MAX_FEATURE_FLAG_FILTER_SIZE_BYTES

        if filter_size > per_flag_limit:
            raise serializers.ValidationError(
                f"Feature flag filters exceed maximum size of {format_bytes(per_flag_limit)}. "
                f"Current size: {format_bytes(filter_size)}. "
                f"Please simplify conditions or reduce payload sizes."
            )

        return filters

    def _validate_flag_reference(self, flag_reference):
        """Validate and convert flag reference to flag key."""
        from posthog.utils import safe_int

        flag_id = safe_int(flag_reference)
        if flag_id is None:
            raise serializers.ValidationError(
                f"Flag dependencies must reference flag IDs (integers), not flag keys. "
                f"Invalid reference: '{flag_reference}'"
            )

        try:
            flag = FeatureFlag.objects.get(id=flag_id, team__project_id=self.context["project_id"])

            # Check if the referenced flag is active
            if not flag.active:
                raise serializers.ValidationError(
                    f"Cannot create dependency on disabled flag '{flag.key}' (ID: {flag_id}). "
                    f"Flag dependencies must reference active flags only."
                )

            return flag.key
        except FeatureFlag.DoesNotExist:
            raise serializers.ValidationError(f"Flag dependency references non-existent flag with ID {flag_id}")

    def _get_properties_from_filters(self, filters: dict, property_type: PropertyFilterType | None = None):
        """
        Extract properties from filters by iterating through groups.

        Args:
            filters: The filters dictionary containing groups
            property_type: Optional filter by property type (e.g., 'flag', 'cohort')

        Yields:
            Property dictionaries matching the criteria
        """
        for group in filters.get("groups", []):
            for prop in group.get("properties", []):
                if property_type is None or prop.get("type") == property_type:
                    yield prop

    def _get_cohort_properties_from_filters(self, filters: dict):
        """Extract cohort properties from filters."""
        return list(self._get_properties_from_filters(filters, PropertyFilterType.COHORT))

    def _get_group_key_properties_from_filters(self, filters: dict):
        """Extract $group_key properties from group-type filters."""
        return [
            prop
            for prop in self._get_properties_from_filters(filters, PropertyFilterType.GROUP)
            if prop.get("key") == "$group_key"
        ]

    def _extract_flag_dependencies(self, filters):
        """Extract flag dependencies from filters."""
        dependencies = set()
        for flag_prop in _get_flag_properties_from_filters(filters):
            flag_reference = flag_prop.get("key")
            if flag_reference:
                flag_key = self._validate_flag_reference(flag_reference)
                dependencies.add(flag_key)
        return dependencies

    def _is_early_exit_enabled(self) -> bool:
        try:
            request = self.context.get("request")
            if not request:
                return False
            user = getattr(request, "user", None)
            if user is None or user.is_anonymous:
                return False
            return feature_enabled_or_false(
                EARLY_EXIT_FLAG,
                user.distinct_id,
                groups={"organization": str(user.organization.id)},
                group_properties={"organization": {"id": str(user.organization.id)}},
                only_evaluate_locally=False,
                send_feature_flag_events=False,
            )
        except Exception:
            logger.exception("Failed to check early exit flag")
            return False

    def _check_flag_circular_dependencies(self, filters):
        """Check for circular dependencies in feature flag conditions."""

        current_flag_key = getattr(self.instance, "key", None) if self.instance else self.initial_data.get("key")
        if not current_flag_key:
            return

        flag_dependencies = self._extract_flag_dependencies(filters)
        if not flag_dependencies:
            return

        # Check for self-reference
        if current_flag_key in flag_dependencies:
            raise serializers.ValidationError(f"Feature flag '{current_flag_key}' cannot depend on itself")

        # Check for cycles using DFS
        def has_cycle(flag_key, path):
            if flag_key in path:
                cycle_path = [*path[path.index(flag_key) :], flag_key]
                cycle_display = " → ".join(cycle_path)
                raise serializers.ValidationError(f"Circular dependency detected: {cycle_display}")

            try:
                flag = FeatureFlag.objects.get(
                    key=flag_key,
                    team__project_id=self.context["project_id"],
                )
                flag_deps = self._extract_flag_dependencies(flag.filters or {})
                for dep_key in flag_deps:
                    has_cycle(dep_key, [*path, flag_key])
            except FeatureFlag.DoesNotExist:
                return  # Non-existent flags have no dependencies

        # Check each dependency for cycles
        for dep_flag_key in flag_dependencies:
            has_cycle(dep_flag_key, [current_flag_key])

    def _free_key_held_by_soft_deleted_flags(self, key: str, exclude_pk: int | None = None) -> None:
        # The (team, key) unique constraint spans soft-deleted rows, so we must
        # clear any tombstone holding `key`. Hard-delete first; if an FK blocks
        # it (Experiment uses RESTRICT, EarlyAccessFeature uses PROTECT), rename
        # the tombstone instead — same scheme as the soft-delete update path.
        # Only safe when no active dependent references it; re-check that
        # invariant and error clearly if violated.
        soft_deleted_qs = FeatureFlag.objects_including_soft_deleted.filter(
            key=key,
            team__project_id=self.context["project_id"],
            deleted=True,
        )
        if exclude_pk is not None:
            soft_deleted_qs = soft_deleted_qs.exclude(pk=exclude_pk)

        for flag in soft_deleted_qs:
            try:
                flag.delete()
            except (deletion.RestrictedError, deletion.ProtectedError):
                blockers = []
                active_experiment_ids = list(flag.experiment_set.filter(deleted=False).values_list("id", flat=True))
                if active_experiment_ids:
                    blockers.append(f"active experiment(s) with ID(s): {', '.join(map(str, active_experiment_ids))}")
                eaf_count = flag.features.count()
                if eaf_count:
                    blockers.append(f"{eaf_count} early access feature(s)")
                if blockers:
                    raise exceptions.ValidationError(
                        f"Cannot reuse key '{flag.key}': a soft-deleted flag with this key is still "
                        f"referenced by {' and '.join(blockers)}. Please contact support."
                    )
                flag.key = flag.tombstoned_key()
                flag.save(update_fields=["key"])

    def create(self, validated_data: dict, *args: Any, **kwargs: Any) -> FeatureFlag:
        request = self.context["request"]
        validated_data["created_by"] = request.user
        validated_data["last_modified_by"] = request.user
        validated_data["team_id"] = self.context["team_id"]
        validated_data["version"] = 1  # This is the first version of the feature flag
        tags = validated_data.pop("tags", None)  # tags are created separately below as global tag relationships
        evaluation_contexts = validated_data.pop("evaluation_contexts", None)
        creation_context = validated_data.pop(
            "creation_context", "feature_flags"
        )  # default to "feature_flags" if an alternative value is not provided

        should_create_usage_dashboard = validated_data.pop("_should_create_usage_dashboard")
        self._update_filters(validated_data)

        # Set default filters for remote config flags to 100% rollout
        if validated_data.get("is_remote_configuration", False):
            filters = validated_data.get("filters", {}) or {}
            groups = filters.get("groups", [])

            # If no groups exist, create one with 100% rollout
            if not groups:
                filters["groups"] = [{"properties": [], "rollout_percentage": 100, "variant": None}]
                validated_data["filters"] = filters
            else:
                # If groups exist, update any with 0% or None rollout to 100%
                for group in groups:
                    if group.get("rollout_percentage") in [0, None]:
                        group["rollout_percentage"] = 100

        encrypt_flag_payloads(validated_data)

        self._free_key_held_by_soft_deleted_flags(validated_data["key"])

        analytics_dashboards = validated_data.pop("analytics_dashboards", None)

        with ImpersonatedContext(request):
            instance: FeatureFlag = super().create(validated_data)

        self._attempt_set_tags(tags, instance)
        self._attempt_set_evaluation_contexts(evaluation_contexts, instance)

        if should_create_usage_dashboard:
            _create_usage_dashboard(instance, request.user)

        if analytics_dashboards is not None:
            for dashboard in analytics_dashboards:
                # nosemgrep: idor-lookup-without-team -- dashboard objects validated via get_fields() queryset restriction
                FeatureFlagDashboards.objects.get_or_create(dashboard=dashboard, feature_flag=instance)

        analytics_metadata = instance.get_analytics_metadata()
        analytics_metadata["creation_context"] = creation_context
        report_user_action(
            request.user,
            "feature flag created",
            analytics_metadata,
            team=instance.team,
            request=request,
        )

        return instance

    @approval_gate(["feature_flag.enable", "feature_flag.disable", "feature_flag.update"])
    def update(self, instance: FeatureFlag, validated_data: dict, *args: Any, **kwargs: Any) -> FeatureFlag:
        request = self.context["request"]
        # This is a workaround to ensure update works when called from a scheduled task.
        if request and not hasattr(request, "data"):
            request.data = {}

        validated_data["last_modified_by"] = request.user
        # Prevent DRF from attempting to set reverse FK relation directly
        validated_data.pop("evaluation_contexts", None)

        if "deleted" in validated_data and validated_data["deleted"] is True:
            # Check for linked early access features
            if instance.features.count() > 0:
                raise exceptions.ValidationError(
                    "Cannot delete a feature flag that is in use with early access features. Please delete the early access feature before deleting the flag."
                )

            # Check for linked running experiments. Draft, stopped, and completed
            # experiments may keep the flag so their historical results are preserved;
            # only a currently running experiment blocks deletion.
            running_experiments = [exp for exp in instance.experiment_set.filter(deleted=False) if exp.is_running]
            if running_experiments:
                experiment_names = ", ".join(f'"{exp.name}" (ID: {exp.id})' for exp in running_experiments)
                raise exceptions.ValidationError(
                    f"Cannot delete a feature flag that is linked to running experiment(s): {experiment_names}. Please stop the experiment(s) before deleting the flag."
                )

            # Check for other flags that depend on this flag
            raise_if_flag_has_dependents(instance, action="delete")

            # Check if flag is used in session replay settings
            if Team.objects.filter(
                project_id=instance.team.project_id,
                session_recording_linked_flag__contains={"id": instance.id},
            ).exists():
                raise exceptions.ValidationError(
                    "This feature flag is used in session replay settings. Please remove it from replay settings before deleting."
                )

            # If the flag is linked to any experiment, rename the key to free it up.
            # Append ID to the key when soft-deleting to prevent key conflicts.
            # Experiments reference the flag by FK, so referential integrity is preserved.
            if instance.experiment_set.exists():
                validated_data["key"] = instance.tombstoned_key()

        if "deleted" in validated_data and validated_data["deleted"] is False:
            # Restoring a soft-deleted flag — if the key was renamed during
            # soft-delete, restore the original key. If the original key has
            # been claimed by another flag, append a numeric suffix.
            original_key = instance.key_without_tombstone()
            if original_key != instance.key:
                candidate = original_key
                counter = 2
                while (
                    FeatureFlag.objects_including_soft_deleted.filter(
                        key=candidate, team__project_id=self.context["project_id"]
                    )
                    .exclude(pk=instance.pk)
                    .exists()
                ):
                    candidate = f"{original_key}-{counter}"
                    counter += 1
                validated_data["key"] = candidate

        # Check for dependency conflicts when disabling a flag
        if "active" in validated_data and validated_data["active"] is False and instance.active is True:
            raise_if_flag_has_dependents(instance)

        # Check for dependency conflicts when enabling a flag
        if "active" in validated_data and validated_data["active"] is True and instance.active is False:
            # Check if this flag depends on any disabled flags
            disabled_dependencies = self._find_disabled_dependencies(instance)
            if disabled_dependencies:
                disabled_flag_names = [f"{flag.key} (ID: {flag.id})" for flag in disabled_dependencies[:5]]
                if len(disabled_dependencies) > 5:
                    disabled_flag_names.append(f"and {len(disabled_dependencies) - 5} more")
                raise exceptions.ValidationError(
                    f"Cannot enable this feature flag because it depends on disabled flags: {', '.join(disabled_flag_names)}. "
                    f"Please enable the dependency flags first."
                )

        self._update_filters(validated_data)

        # Resolve `has_encrypted_payloads` against the instance so a partial PATCH
        # that omits the boolean still routes through the right path.
        effective_has_encrypted = validated_data.get("has_encrypted_payloads", instance.has_encrypted_payloads)

        if effective_has_encrypted:
            # Ensure downstream helpers (e.g. encrypt_flag_payloads) see the
            # flag even when the client didn't echo it back in this PATCH.
            validated_data["has_encrypted_payloads"] = True
            filters = validated_data.get("filters")
            new_true_payload = ((filters or {}).get("payloads") or {}).get("true")

            if not new_true_payload or new_true_payload == REDACTED_PAYLOAD_VALUE:
                # Preserve the existing encrypted payload when the request didn't
                # supply a fresh one — either because `filters.payloads` was
                # omitted (partial PATCH from the V2 form), the redacted
                # placeholder was echoed back, or an empty string slipped past
                # `validate_filters` (defense in depth: the public API rejects
                # `""` as invalid JSON upstream, but direct serializer callers
                # could still land here). Only re-inject when `filters` is
                # being sent, so a filters-less PATCH stays a partial update.
                if filters is not None:
                    existing_true_payload = (instance.filters or {}).get("payloads", {}).get("true")
                    if not existing_true_payload:
                        raise exceptions.ValidationError(
                            "An encrypted payload is required when has_encrypted_payloads is true."
                        )
                    payloads = filters.get("payloads") or {}
                    payloads["true"] = existing_true_payload
                    filters["payloads"] = payloads
            else:
                encrypt_flag_payloads(validated_data)

        elif instance.has_encrypted_payloads:
            # Downgrading from encrypted to non-encrypted. Strip leftover
            # ciphertext so a partial PATCH that only flipped the bit doesn't
            # leave the prior encrypted blob exposed as a normal payload on
            # subsequent reads (redaction is gated on has_encrypted_payloads).
            filters = validated_data.get("filters")
            if filters is None:
                # Client didn't send filters; inject a copy of instance.filters
                # with the encrypted "true" payload removed.
                new_filters = copy.deepcopy(instance.filters or {})
                payloads = new_filters.get("payloads") or {}
                payloads.pop("true", None)
                new_filters["payloads"] = payloads
                validated_data["filters"] = new_filters
            else:
                # Client sent filters. Drop an empty/missing/redacted echo at
                # "true"; a fresh non-empty plaintext is left alone (the user
                # explicitly set a new payload during the downgrade).
                payloads = filters.get("payloads") or {}
                true_val = payloads.get("true")
                if not true_val or true_val == REDACTED_PAYLOAD_VALUE:
                    payloads.pop("true", None)
                filters["payloads"] = payloads

        # Opportunistically strip legacy keys on save.
        previous_filters = validated_data.get("filters") or instance.filters
        if previous_filters and ("holdout_groups" in previous_filters or "super_groups" in previous_filters):
            validated_data["filters"] = {
                k: v for k, v in previous_filters.items() if k not in ("holdout_groups", "super_groups")
            }

        version = request.data.get("version", -1)

        with transaction.atomic():
            # select_for_update locks the database row so we ensure version updates are atomic.
            # Uses objects_including_soft_deleted so that restoring a soft-deleted flag
            # (setting deleted=False) can acquire the lock.
            locked_instance = FeatureFlag.objects_including_soft_deleted.select_for_update().get(pk=instance.pk)
            locked_version = locked_instance.version or 0

            # NOW check for conflicts after all transformations
            if version != -1 and version != locked_version:
                conflicting_changes = self._get_conflicting_changes(
                    locked_instance,
                    validated_data,
                    request.data.get("original_flag", {}),
                )
                if len(conflicting_changes) > 0:
                    raise Conflict(
                        f"The feature flag was updated by {locked_instance.last_modified_by.email if locked_instance.last_modified_by else 'another user'} since you started editing it. Please refresh and try again."
                    )

            # Continue with the update
            validated_data["version"] = locked_version + 1
            old_key = instance.key

            # Clear any soft-deleted tombstone on `new_key` so the (team, key)
            # unique constraint doesn't block the rename. Mirrors create().
            new_key = validated_data.get("key")
            if new_key and new_key != old_key and validated_data.get("deleted", instance.deleted) is False:
                self._free_key_held_by_soft_deleted_flags(new_key, exclude_pk=instance.pk)

            with ImpersonatedContext(request):
                instance = super().update(instance, validated_data)

        # Continue with the update outside of the transaction. This is an intentional choice
        # to avoid deadlocks. Not to mention, before making the concurrency changes, these
        # updates were already occurring outside of a transaction.

        # Handle evaluation contexts (uses initial_data like TaggedItemSerializerMixin does)
        # Only update if explicitly provided in request, otherwise preserve existing contexts
        # Accept both field names; prefer evaluation_contexts if provided
        if "evaluation_contexts" in self.initial_data:
            evaluation_data = self.initial_data.get("evaluation_contexts")
            self._attempt_set_evaluation_contexts(evaluation_data, instance)

        analytics_dashboards = validated_data.pop("analytics_dashboards", None)

        if analytics_dashboards is not None:
            for dashboard in analytics_dashboards:
                # nosemgrep: idor-lookup-without-team -- dashboard objects validated via get_fields() queryset restriction
                FeatureFlagDashboards.objects.get_or_create(dashboard=dashboard, feature_flag=instance)

        # The linked feature flag is the source of truth for variants and aggregation group type.
        # Experiment reads derive these from the flag (see ExperimentBaseSerializer), so there is no
        # longer a `parameters` mirror to keep in sync here.

        if old_key != instance.key:
            _update_feature_flag_dashboard(instance, old_key)

        report_user_action(
            request.user,
            "feature flag updated",
            instance.get_analytics_metadata(),
            team=instance.team,
            request=request,
        )

        # If flag is using encrypted payloads, replace them with redacted string or unencrypted value
        # if the request was made with a personal API key
        if instance.has_encrypted_payloads:
            instance.filters["payloads"] = get_decrypted_flag_payloads_protected(
                request, instance.filters.get("payloads", {})
            )

        return instance

    def _get_conflicting_changes(
        self,
        current_instance: FeatureFlag,
        validated_data: dict,
        original_flag: dict | None,
    ) -> list[str]:
        """
        Returns the list of fields that have conflicts. A conflict is defined as a field that
        the current user is trying to change that has been changed by another user.

        If the field in validated_data is different from the original_flag, then the current user
        is trying to change it.

        If a field that the user is trying to change is different in the current_instance, then
        there is a conflict.
        """

        if original_flag is None or original_flag == {}:
            return []

        # Get the fields that the user is trying to change
        user_changes = [
            field
            for field, new_value in validated_data.items()
            if field in original_flag and new_value != original_flag[field]
        ]

        # Return the fields that have conflicts
        # Only include fields where the user's intended change is different from the current value
        # AND the original value is different from the current value (indicating someone else changed it)
        return [
            field
            for field in user_changes
            if field in original_flag
            and original_flag[field] != getattr(current_instance, field)
            and validated_data[field] != getattr(current_instance, field)
        ]

    def _find_disabled_dependencies(self, flag_to_check: FeatureFlag) -> list[FeatureFlag]:
        """Find all disabled flags that the given flag depends on."""
        dependency_ids = []

        # Extract flag dependencies from filters
        filters = flag_to_check.filters or {}
        for group in filters.get("groups", []):
            for prop in group.get("properties", []):
                if prop.get("type") == "flag":
                    dependency_ids.append(int(prop.get("key")))

        if not dependency_ids:
            return []

        # Find disabled dependency flags
        return list(
            FeatureFlag.objects.filter(
                team=flag_to_check.team,
                id__in=dependency_ids,
                active=False,
            ).order_by("key")
        )

    def _update_filters(self, validated_data):
        if "get_filters" in validated_data:
            validated_data["filters"] = validated_data.pop("get_filters")

        active = validated_data.get("active", None)
        if active:
            validated_data["performed_rollback"] = False

    def get_status(self, feature_flag: FeatureFlag) -> str:
        checker = FeatureFlagStatusChecker(feature_flag=feature_flag)
        flag_status, _ = checker.get_status()
        return flag_status.name

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        filters = representation.get("filters", {})

        # Get all cohort IDs used in the feature flag
        cohort_ids = set()
        for cohort_prop in self._get_cohort_properties_from_filters(filters):
            cohort_ids.add(cohort_prop.get("value"))

        # Use prefetched cohorts if available
        if hasattr(instance.team, "available_cohorts"):
            cohorts = {
                str(cohort.id): cohort.name
                for cohort in instance.team.available_cohorts
                if str(cohort.id) in map(str, cohort_ids)
            }
        else:
            # Fallback to database query if cohorts weren't prefetched
            cohorts = {
                str(cohort.id): cohort.name
                for cohort in Cohort.objects.filter(id__in=cohort_ids, team__project_id=self.context["project_id"])
            }

        # Add cohort names to the response
        for cohort_prop in self._get_cohort_properties_from_filters(filters):
            cohort_prop["cohort_name"] = cohorts.get(str(cohort_prop.get("value")))

        # Resolve group key display names for $group_key filters. Check both
        # the flag-level and per-condition-set aggregation_group_type_index to
        # find the relevant group type indices.
        group_key_props = self._get_group_key_properties_from_filters(filters)
        if group_key_props:
            group_type_indices: set[int] = set()
            flag_level_index = filters.get("aggregation_group_type_index")
            if flag_level_index is not None:
                group_type_indices.add(flag_level_index)
            for condition_group in filters.get("groups", []):
                condition_index = condition_group.get("aggregation_group_type_index")
                if condition_index is not None:
                    group_type_indices.add(condition_index)

            if group_type_indices:
                group_keys: set[str] = set()
                for prop in group_key_props:
                    prop_value = prop.get("value")
                    if isinstance(prop_value, list):
                        group_keys.update(str(v) for v in prop_value)
                    elif prop_value is not None:
                        group_keys.add(str(prop_value))

                if group_keys:
                    from posthog.models.group.util import get_groups_by_type_indices

                    group_names: dict[str, str] = {}
                    for group in get_groups_by_type_indices(instance.team_id, group_type_indices, group_keys):
                        name = group.group_properties.get("name")
                        group_names[group.group_key] = str(name) if name else group.group_key

                    for prop in group_key_props:
                        prop["group_key_names"] = group_names

        representation["filters"] = filters
        return representation

    def get_experiment_set(self, obj: FeatureFlag) -> list[int]:
        # Use the prefetched active experiments
        if hasattr(obj, "_active_experiments"):
            return [exp.id for exp in obj._active_experiments]
        return [exp.id for exp in obj.experiment_set.filter(deleted=False)]

    @extend_schema_field(FeatureFlagExperimentSetMetadataSerializer(many=True))
    def get_experiment_set_metadata(self, obj: FeatureFlag) -> list[dict]:
        # Use the prefetched active experiments
        if hasattr(obj, "_active_experiments"):
            experiments = obj._active_experiments
        else:
            experiments = obj.experiment_set.filter(deleted=False)
        # `is_running` mirrors the deletion guard: only a running experiment blocks flag deletion
        return [{"id": exp.id, "name": exp.name, "is_running": exp.is_running} for exp in experiments]


def _create_usage_dashboard(feature_flag: FeatureFlag, user):
    from posthog.helpers.dashboard_templates import create_feature_flag_dashboard

    from products.dashboards.backend.models.dashboard import Dashboard

    usage_dashboard = Dashboard.objects.create(
        name="Generated Dashboard: " + feature_flag.key + " Usage",
        description="This dashboard was generated by the feature flag with key (" + feature_flag.key + ")",
        team=feature_flag.team,
        created_by=user,
        creation_mode="template",
    )
    create_feature_flag_dashboard(feature_flag, usage_dashboard, user)

    feature_flag.usage_dashboard = usage_dashboard
    feature_flag.save()

    return usage_dashboard


def _update_feature_flag_dashboard(feature_flag: FeatureFlag, old_key: str) -> None:
    from posthog.helpers.dashboard_templates import update_feature_flag_dashboard

    if not old_key:
        return

    update_feature_flag_dashboard(feature_flag, old_key)


class GroupsJSONField(serializers.CharField):
    """
    CharField that parses JSON object strings.
    Matches legacy behavior of json.loads(request.GET.get("groups", "{}")).
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("default", "{}")
        kwargs.setdefault("allow_blank", True)
        kwargs.setdefault("help_text", "Groups for feature flag evaluation (JSON object string)")
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        # Handle case where data is already a dict (from previous parsing or direct assignment)
        if isinstance(data, dict):
            return data

        value = super().to_internal_value(data)
        if not value:
            return {}
        try:
            parsed = json.loads(value)
            if not isinstance(parsed, dict):
                raise serializers.ValidationError("groups must be a JSON object")
            return parsed
        except (json.JSONDecodeError, ValueError):
            raise serializers.ValidationError("Invalid JSON in groups parameter")


class MyFlagsQuerySerializer(serializers.Serializer):
    groups = GroupsJSONField()


class EvaluationReasonsQuerySerializer(serializers.Serializer):
    distinct_id = serializers.CharField(required=True, help_text="User distinct ID")
    groups = GroupsJSONField()
    flag_keys = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        allow_empty=True,
        help_text=(
            "Optional list of flag keys to scope the response to. When omitted, evaluation reasons are "
            "returned for every flag in the project, which can be a very large payload on projects with "
            "many flags. Pass the specific flag(s) you are debugging to keep the response small."
        ),
    )


class ActivityQuerySerializer(serializers.Serializer):
    limit = serializers.IntegerField(required=False, default=10, min_value=1, help_text="Number of items per page")
    page = serializers.IntegerField(required=False, default=1, min_value=1, help_text="Page number")


class EvaluationReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(help_text="The reason for the evaluation result")
    condition_index = serializers.IntegerField(
        allow_null=True,
        help_text="The index of the condition that matched, if applicable",
    )


class FlagEvaluationResultSerializer(serializers.Serializer):
    value = serializers.JSONField(help_text="The evaluated value of the feature flag (boolean or variant key string)")
    evaluation = EvaluationReasonSerializer()


class EvaluationReasonsResponseSerializer(serializers.Serializer):
    """
    Response for evaluation_reasons endpoint.

    Structure: Dict[flag_key: str, FlagEvaluationResultSerializer]
    See OpenApiExample for concrete shape.
    """

    pass


class FeatureFlagRolloutSummarySerializer(serializers.Serializer):
    effectively_full_rollout = serializers.BooleanField(
        help_text=(
            "True if the flag is effectively rolled out to everyone, independent of recent evaluation. "
            "For boolean flags this means at least one release condition targets 100% with no property "
            "filters (or there are no release conditions); for multivariate flags it means a single variant "
            "is served to 100% via a fully rolled out release condition. This is the signal for "
            "'fully rolled out' / GA — unlike `status`, which only reflects recent evaluation."
        )
    )
    has_targeting_conditions = serializers.BooleanField(
        help_text=(
            "True if any release condition has property filters, i.e. the flag is conditionally targeted "
            "rather than a blanket rollout. When true, `max_rollout_percentage` is a percentage within the "
            "targeted segment, not of the whole user base."
        )
    )
    max_rollout_percentage = serializers.IntegerField(
        allow_null=True,
        help_text=(
            "Highest rollout percentage (0-100) across the flag's release conditions, treating a missing "
            "percentage as 100. Null when the flag has no release conditions. Interpret together with "
            "`has_targeting_conditions`."
        ),
    )
    is_multivariate = serializers.BooleanField(
        help_text="True if the flag serves multiple variants (has a multivariate variant set)."
    )


class FeatureFlagStatusResponseSerializer(serializers.Serializer):
    status = serializers.CharField(
        help_text=(
            "Flag staleness/evaluation status: active, stale, archived, deleted, or unknown. 'active' means the flag "
            "was recently evaluated (or has no usage data yet) — it does NOT mean the flag is fully rolled "
            "out. Use the `rollout` object to determine rollout completeness."
        )
    )
    reason = serializers.CharField(help_text="Human-readable explanation of the status")
    rollout = FeatureFlagRolloutSummarySerializer(
        help_text="Summary of the flag's rollout configuration, for determining whether it is fully rolled out."
    )


class DependentFlagSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="Feature flag ID")
    key = serializers.CharField(help_text="Feature flag key")
    name = serializers.CharField(help_text="Feature flag name")


class FeatureFlagTestEvaluationRequestSerializer(serializers.Serializer):
    distinct_id = serializers.CharField(
        required=False,
        allow_blank=False,
        help_text="User distinct ID to test against (mutually exclusive with person_id)",
    )
    person_id = serializers.CharField(
        required=False, allow_blank=False, help_text="Person ID to test against (mutually exclusive with distinct_id)"
    )
    timestamp = serializers.DateTimeField(
        required=False,
        allow_null=True,
        help_text=(
            "Optional point-in-time to evaluate the flag against — both flag conditions "
            "and person properties are reconstructed as they existed at that timestamp. "
            "ISO 8601 with timezone, e.g. ``2026-04-29T15:30:00Z`` or ``2026-04-29T15:30:00+00:00``. "
            "Naive timestamps (no timezone) are interpreted as UTC."
        ),
    )
    groups = serializers.JSONField(
        required=False,
        default=dict,
        help_text="Groups for feature flag evaluation (JSON object, defaults to empty dict)",
    )

    def validate(self, attrs):
        distinct_id = attrs.get("distinct_id")
        person_id = attrs.get("person_id")

        if not distinct_id and not person_id:
            raise serializers.ValidationError("Either distinct_id or person_id must be provided")

        if distinct_id and person_id:
            raise serializers.ValidationError("Cannot provide both distinct_id and person_id")

        return attrs


class FeatureFlagConditionPropertyAnalysisSerializer(serializers.Serializer):
    key = serializers.CharField(help_text="Property key")
    operator = serializers.CharField(help_text="Comparison operator")
    value = serializers.JSONField(help_text="Expected property value")
    type = serializers.CharField(help_text="Property type (person, group, etc.)")
    actual_value = serializers.JSONField(allow_null=True, help_text="Actual property value from user")
    matched = serializers.BooleanField(help_text="Whether this property condition matched")
    explanation = serializers.CharField(help_text="Human-readable explanation of the match result")


class FeatureFlagConditionAnalysisSerializer(serializers.Serializer):
    index = serializers.IntegerField(help_text="Index of this condition in the feature flag")
    matched = serializers.BooleanField(
        help_text=(
            "True when this condition was the one that determined the flag's outcome. "
            "Use this to find the winning condition — at most one condition per flag is True."
        )
    )
    properties_matched = serializers.BooleanField(
        required=False,
        help_text=(
            "True when every property in this condition evaluated to true, regardless of "
            "whether this condition was the eventual winner."
        ),
    )
    explanation = serializers.CharField(
        help_text="Human-readable explanation of why this condition matched/didn't match"
    )
    rollout_percentage = serializers.FloatField(help_text="Rollout percentage for this condition (0.0-100.0)")
    rollout_excluded = serializers.BooleanField(
        help_text="Whether this condition matched properties but was excluded due to rollout"
    )
    variant = serializers.CharField(allow_null=True, help_text="Variant associated with this condition")
    properties = FeatureFlagConditionPropertyAnalysisSerializer(
        many=True, help_text="Analysis of each property in this condition"
    )


class FeatureFlagTestEvaluationResponseSerializer(serializers.Serializer):
    flag_key = serializers.CharField(help_text="Feature flag key")
    result = serializers.JSONField(help_text="The evaluated value of the feature flag (boolean or variant key string)")
    reason = serializers.CharField(help_text="The reason for the evaluation result")
    condition_index = serializers.IntegerField(
        allow_null=True, help_text="The index of the condition that matched, if applicable"
    )
    payload = serializers.JSONField(allow_null=True, help_text="Payload associated with the flag result, if any")
    person_properties = serializers.DictField(
        help_text="Person properties at the time of evaluation (for historical evaluations)"
    )
    evaluation_distinct_id = serializers.CharField(
        allow_null=True,
        help_text=(
            "The distinct_id used for rollout/variant bucketing. Echoes the caller-provided "
            "distinct_id when one was sent; null on the person_id path so the endpoint doesn't "
            "leak the person's other distinct_ids to a feature_flag:read-only token."
        ),
    )
    conditions = FeatureFlagConditionAnalysisSerializer(
        many=True, help_text="Detailed analysis of each condition in the feature flag"
    )


class FeatureFlagVersionResponseSerializer(serializers.ModelSerializer):
    """Feature flag state at a given version plus reconstruction metadata."""

    created_by = serializers.IntegerField(read_only=True, allow_null=True)
    filters = serializers.DictField(read_only=True)
    is_historical = serializers.BooleanField(
        read_only=True,
        help_text="False for the current version; true for reconstructed historical versions.",
    )
    version_timestamp = serializers.DateTimeField(read_only=True, allow_null=True)
    modified_by = serializers.IntegerField(
        read_only=True,
        allow_null=True,
        help_text="User from the activity log entry that produced this version.",
    )

    class Meta:
        model = FeatureFlag
        fields = [
            "id",
            "key",
            "name",
            "filters",
            "active",
            "deleted",
            "version",
            "rollback_conditions",
            "performed_rollback",
            "ensure_experience_continuity",
            "has_enriched_analytics",
            "is_remote_configuration",
            "has_encrypted_payloads",
            "evaluation_runtime",
            "bucketing_identifier",
            "last_called_at",
            "created_at",
            "created_by",
            "is_historical",
            "version_timestamp",
            "modified_by",
        ]


class UserBlastRadiusRequestSerializer(serializers.Serializer):
    condition = serializers.DictField(required=True, help_text="The release condition to evaluate")
    group_type_index = serializers.IntegerField(
        required=False,
        allow_null=True,
        default=None,
        help_text="Group type index for group-based flags (null for person-based flags)",
    )


class UserBlastRadiusResponseSerializer(serializers.Serializer):
    affected = serializers.IntegerField(
        help_text="Number of entities matching the condition (users or groups depending on group_type_index)"
    )
    total = serializers.IntegerField(help_text="Total number of entities of this type in the project")


# HYPERCACHE CONTRACT: This serializer defines the JSON schema that the Rust feature-flags
# service deserializes. Field changes (renames, removals, type changes) must follow the
# expand-and-contract pattern. Run the contract tests to verify compatibility:
#   pytest posthog/models/feature_flag/test/test_flags_cache.py -k "test_serializer_output_matches_fixture_schema"
# See also: rust/feature-flags/src/flags/flag_models.rs (FeatureFlag struct)
class MinimalFeatureFlagSerializer(serializers.ModelSerializer):
    filters = serializers.DictField(source="get_filters", required=False)
    evaluation_contexts = serializers.SerializerMethodField()

    class Meta:
        model = FeatureFlag
        fields = [
            "id",
            "team_id",
            "name",
            "key",
            "filters",
            "deleted",
            "active",
            "ensure_experience_continuity",
            "version",
            "evaluation_runtime",
            "bucketing_identifier",
            "evaluation_contexts",
        ]

    def get_evaluation_contexts(self, feature_flag: FeatureFlag) -> list[str]:
        try:
            cached = getattr(feature_flag, "_evaluation_tag_names", None)
            if cached is not None:
                return cached or []

            if (
                hasattr(feature_flag, "_prefetched_objects_cache")
                and "flag_evaluation_contexts" in feature_flag._prefetched_objects_cache
            ):
                return [ec.evaluation_context.name for ec in feature_flag.flag_evaluation_contexts.all()]

            from products.feature_flags.backend.models.evaluation_context import FeatureFlagEvaluationContext

            return list(
                FeatureFlagEvaluationContext.objects.filter(feature_flag=feature_flag)
                .select_related("evaluation_context")
                .values_list("evaluation_context__name", flat=True)
            )
        except Exception:
            return []


class EvaluationFeatureFlagSerializer(MinimalFeatureFlagSerializer):
    """Flag representation for the SDK-facing evaluation paths: the flags cache the Rust
    service reads (`serialize_feature_flags`) and the local-evaluation response.

    Adds `has_experiment` on top of the minimal flag shape. It lives here rather than on
    MinimalFeatureFlagSerializer so the many UI endpoints that embed the minimal serializer
    (surveys, early access features, product tours, experiments, my_flags) don't each pay a
    per-flag experiment lookup for a field only the SDKs consume.
    """

    has_experiment = serializers.SerializerMethodField(
        help_text=(
            "True if the flag has at least one non-deleted linked experiment. SDKs use this to decide whether "
            "to keep all $feature_flag_called event properties or send a minimal event."
        )
    )

    class Meta(MinimalFeatureFlagSerializer.Meta):
        fields = [*MinimalFeatureFlagSerializer.Meta.fields, "has_experiment"]

    def get_has_experiment(self, feature_flag: FeatureFlag) -> bool:
        # The evaluation/cache batch queries annotate `_has_experiment` via a bulk Exists,
        # so this avoids an N+1. The exists() fallback only fires for unannotated callers.
        cached = getattr(feature_flag, "_has_experiment", None)
        if cached is not None:
            return cached
        return flag_has_live_experiment(feature_flag.pk)


class MyFlagsResponseSerializer(serializers.Serializer):
    feature_flag = MinimalFeatureFlagSerializer()
    value = serializers.JSONField()


class MyFlagsResponseListSerializer(serializers.ListSerializer):
    child = MyFlagsResponseSerializer()


class BulkKeysRequestSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.JSONField(),
        required=False,
        allow_empty=True,
        help_text=(
            "Feature flag IDs to look up keys for. Strings of digits are also accepted; any other value "
            "is reported in the response `warning` field and otherwise ignored."
        ),
    )


class BulkKeysResponseSerializer(serializers.Serializer):
    keys = serializers.DictField(
        child=serializers.CharField(),
        help_text="Mapping of feature flag ID (as a string) to flag key, for IDs that exist in this project.",
    )
    warning = serializers.CharField(
        required=False,
        help_text="Present when some submitted IDs were not numeric and were ignored.",
    )


class BulkDeleteFiltersSerializer(serializers.Serializer):
    """Allowed filter keys for bulk_delete — same shape as the list endpoint's query params."""

    active = serializers.ChoiceField(
        choices=["true", "false", "STALE"],
        required=False,
        help_text="Filter by active state.",
    )
    created_by_id = serializers.IntegerField(
        required=False,
        help_text="Filter to flags created by a specific user ID.",
    )
    search = serializers.CharField(
        required=False,
        help_text="Search by feature flag key or name (case-insensitive).",
    )
    type = serializers.ChoiceField(
        choices=["boolean", "multivariant", "experiment", "remote_config"],
        required=False,
        help_text="Filter by flag type.",
    )
    evaluation_runtime = serializers.ChoiceField(
        choices=FeatureFlag.EVALUATION_RUNTIME_CHOICES,
        required=False,
        help_text="Filter by evaluation runtime.",
    )
    excluded_properties = serializers.CharField(
        required=False,
        help_text="JSON-encoded property filter to exclude. Same shape as the list endpoint.",
    )
    tags = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Tag names to filter by. Flags carrying at least one of these tags match.",
    )
    excluded_tags = serializers.ListField(
        child=serializers.CharField(),
        required=False,
        help_text="Tag names to exclude. Flags carrying any of these tags are filtered out.",
    )
    has_evaluation_contexts = serializers.BooleanField(
        required=False,
        help_text="When true, only matches flags with at least one evaluation context.",
    )
    archived = serializers.BooleanField(
        required=False,
        help_text="Filter by archived state. When omitted, archived flags are excluded.",
    )


class BulkDeleteRequestSerializer(serializers.Serializer):
    filters = BulkDeleteFiltersSerializer(
        required=False,
        help_text=(
            "Filter criteria — same shape as the list endpoint's query params. Mutually exclusive with `ids`. "
            "Use this to bulk-delete by search/active/tags/etc. instead of supplying explicit IDs."
        ),
    )
    ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        help_text="Explicit feature flag IDs to soft-delete. Mutually exclusive with `filters`.",
    )


class BulkDeleteDeletedItemSerializer(serializers.Serializer):
    id = serializers.IntegerField(help_text="ID of the soft-deleted flag.")
    key = serializers.CharField(help_text="The flag key at the time of deletion.")
    rollout_state = serializers.ChoiceField(
        choices=["fully_rolled_out", "not_rolled_out", "partial"],
        help_text="Rollout state captured before deletion.",
    )
    active_variant = serializers.CharField(
        allow_null=True,
        help_text="Variant key when a multivariate flag was fully rolled out to a single variant; otherwise null.",
    )


class BulkDeleteErrorItemSerializer(serializers.Serializer):
    id = serializers.JSONField(
        help_text="Feature flag ID — integer for valid inputs; the original raw value for invalid inputs."
    )
    key = serializers.CharField(required=False, help_text="The flag key, when known.")
    reason = serializers.CharField(help_text="Human-readable reason the flag could not be deleted.")


class BulkDeleteResponseSerializer(serializers.Serializer):
    """
    Schema-only — referenced from ``@extend_schema(responses=...)`` to describe the wire format.
    Never instantiate this for validation or call ``.is_valid()`` / ``.errors`` on it: the
    declared ``errors`` field shadows DRF's inherited ``Serializer.errors`` ReturnDict property,
    so accessing ``serializer.errors`` would return this field descriptor instead of validation
    errors. The handler builds the response dict directly; this class exists only so drf-spectacular
    can render the response in the OpenAPI spec and downstream generated clients.
    """

    deleted = BulkDeleteDeletedItemSerializer(many=True, help_text="Flags successfully soft-deleted.")
    # Explicit ListSerializer avoids the many=True descriptor magic that confuses type checkers.
    errors: serializers.ListSerializer = serializers.ListSerializer(  # type: ignore[assignment]
        child=BulkDeleteErrorItemSerializer(),
        help_text="Flags that could not be deleted, with reasons.",
    )


# ClickHouse cost attribution: this viewset currently has no direct ClickHouse calls —
# all ClickHouse work is delegated to helpers (user_blast_radius.py, flag_analytics.py)
# that already tag their queries. If you add a new ClickHouse query reachable from an
# action on this viewset, wrap it with tag_queries(product=Product.FEATURE_FLAGS,
# feature=Feature.QUERY, team_id=self.team_id) so query_log attribution stays correct.
# See posthog/models/feature_flag/user_blast_radius.py for the pattern.
@extend_schema(extensions={"x-product": ProductKey.FEATURE_FLAGS})
class FeatureFlagViewSet(
    ApprovalHandlingMixin,
    TeamAndOrgViewSetMixin,
    AccessControlViewSetMixin,
    TaggedItemViewSetMixin,
    ForbidDestroyModel,
    viewsets.ModelViewSet,
):
    """
    Create, read, update and delete feature flags. [See docs](https://posthog.com/docs/feature-flags) for more information on feature flags.

    If you're looking to use feature flags on your application, you can either use our JavaScript Library or our dedicated endpoint to check if feature flags are enabled for a given user.
    """

    scope_object = "feature_flag"
    psak_allowed_actions = ["remote_config"]
    # Opt the shared TaggedItemViewSetMixin action into feature_flag:write.
    # Other inheritors of the mixin don't extend write actions and so still
    # reject PAT calls — keeps the scope local to this viewset.
    scope_object_write_actions = ["create", "update", "partial_update", "patch", "destroy", "bulk_update_tags"]
    # Use the unfiltered manager so non-list actions (retrieve, update, etc.)
    # can access soft-deleted flags. The list action applies its own
    # deleted=False filter in safely_get_queryset.
    queryset = FeatureFlag.objects_including_soft_deleted.all()
    serializer_class = FeatureFlagSerializer

    @extend_schema(request=FeatureFlagCreateRequestSchemaSerializer)
    def create(self, request, *args, **kwargs):
        return super().create(request, *args, **kwargs)

    @extend_schema(request=FeatureFlagPartialUpdateRequestSchemaSerializer)
    def partial_update(self, request, *args, **kwargs):
        return super().partial_update(request, *args, **kwargs)

    def _filter_request(self, request: request.Request, queryset: QuerySet) -> QuerySet:
        """Apply filters from request query params to queryset."""
        return self._apply_filters(request.GET.dict(), queryset)

    def safely_get_queryset(self, queryset) -> QuerySet:
        from django.db.models import Exists, OuterRef

        from products.feature_flags.backend.models.evaluation_context import FeatureFlagEvaluationContext

        # Always prefetch experiment_set since it's used in both list and retrieve
        queryset = queryset.prefetch_related(
            Prefetch(
                "experiment_set",
                queryset=Experiment.objects.filter(deleted=False),
                to_attr="_active_experiments",
            )
        )

        # Prefetch evaluation contexts to avoid N+1 queries when serializing.
        queryset = queryset.prefetch_related(
            Prefetch(
                "flag_evaluation_contexts",
                queryset=FeatureFlagEvaluationContext.objects.select_related("evaluation_context"),
            )
        )

        # Annotate with replay settings usage to avoid N+1 queries
        # This checks if any team in the same project uses this flag for session recording
        # Extract the 'id' key from the JSONB field and cast to integer for safe comparison
        from django.db.models import IntegerField
        from django.db.models.functions import Cast

        queryset = queryset.annotate(
            is_used_in_replay_settings_annotation=Exists(
                Team.objects.filter(
                    project_id=OuterRef("team__project_id"),
                )
                .annotate(json_flag_id=Cast("session_recording_linked_flag__id", IntegerField()))
                .filter(json_flag_id=OuterRef("id"))
            )
        )

        if self.action == "list":
            queryset = (
                queryset.filter(deleted=False)
                .prefetch_related("features")
                .prefetch_related("analytics_dashboards")
                .prefetch_related(
                    Prefetch(
                        "surveys_linked_flag",
                        queryset=Survey.objects.select_related(
                            "linked_flag",
                            "targeting_flag",
                            "internal_targeting_flag",
                        ).prefetch_related("actions"),
                    )
                )
                .prefetch_related(
                    Prefetch(
                        "team__cohort_set",
                        queryset=Cohort.objects.filter(deleted=False).only("id", "name"),
                        to_attr="available_cohorts",
                    )
                )
            )

            survey_flag_ids = Survey.get_internal_flag_ids(project_id=self.project_id)
            product_tour_internal_targeting_flags = ProductTour.all_objects.filter(
                team__project_id=self.project_id, internal_targeting_flag__isnull=False
            ).values_list("internal_targeting_flag_id", flat=True)
            queryset = queryset.exclude(Q(id__in=survey_flag_ids)).exclude(
                Q(id__in=product_tour_internal_targeting_flags)
            )

            queryset = exclude_archived_unless_requested(queryset, requested="archived" in self.request.GET)

            # add additional filters provided by the client
            queryset = self._filter_request(self.request, queryset)

        order = self.request.GET.get("order", None)
        if order:
            queryset = queryset.order_by(order)
        else:
            queryset = queryset.order_by("-created_at")

        return queryset.select_related("created_by", "last_modified_by")

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "active",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=["true", "false", "STALE"],
            ),
            OpenApiParameter(
                "created_by_id",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    "Filter by the user(s) who created the feature flag. Accepts a single user ID, "
                    "or a JSON-encoded / comma-separated list of user IDs to match any of them."
                ),
            ),
            OpenApiParameter(
                "search",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="Search by feature flag key or name. Case insensitive.",
            ),
            OpenApiParameter(
                "type",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=["boolean", "multivariant", "experiment", "remote_config"],
            ),
            OpenApiParameter(
                "evaluation_runtime",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=[choice[0] for choice in FeatureFlag.EVALUATION_RUNTIME_CHOICES],
                description="Filter feature flags by their evaluation runtime.",
            ),
            OpenApiParameter(
                "excluded_properties",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="JSON-encoded list of feature flag keys to exclude from the results.",
            ),
            OpenApiParameter(
                "tags",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="JSON-encoded list of tag names to filter feature flags by.",
            ),
            OpenApiParameter(
                "excluded_tags",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="JSON-encoded list of tag names to exclude. Flags carrying any of these tags are filtered out.",
            ),
            OpenApiParameter(
                "archived",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=["true", "false"],
                description="Filter by archived state. When omitted, archived flags are excluded.",
            ),
            OpenApiParameter(
                "has_evaluation_contexts",
                OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                enum=["true", "false"],
                description="Filter feature flags by presence of evaluation contexts. 'true' returns only flags with at least one evaluation context, 'false' returns only flags without.",
            ),
        ]
    )
    def list(self, request, *args, **kwargs):
        if isinstance(request.successful_authenticator, PersonalAPIKeyAuthentication):
            # Add request for analytics only if request coming with personal API key authentication
            increment_request_count(self.team.pk, 1, FlagRequestType.LOCAL_EVALUATION)

        response = super().list(request, *args, **kwargs)
        feature_flags_data = response.data.get("results", [])

        is_evaluation_contexts_enabled = EvaluationTagsChecker.is_enabled(request)

        for feature_flag in feature_flags_data:
            if not is_evaluation_contexts_enabled:
                feature_flag["evaluation_contexts"] = []

            # If flag is using encrypted payloads, replace them with redacted string or unencrypted value
            if feature_flag.get("has_encrypted_payloads", False):
                feature_flag["filters"]["payloads"] = get_decrypted_flag_payloads_protected(
                    request, feature_flag["filters"]["payloads"]
                )

        return response

    def retrieve(self, request, *args, **kwargs):
        response = super().retrieve(request, *args, **kwargs)
        feature_flag_data = response.data

        is_evaluation_contexts_enabled = EvaluationTagsChecker.is_enabled(request)

        if not is_evaluation_contexts_enabled:
            feature_flag_data["evaluation_contexts"] = []

        # If flag is using encrypted payloads, replace them with redacted string or unencrypted value
        if feature_flag_data.get("has_encrypted_payloads", False):
            feature_flag_data["filters"]["payloads"] = get_decrypted_flag_payloads_protected(
                request, feature_flag_data["filters"]["payloads"]
            )

        return response

    @action(methods=["POST"], detail=True)
    def dashboard(self, request: request.Request, **kwargs):
        feature_flag: FeatureFlag = self.get_object()
        try:
            usage_dashboard = _create_usage_dashboard(feature_flag, request.user)

            if feature_flag.has_enriched_analytics and not feature_flag.usage_dashboard_has_enriched_insights:
                add_enriched_insights_to_feature_flag_dashboard(feature_flag, usage_dashboard)

        except Exception as e:
            capture_exception(e)
            return Response(
                {
                    "success": False,
                    "error": f"Unable to generate usage dashboard",
                },
                status=400,
            )

        return Response({"success": True}, status=200)

    @action(methods=["POST"], detail=True)
    def enrich_usage_dashboard(self, request: request.Request, **kwargs):
        feature_flag: FeatureFlag = self.get_object()
        usage_dashboard = feature_flag.usage_dashboard

        if not usage_dashboard:
            return Response(
                {
                    "success": False,
                    "error": f"Usage dashboard not found",
                },
                status=400,
            )

        if feature_flag.usage_dashboard_has_enriched_insights:
            return Response(
                {
                    "success": False,
                    "error": f"Usage dashboard already has enriched data",
                },
                status=400,
            )

        if not feature_flag.has_enriched_analytics:
            return Response(
                {
                    "success": False,
                    "error": f"No enriched analytics available for this feature flag",
                },
                status=400,
            )
        try:
            add_enriched_insights_to_feature_flag_dashboard(feature_flag, usage_dashboard)
        except Exception as e:
            capture_exception(e)
            return Response(
                {
                    "success": False,
                    "error": f"Unable to enrich usage dashboard",
                },
                status=400,
            )

        return Response({"success": True}, status=200)

    @extend_schema(
        responses={200: DependentFlagSerializer(many=True)},
    )
    @action(methods=["GET"], detail=True, required_scopes=["feature_flag:read"], pagination_class=None)
    def dependent_flags(self, request: request.Request, **kwargs):
        """Get other active flags that depend on this flag."""
        feature_flag: FeatureFlag = self.get_object()
        dependent_flags = find_dependent_flags(feature_flag)
        return Response(
            [
                {
                    "id": flag.id,
                    "key": flag.key,
                    "name": flag.name or flag.key,
                }
                for flag in dependent_flags
            ],
            status=200,
        )

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "version_number",
                OpenApiTypes.INT,
                location=OpenApiParameter.PATH,
                required=True,
                description="The version number to reconstruct.",
            ),
        ],
        responses={
            200: FeatureFlagVersionResponseSerializer,
            400: OpenApiResponse(description="Version history is not available for remote configuration flags."),
            404: OpenApiResponse(description="Version not found."),
            422: OpenApiResponse(description="Activity log incomplete; cannot reconstruct this version."),
        },
    )
    @action(
        methods=["GET"],
        detail=True,
        url_path=r"versions/(?P<version_number>[0-9]+)",
        required_scopes=["feature_flag:read"],
    )
    def versions(self, request: request.Request, version_number: str, **kwargs) -> Response:
        feature_flag: FeatureFlag = self.get_object()

        if feature_flag.is_remote_configuration or feature_flag.has_encrypted_payloads:
            return Response(
                {"detail": "Version history is not available for remote configuration or encrypted flags."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        target_version = int(version_number)

        try:
            result = reconstruct_flag_at_version(
                flag=feature_flag,
                target_version=target_version,
                team_id=self.team_id,
            )
        except VersionNotFound as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_404_NOT_FOUND,
            )
        except VersionHistoryIncomplete as e:
            return Response(
                {"detail": str(e)},
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )

        return Response(FeatureFlagVersionResponseSerializer(instance=result).data)

    @validated_request(
        query_serializer=MyFlagsQuerySerializer,
        responses={
            200: OpenApiResponse(response=MyFlagsResponseListSerializer),
        },
    )
    @action(methods=["GET"], detail=False, pagination_class=None, required_scopes=["feature_flag:read"])
    def my_flags(self, request: request.Request, **kwargs):
        if not request.user.is_authenticated:  # for mypy
            raise exceptions.NotAuthenticated()

        # Exclude internal flags (survey targeting and product tour internal flags)
        # These are auto-generated and not user-editable, same as the main flags list
        survey_flag_ids = Survey.get_internal_flag_ids(project_id=self.project_id)
        product_tour_internal_targeting_flags = ProductTour.all_objects.filter(
            team__project_id=self.project_id, internal_targeting_flag__isnull=False
        ).values_list("internal_targeting_flag_id", flat=True)

        feature_flags = list(
            FeatureFlag.objects.filter(team__project_id=self.project_id)
            .exclude(Q(id__in=survey_flag_ids))
            .exclude(Q(id__in=product_tour_internal_targeting_flags))
            .annotate(
                evaluation_tag_names_agg=ArrayAgg(
                    "flag_evaluation_contexts__evaluation_context__name",
                    filter=Q(flag_evaluation_contexts__isnull=False),
                    distinct=True,
                ),
            )
            .order_by("-created_at")
        )

        if not feature_flags:
            return Response([])

        # Transfer the bulk-aggregated context names onto _evaluation_tag_names so the
        # serializer answers without a per-flag query (see get_evaluation_contexts).
        for flag in feature_flags:
            flag._evaluation_tag_names = getattr(flag, "evaluation_tag_names_agg", None)

        groups = request.validated_query_data.get("groups", {})
        # Ensure groups is always a dict, not a string
        if isinstance(groups, str):
            groups = json.loads(groups) if groups else {}

        distinct_id = request.user.distinct_id
        if not distinct_id:
            raise exceptions.ValidationError("User distinct_id is required")

        # Authenticated Django UI handler (the flags list in the app), not customer SDK
        # traffic. Pass the internal token so the call bypasses per-team billing.
        result = get_flags_from_service(
            token=self.team.api_token,
            distinct_id=distinct_id,
            groups=groups,
            internal_request_token=settings.INTERNAL_REQUEST_TOKEN,
        )

        # Result from Rust service is always a dictionary. Parse it to get the flags data.
        flags_data = result.get("flags", {})
        matches = {
            flag_key: (
                flag_data.get("variant") if flag_data.get("variant") is not None else flag_data.get("enabled", False)
            )
            for flag_key, flag_data in flags_data.items()
        }

        all_serialized_flags = MinimalFeatureFlagSerializer(
            feature_flags, many=True, context=self.get_serializer_context()
        ).data
        return Response(
            {
                "feature_flag": feature_flag,
                "value": matches.get(feature_flag["key"], False),
            }
            for feature_flag in all_serialized_flags
        )

    @extend_schema(
        operation_id="feature_flags_bulk_keys_retrieve",
        request=BulkKeysRequestSerializer,
        responses={
            200: OpenApiResponse(response=BulkKeysResponseSerializer),
            400: OpenApiResponse(response=ErrorResponseSerializer, description="Invalid flag IDs provided."),
        },
    )
    @action(methods=["POST"], detail=False, required_scopes=["feature_flag:read"])
    def bulk_keys(self, request: request.Request, **kwargs):
        """
        Get feature flag keys by IDs.
        Accepts a list of feature flag IDs and returns a mapping of ID to key.
        """
        flag_ids = request.data.get("ids", [])

        if not flag_ids:
            return Response({"keys": {}})

        # Convert to integers and track invalid IDs
        validated_ids = []
        invalid_ids = []
        for flag_id in flag_ids:
            if isinstance(flag_id, int):
                validated_ids.append(flag_id)
            elif isinstance(flag_id, str) and flag_id.isdigit():
                validated_ids.append(int(flag_id))
            else:
                invalid_ids.append(flag_id)

        # If no valid IDs were provided, return error
        if not validated_ids and flag_ids:
            return Response(
                {"error": "Invalid flag IDs provided"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not validated_ids:
            return Response({"keys": {}})

        flag_ids = validated_ids

        # Prepare response data
        response_data: dict[str, Any] = {"keys": {}}

        # Add warning if there were invalid IDs
        if invalid_ids:
            response_data["warning"] = f"Invalid flag IDs ignored: {invalid_ids}"

        # Filter through per-object ACLs so a caller can't probe IDs to learn keys of flags they've been denied.
        # The queryset is project-scoped (team__project_id) while the AC filter is team-scoped — equivalent today
        # since team_id == project_id, asymmetric only under the deprecated multi-team-per-project ("environments")
        # path being removed. Mirrors the list endpoint's ACL filtering.
        queryset = FeatureFlag.objects.filter(id__in=flag_ids, team__project_id=self.project_id)
        queryset = self.user_access_control.filter_queryset_by_access_level(queryset, include_all_if_admin=True)
        flags = queryset.values_list("id", "key")

        # Create mapping of ID to key
        keys_mapping = {str(flag_id): key for flag_id, key in flags}
        response_data["keys"] = keys_mapping

        return Response(response_data)

    @action(methods=["GET"], detail=False, required_scopes=["feature_flag:read"])
    def matching_ids(self, request: request.Request, **kwargs):
        """
        Get IDs of all feature flags matching the current filters.
        Uses the same filtering logic as the list endpoint.
        Returns only IDs that the user has permission to edit.
        """
        from posthog.rbac.user_access_control import access_level_satisfied_for_resource

        # Build queryset with same filtering as list endpoint
        queryset = self.queryset.filter(team__project_id=self.project_id, deleted=False)

        # Exclude internal flags (same as list endpoint)
        survey_flag_ids = Survey.get_internal_flag_ids(project_id=self.project_id)
        product_tour_internal_targeting_flags = ProductTour.all_objects.filter(
            team__project_id=self.project_id, internal_targeting_flag__isnull=False
        ).values_list("internal_targeting_flag_id", flat=True)
        queryset = queryset.exclude(Q(id__in=survey_flag_ids)).exclude(Q(id__in=product_tour_internal_targeting_flags))

        queryset = exclude_archived_unless_requested(queryset, requested="archived" in self.request.GET)

        # Apply client filters (same filtering as list endpoint)
        queryset = self._filter_request(self.request, queryset)

        # If no access control, fetch IDs directly without loading full rows
        if not self.user_access_control:
            editable_ids = list(queryset.values_list("id", flat=True))
        else:
            # Load only the id field to minimize data transfer
            flags = list(queryset.only("id"))

            # Preload access controls to avoid N+1 queries
            self.user_access_control.preload_object_access_controls(cast(list, flags))

            # Filter to only flags the user can edit (same logic as serializer's get_can_edit)
            editable_ids = []
            for flag in flags:
                user_access_level = self.user_access_control.get_user_access_level(flag)
                if user_access_level and access_level_satisfied_for_resource(
                    "feature_flag", user_access_level, "editor"
                ):
                    editable_ids.append(flag.id)

        return Response(
            {
                "ids": editable_ids,
                "total": len(editable_ids),
            }
        )

    @extend_schema(
        request=BulkDeleteRequestSerializer,
        responses={
            200: OpenApiResponse(response=BulkDeleteResponseSerializer),
            400: OpenApiResponse(
                response=ErrorResponseSerializer,
                description="Invalid input — e.g., both filters and ids supplied, neither supplied, or unknown filter keys.",
            ),
        },
    )
    @action(methods=["POST"], detail=False, required_scopes=["feature_flag:write"])
    def bulk_delete(self, request: request.Request, **kwargs):
        """
        Bulk delete feature flags by filter criteria or explicit IDs.

        Accepts either:
        - {"filters": {...}} - Same filter params as list endpoint (search, active, type, etc.)
        - {"ids": [...]} - Explicit list of flag IDs (no limit)

        Returns same format as bulk_delete for UI compatibility.

        Uses bulk operations for efficiency: database updates are batched and cache
        invalidation happens once at the end rather than per-flag.
        """
        from django.utils import timezone

        from posthog.models.activity_logging.activity_log import LogActivityEntry, bulk_log_activity
        from posthog.rbac.user_access_control import access_level_satisfied_for_resource
        from posthog.tasks.remote_config import update_team_remote_config

        from products.feature_flags.backend.models.feature_flag import set_feature_flags_for_team_in_cache
        from products.feature_flags.backend.tasks import update_team_flags_cache, update_team_service_flags_cache

        filters = request.data.get("filters", {})
        explicit_ids = request.data.get("ids", [])

        if filters and explicit_ids:
            return Response(
                {"error": "Provide either filters or ids, not both"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not filters and not explicit_ids:
            return Response(
                {"error": "Must provide either filters or ids"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate filter keys against allowlist to prevent accidental mass deletion
        if filters:
            valid_filter_keys = set(BulkDeleteFiltersSerializer().fields.keys())
            unknown_keys = set(filters.keys()) - valid_filter_keys
            if unknown_keys:
                return Response(
                    {"error": f"Unknown filter keys: {', '.join(sorted(unknown_keys))}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Build base queryset
        queryset = self.queryset.filter(team__project_id=self.project_id, deleted=False)

        # Exclude internal flags (same as list/matching_ids endpoints)
        survey_flag_ids = Survey.get_internal_flag_ids(project_id=self.project_id)
        product_tour_internal_targeting_flags = ProductTour.all_objects.filter(
            team__project_id=self.project_id, internal_targeting_flag__isnull=False
        ).values_list("internal_targeting_flag_id", flat=True)
        queryset = queryset.exclude(Q(id__in=survey_flag_ids)).exclude(Q(id__in=product_tour_internal_targeting_flags))

        if filters:
            # Match the list endpoint's semantics: archived flags are not deleted by
            # filter-based bulk deletion unless explicitly requested.
            queryset = exclude_archived_unless_requested(queryset, requested="archived" in filters)
            # Apply filters from request body (same logic as _filter_request but from dict)
            queryset = self._apply_filters(filters, queryset)
        else:
            # Validate and convert IDs
            validated_ids = []
            invalid_ids = []
            for flag_id in explicit_ids:
                if isinstance(flag_id, int):
                    validated_ids.append(flag_id)
                elif isinstance(flag_id, str) and flag_id.isdigit():
                    validated_ids.append(int(flag_id))
                else:
                    invalid_ids.append(flag_id)

            if not validated_ids and not invalid_ids:
                return Response(
                    {"error": "No flag IDs provided"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            queryset = queryset.filter(id__in=validated_ids)

        # Apply access control - filter to only editable flags
        if self.user_access_control:
            # Fetch just IDs for access control check (lightweight query)
            flags_for_access_check = list(queryset.only("id"))
            self.user_access_control.preload_object_access_controls(cast(list, flags_for_access_check))

            editable_ids = []
            for flag in flags_for_access_check:
                user_access_level = self.user_access_control.get_user_access_level(flag)
                if user_access_level and access_level_satisfied_for_resource(
                    "feature_flag", user_access_level, "editor"
                ):
                    editable_ids.append(flag.id)

            # Filter the existing queryset to only editable flags (preserves all exclusions)
            queryset = queryset.filter(id__in=editable_ids)

        # Prefetch related data for validation (only for flags we'll actually process)
        queryset = queryset.prefetch_related("features", "experiment_set")
        flags_list = list(queryset)

        # Batch query for dependent flags
        dependent_flags_map = find_dependent_flags_batch(flags_list)

        deleted = []
        errors = []

        # Add errors for invalid or missing IDs (only for ID-based deletion)
        if explicit_ids:
            found_ids = {flag.id for flag in flags_list}
            for flag_id in explicit_ids:
                if not isinstance(flag_id, int) and not (isinstance(flag_id, str) and flag_id.isdigit()):
                    errors.append({"id": flag_id, "reason": "Invalid flag ID format"})
                else:
                    # Convert to int for comparison if it's a string
                    numeric_id = int(flag_id) if isinstance(flag_id, str) else flag_id
                    if numeric_id not in found_ids:
                        errors.append({"id": numeric_id, "reason": "Flag not found"})

        # Separate flags into those that pass validation vs those that don't
        # Also track which need key renames (have deleted experiments)
        flags_to_delete_normal: list[FeatureFlag] = []
        flags_to_delete_with_rename: list[FeatureFlag] = []
        activity_log_entries: list[LogActivityEntry] = []

        current_user = request.user if request.user.is_authenticated else None
        was_impersonated = is_impersonated(request)

        for flag in flags_list:
            flag_id = flag.id

            # Check for linked early access features
            if len(list(flag.features.all())) > 0:
                errors.append(
                    {
                        "id": flag_id,
                        "key": flag.key,
                        "reason": "Cannot delete a feature flag that is in use with early access features",
                    }
                )
                continue

            # Check for linked running experiments. Draft/stopped/completed experiments
            # may keep the flag so their historical results are preserved; only a
            # currently running experiment blocks deletion.
            running_experiments = [exp for exp in flag.experiment_set.all() if not exp.deleted and exp.is_running]
            if running_experiments:
                experiment_names = ", ".join(f'"{exp.name}" (ID: {exp.id})' for exp in running_experiments)
                errors.append(
                    {
                        "id": flag_id,
                        "key": flag.key,
                        "reason": f"Cannot delete a feature flag linked to running experiment(s): {experiment_names}",
                    }
                )
                continue

            # Check for dependent flags
            dependent_flags = dependent_flags_map.get(flag_id, [])
            if dependent_flags:
                dependent_flag_names = [f"{f.key} (ID: {f.id})" for f in dependent_flags[:3]]
                if len(dependent_flags) > 3:
                    dependent_flag_names.append(f"and {len(dependent_flags) - 3} more")
                errors.append(
                    {
                        "id": flag_id,
                        "key": flag.key,
                        "reason": f"Cannot delete because other flags depend on it: {', '.join(dependent_flag_names)}",
                    }
                )
                continue

            # Flag passes validation - capture rollout state before deletion
            checker = FeatureFlagStatusChecker(feature_flag=flag)
            rollout_info = _get_flag_rollout_info(flag, checker)
            old_key = flag.key

            # Rename the key if the flag is linked to any experiment, to free it up.
            # Use the prefetched experiment_set cache (see queryset above) rather than
            # .exists(), which would issue a fresh query per flag.
            has_linked_experiments = bool(flag.experiment_set.all())
            if has_linked_experiments:
                flags_to_delete_with_rename.append(flag)
            else:
                flags_to_delete_normal.append(flag)

            # Prepare activity log entry
            activity_log_entries.append(
                LogActivityEntry(
                    organization_id=flag.team.organization_id,
                    team_id=flag.team_id,
                    user=current_user,
                    was_impersonated=was_impersonated,
                    item_id=flag.id,
                    scope="FeatureFlag",
                    activity="deleted",
                    detail=Detail(changes=[], name=old_key),
                )
            )

            deleted.append({"id": flag_id, "key": old_key, **rollout_info})

        # Perform bulk database updates
        # Using queryset.update() instead of individual saves means Django signals don't fire.
        # The signals (refresh_flag_cache_on_updates, feature_flag_changed_flags_cache, etc.)
        # all do cache invalidation, which we handle manually below - once for all flags
        # instead of once per flag.
        now_timestamp = timezone.now()

        if flags_to_delete_normal or flags_to_delete_with_rename:
            sample_flag = flags_to_delete_normal[0] if flags_to_delete_normal else flags_to_delete_with_rename[0]
            team_id = sample_flag.team_id
            project_id = sample_flag.team.project_id

            with transaction.atomic():
                if flags_to_delete_normal:
                    normal_ids = [f.id for f in flags_to_delete_normal]
                    FeatureFlag.objects.filter(id__in=normal_ids, team_id=team_id).update(
                        deleted=True,
                        last_modified_by=current_user,
                        updated_at=now_timestamp,
                    )

                # Flags with soft-deleted experiments need key rename - use bulk_update
                # to update all flags in a single query with per-flag key values
                if flags_to_delete_with_rename:
                    for flag in flags_to_delete_with_rename:
                        flag.deleted = True
                        flag.last_modified_by = current_user
                        flag.updated_at = now_timestamp
                        flag.key = flag.tombstoned_key()
                    FeatureFlag.objects.bulk_update(
                        flags_to_delete_with_rename,
                        ["deleted", "last_modified_by", "updated_at", "key"],
                    )

                if activity_log_entries:
                    bulk_log_activity(activity_log_entries)

                # Cache invalidation - same work the signals would do, but once instead of N times
                def invalidate_caches():
                    set_feature_flags_for_team_in_cache(project_id)
                    update_team_service_flags_cache.delay(team_id)
                    update_team_flags_cache.delay(team_id)
                    update_team_remote_config.delay(team_id)

                transaction.on_commit(invalidate_caches)

        return Response(
            {
                "deleted": deleted,
                "errors": errors,
            }
        )

    def _apply_filters(self, filters: dict, queryset: QuerySet) -> QuerySet:
        """
        Apply filters to queryset.

        Handles both string values (from URL query params) and native Python types (from JSON body).
        Used by both _filter_request and bulk_delete endpoints.
        """

        for key, value in filters.items():
            if key == "active":
                queryset = filter_flags_by_active_param(queryset, value)
            elif key == "archived":
                is_archived = value if isinstance(value, bool) else str(value).lower() == "true"
                queryset = queryset.filter(archived=is_archived)
            elif key == "created_by_id":
                user_ids = parse_created_by_ids(value)
                if user_ids:
                    queryset = queryset.filter(created_by_id__in=user_ids)
            elif key == "search":
                if isinstance(value, str):
                    value = value.strip()
                    if value:
                        # Limit search term length for performance safety
                        if len(value) > 200:
                            raise serializers.ValidationError("Search term cannot exceed 200 characters")

                        # Escape regex metacharacters first, then replace spaces with word boundary pattern
                        escaped_value = re.escape(value)
                        regex_pattern = escaped_value.replace(r"\ ", r"[\s\-_]*")
                        queryset = queryset.filter(
                            Q(key__iregex=regex_pattern)
                            | Q(name__iregex=regex_pattern)
                            | Q(experiment__name__iregex=regex_pattern, experiment__deleted=False)
                        ).distinct()
            elif key == "type":
                if value == "boolean":
                    queryset = queryset.filter(
                        Q(filters__multivariate__variants__isnull=True) | Q(filters__multivariate__variants=[])
                    )
                elif value == "multivariant":
                    queryset = queryset.filter(
                        Q(filters__multivariate__variants__isnull=False) & ~Q(filters__multivariate__variants=[])
                    )
                elif value == "experiment":
                    queryset = queryset.filter(~Q(experiment__isnull=True))
                elif value == "remote_config":
                    queryset = queryset.filter(is_remote_configuration=True)
            elif key == "evaluation_runtime":
                queryset = queryset.filter(evaluation_runtime=value)
            elif key == "excluded_properties":
                try:
                    # Handle both list and JSON string
                    excluded_keys = (
                        value if isinstance(value, list) else json.loads(value) if isinstance(value, str) else []
                    )
                    if excluded_keys:
                        queryset = queryset.exclude(key__in=excluded_keys)
                except (json.JSONDecodeError, TypeError):
                    pass
            elif key == "tags":
                try:
                    # Handle both list and JSON string
                    tags = value if isinstance(value, list) else json.loads(value) if isinstance(value, str) else []
                    if tags:
                        queryset = queryset.filter(tagged_items__tag__name__in=tags).distinct()
                except (json.JSONDecodeError, TypeError):
                    pass
            elif key == "excluded_tags":
                try:
                    # Handle both list and JSON string
                    excluded_tags = (
                        value if isinstance(value, list) else json.loads(value) if isinstance(value, str) else []
                    )
                    if excluded_tags:
                        # Exclude by ID subquery so a flag carrying both an excluded and a
                        # non-excluded tag is still reliably filtered out.
                        flags_with_excluded_tags = FeatureFlag.objects.filter(
                            team__project_id=self.project_id, tagged_items__tag__name__in=excluded_tags
                        ).values("pk")
                        queryset = queryset.exclude(pk__in=flags_with_excluded_tags)
                except (json.JSONDecodeError, TypeError):
                    pass
            elif key == "has_evaluation_contexts":
                # Handle both string and boolean
                if isinstance(value, bool):
                    filter_value = value
                else:
                    filter_value = str(value).lower() in ("true", "1", "yes")

                queryset = queryset.annotate(eval_tag_count=Count("flag_evaluation_contexts"))
                if filter_value:
                    queryset = queryset.filter(eval_tag_count__gt=0)
                else:
                    queryset = queryset.filter(eval_tag_count=0)

        return queryset

    @validated_request(
        query_serializer=EvaluationReasonsQuerySerializer,
        responses={
            200: OpenApiResponse(response=EvaluationReasonsResponseSerializer()),
        },
        examples=[
            OpenApiExample(
                "Evaluation Reasons Response",
                description="Example response showing evaluation results for multiple feature flags",
                response_only=True,
                value={
                    "new-signup-flow": {
                        "value": True,
                        "evaluation": {
                            "reason": "condition_match",
                            "condition_index": 0,
                        },
                    },
                    "dark-mode": {
                        "value": "variant-a",
                        "evaluation": {
                            "reason": "condition_match",
                            "condition_index": 1,
                        },
                    },
                    "beta-features": {
                        "value": False,
                        "evaluation": {
                            "reason": "no_condition_match",
                            "condition_index": None,
                        },
                    },
                },
            )
        ],
    )
    @action(methods=["GET"], detail=False, required_scopes=["feature_flag:read"])
    def evaluation_reasons(self, request: request.Request, **kwargs):
        distinct_id = request.validated_query_data["distinct_id"]
        groups = request.validated_query_data.get("groups", {})
        # Ensure groups is always a dict, not a string
        if isinstance(groups, str):
            groups = json.loads(groups) if groups else {}

        flag_keys = request.validated_query_data.get("flag_keys") or None

        # PostHog UI debug endpoint, not customer SDK traffic. Pass the internal
        # token so the call bypasses per-team billing.
        result = get_flags_from_service(
            token=self.team.api_token,
            distinct_id=distinct_id,
            groups=groups,
            flag_keys=flag_keys,
            evaluation_runtime="all",
            internal_request_token=settings.INTERNAL_REQUEST_TOKEN,
        )

        # Result from Rust service is always a dictionary with a "flags" key. Parse it to get the flags data.
        flags_data = result.get("flags", {})
        flags_with_evaluation_reasons = {}

        for flag_key, flag_data in flags_data.items():
            value = (
                flag_data.get("variant") if flag_data.get("variant") is not None else flag_data.get("enabled", False)
            )

            reason_data = flag_data.get("reason", {})
            flags_with_evaluation_reasons[flag_key] = {
                "value": value,
                "evaluation": {
                    "reason": reason_data.get("code", "unknown"),
                    "condition_index": reason_data.get("condition_index"),
                },
            }

        disabled_flags_qs = FeatureFlag.objects.filter(team__project_id=self.project_id, active=False)
        if flag_keys:
            disabled_flags_qs = disabled_flags_qs.filter(key__in=flag_keys)
        disabled_flags = disabled_flags_qs.values_list("key", flat=True)

        for flag_key in disabled_flags:
            flags_with_evaluation_reasons[flag_key] = {
                "value": False,
                "evaluation": {
                    "reason": "disabled",
                    "condition_index": None,
                },
            }

        return Response(flags_with_evaluation_reasons)

    @extend_schema(
        request=UserBlastRadiusRequestSerializer,
        responses={200: UserBlastRadiusResponseSerializer},
    )
    @action(methods=["POST"], detail=False, required_scopes=["feature_flag:read"])
    def user_blast_radius(self, request: request.Request, **kwargs):
        if "condition" not in request.data:
            raise exceptions.ValidationError("Missing condition for which to get blast radius")

        condition = request.data.get("condition") or {}
        group_type_index = request.data.get("group_type_index", None)

        result = get_user_blast_radius(self.team, condition, group_type_index)

        return Response({"affected": result.affected, "total": result.total})

    @action(methods=["POST"], detail=True)
    def create_static_cohort_for_flag(self, request: request.Request, **kwargs):
        feature_flag = self.get_object()
        feature_flag_key = feature_flag.key
        cohort_serializer = CohortSerializer(
            data={
                "is_static": True,
                "key": feature_flag_key,
                "name": f"Users with feature flag {feature_flag_key} enabled at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                "is_calculating": True,
            },
            context={
                "request": request,
                "team": self.team,
                "team_id": self.team_id,
                "from_feature_flag_key": feature_flag_key,
            },
        )

        cohort_serializer.is_valid(raise_exception=True)
        cohort_serializer.save()
        return Response({"cohort": cohort_serializer.data}, status=201)

    @extend_schema(operation_id="feature_flags_all_activity_retrieve")
    @validated_request(
        query_serializer=ActivityQuerySerializer,
        responses={
            200: OpenApiResponse(response=ActivityLogPaginatedResponseSerializer),
        },
    )
    @action(
        methods=["GET"],
        url_path="activity",
        detail=False,
        required_scopes=["activity_log:read"],
    )
    def all_activity(self, request: request.Request, **kwargs):
        limit = request.validated_query_data["limit"]
        page = request.validated_query_data["page"]

        activity_page = load_activity(scope="FeatureFlag", team_id=self.team_id, limit=limit, page=page)

        return activity_page_response(activity_page, limit, page, request)

    @extend_schema(
        responses={200: FeatureFlagStatusResponseSerializer},
    )
    @action(methods=["GET"], detail=True, required_scopes=["feature_flag:read"])
    def status(self, request: request.Request, **kwargs):
        feature_flag = self.get_object()

        checker = FeatureFlagStatusChecker(
            feature_flag=feature_flag,
        )
        flag_status, reason = checker.get_status()
        rollout = checker.get_rollout_summary(feature_flag)

        # Route through the declared serializer so it is the single source of truth for the
        # response shape and the dataclass cannot silently drift from the OpenAPI/MCP schema.
        response = FeatureFlagStatusResponseSerializer(
            {"status": flag_status, "reason": reason, "rollout": asdict(rollout)}
        )
        return Response(response.data, status=status.HTTP_200_OK)

    @validated_request(
        request_serializer=FeatureFlagTestEvaluationRequestSerializer,
        responses={
            200: OpenApiResponse(response=FeatureFlagTestEvaluationResponseSerializer),
            400: OpenApiResponse(response=ErrorResponseSerializer, description="Invalid parameters"),
            404: OpenApiResponse(response=ErrorResponseSerializer, description="Person not found"),
            500: OpenApiResponse(response=ErrorResponseSerializer, description="Server error"),
            502: OpenApiResponse(response=ErrorResponseSerializer, description="Flag evaluation service error"),
        },
    )
    @action(
        methods=["POST"],
        detail=True,
        required_scopes=["feature_flag:read"],
        throttle_classes=[ClickHouseBurstRateThrottle, ClickHouseSustainedRateThrottle],
    )
    def test_evaluation(self, request: request.Request, **kwargs):
        """
        Test feature flag evaluation against a specific user at an optional point in time.

        This endpoint allows testing how a feature flag would evaluate for a specific user,
        optionally at a historical timestamp. When a timestamp is provided, both the flag
        conditions and person properties are evaluated as they existed at that time.
        """
        feature_flag = self.get_object()

        # Extract validated data - prioritize person_id over distinct_id
        distinct_id = request.validated_data.get("distinct_id")
        person_id = request.validated_data.get("person_id")
        timestamp = request.validated_data.get("timestamp")
        groups = request.validated_data.get("groups") or {}

        # Resolve person and distinct_ids
        try:
            person, distinct_ids = get_person_and_distinct_ids_for_identifier(
                team_id=self.team_id, distinct_id=distinct_id, person_id=person_id
            )
        except ValueError as e:
            capture_exception(e)
            return Response({"error": "Invalid parameters"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            capture_exception(e)
            return Response({"error": "Failed to resolve person"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        if not person or not distinct_ids:
            identifier_type = "distinct_id" if distinct_id else "person_id"
            identifier_value = distinct_id or person_id
            return Response(
                {"detail": f"Person not found for {identifier_type}: {identifier_value}"},
                status=status.HTTP_404_NOT_FOUND,
            )

        # Prefer the caller-provided distinct_id for evaluation when it resolves to this person,
        # since rollout/variant assignment can depend on the exact distinct_id used.
        # If person_id was provided, pick the lexicographically smallest distinct_id so the
        # choice is stable across calls — proto_person_to_model / the ORM don't guarantee order.
        evaluation_distinct_id = distinct_id if distinct_id and distinct_id in distinct_ids else sorted(distinct_ids)[0]
        person_properties: dict[str, Any] = {}

        # Build person properties at timestamp if provided
        if timestamp:
            try:
                # Tag the ClickHouse call so query_log attribution stays correct.
                tag_queries(product=Product.FEATURE_FLAGS, feature=Feature.QUERY, team_id=self.team_id)
                lower_bound = timestamp - timedelta(days=730)
                if feature_flag.created_at:
                    lower_bound = min(max(lower_bound, feature_flag.created_at), timestamp)
                person_properties = build_person_properties_at_time(
                    team_id=self.team_id,
                    timestamp=timestamp,
                    distinct_ids=distinct_ids,
                    include_set_once=True,
                    lower_bound=lower_bound,
                )
            except ValueError as e:
                # Our own validation (invalid timestamp shape, naive datetime, etc.) —
                # Validation failures should be logged server-side, but return a generic
                # message to avoid exposing internal exception details to API callers.
                logger.warning("Invalid timestamp input for flag %s: %s", feature_flag.key, e)
                return Response(
                    {"error": "Invalid timestamp format."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            except Exception:
                # ClickHouse / infra failures keep the generic 500 but log the real cause.
                logger.exception("Failed to build person properties at timestamp for flag %s", feature_flag.key)
                return Response(
                    {"error": "Failed to build person properties at specified timestamp."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
        else:
            # Use current person properties
            person_properties = person.properties or {}

        # If timestamp is provided, reconstruct the flag at that point in time.
        # ``evaluation_filters`` is what we hand to _filter_person_properties_for_flag
        # and what the Rust override payload's "filters" entry comes from.
        evaluation_filters: dict[str, Any] = feature_flag.filters or {}
        reconstructed_flag_data: Optional[dict[str, Any]] = None
        if timestamp:
            try:
                # Reconstruct the flag at the timestamp using the efficient single-pass method
                reconstructed_flag_data = reconstruct_flag_at_timestamp(
                    flag=feature_flag,
                    timestamp=timestamp,
                    team_id=self.team_id,
                )
                evaluation_filters = reconstructed_flag_data.get("filters") or {}

            except VersionNotFound:
                return Response(
                    {"error": f"Feature flag '{feature_flag.key}' did not exist at the specified timestamp."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            except VersionHistoryIncomplete:
                return Response(
                    {"error": "Could not reconstruct flag at timestamp due to incomplete history."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            except ValueError as e:
                # e.g. "timestamp must be timezone-aware" from version_history.
                logger.warning("Invalid timestamp for flag reconstruction (flag %s): %s", feature_flag.key, e)
                return Response(
                    {"error": "Invalid timestamp."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            except Exception:
                logger.exception("Failed to reconstruct flag at timestamp for flag %s", feature_flag.key)
                return Response(
                    {"error": "Failed to reconstruct flag at specified timestamp."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        # Evaluate the flag
        try:
            # Get team API token for Rust service
            team_token = self.team.api_token

            # If we reconstructed a historical version, ship the reconstructed
            # field set as the override payload. Building straight from
            # reconstructed_flag_data avoids round-tripping through an in-memory
            # FeatureFlag(...), which would silently substitute model defaults
            # for any field we forgot to copy (bucketing_identifier,
            # evaluation_runtime, ensure_experience_continuity, evaluation_tags,
            # …) and ship those defaults as the historical value.
            override_definitions = None
            if timestamp and reconstructed_flag_data is not None:
                try:
                    # Use allowlist of fields that Rust expects, avoiding the need to track
                    # what _build_response might inject in the future
                    flag_dict: dict[str, Any] = {
                        k: reconstructed_flag_data[k] for k in RUST_FLAG_FIELDS if k in reconstructed_flag_data
                    }
                    flag_dict.update({"id": feature_flag.id, "key": feature_flag.key, "team_id": feature_flag.team_id})

                    # Stringify datetime fields for JSON serialization.
                    if flag_dict.get("created_at") and hasattr(flag_dict["created_at"], "isoformat"):
                        flag_dict["created_at"] = flag_dict["created_at"].isoformat()

                    override_definitions = {feature_flag.key: flag_dict}
                except Exception as e:
                    logger.exception("Failed to serialize flag for override")
                    capture_exception(e)
                    return Response(
                        {"error": "Failed to prepare historical flag definition for evaluation."},
                        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    )

            internal_token = settings.INTERNAL_REQUEST_TOKEN
            if not internal_token:
                return Response(
                    {"error": "Internal request token not configured"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            rust_response = get_flags_from_service(
                token=team_token,
                distinct_id=evaluation_distinct_id,
                groups=groups,
                detailed_analysis=True,
                person_properties=person_properties,
                only_use_override_person_properties=timestamp is not None,
                flag_keys=[feature_flag.key],
                internal_request_token=internal_token,
                override_flags_definitions=override_definitions,
            )

            # Extract the flag result from the Rust response
            flags = rust_response.get("flags", {})
            flag_result = flags.get(feature_flag.key)

            # Initialize defaults
            condition_index = None
            payload = None
            detailed_conditions: list[dict] = []
            result: bool | str = False

            if flag_result is None:
                result = False
                reason = "flag_not_found"
            else:
                # Extract the detailed flag result data
                if isinstance(flag_result, dict):
                    result = flag_result.get("enabled", False)
                    variant = flag_result.get("variant")
                    reason_data = flag_result.get("reason", {})
                    metadata = flag_result.get("metadata", {})

                    # Extract values from the correct nested structures
                    reason = reason_data.get("code", "unknown") if reason_data else "unknown"
                    condition_index = reason_data.get("condition_index") if reason_data else None
                    payload = metadata.get("payload") if metadata else None
                    # Extract conditions from flag result (only valid path per Rust FlagDetails contract).
                    # When ``timestamp`` is set, missing conditions almost certainly means Rust
                    # rejected the internal token and silently fell back to current-state
                    # evaluation: returning a 200 with current-state values would silently corrupt
                    # the historical contract this endpoint promises, so fail loudly instead.
                    if "conditions" not in flag_result:
                        if timestamp:
                            logger.error(
                                "Historical evaluation returned no conditions; INTERNAL_REQUEST_TOKEN may be misconfigured",
                                extra={
                                    "flag_key": feature_flag.key,
                                    "response_keys": list(flag_result.keys()),
                                },
                            )
                            return Response(
                                {"error": "Historical evaluation unavailable. Check service configuration."},
                                status=status.HTTP_502_BAD_GATEWAY,
                            )
                        logger.warning(
                            "Missing 'conditions' key in flag evaluation response",
                            extra={"flag_key": feature_flag.key, "response_keys": list(flag_result.keys())},
                        )
                    detailed_conditions = flag_result.get("conditions", [])

                    # If there's a variant, use it as the result
                    if variant is not None:
                        result = variant
                else:
                    # /flags endpoint with v=2 always returns dict, these branches should never fire
                    logger.error(
                        "Unexpected flag_result type in test_evaluation",
                        extra={
                            "flag_key": feature_flag.key,
                            "result_type": type(flag_result).__name__,
                            "result_value": str(flag_result)[:100],
                        },
                    )
                    return Response(
                        {"error": "Unexpected response format from flag evaluation service"},
                        status=status.HTTP_502_BAD_GATEWAY,
                    )

            # Only echo back the bucketing distinct_id when the caller already
            # had it (they sent it in the request). On the person_id path we
            # picked one for them out of the person's set, and surfacing it
            # would let a ``feature_flag:read``-only token enumerate distinct
            # IDs for any UUID — which normally requires ``person:read``.
            response_evaluation_distinct_id = (
                evaluation_distinct_id if distinct_id and distinct_id in distinct_ids else None
            )
            response_data = {
                "flag_key": feature_flag.key,
                "result": result,
                "reason": reason,
                "condition_index": condition_index,
                "payload": payload,
                "person_properties": _filter_person_properties_for_flag(
                    evaluation_filters, person_properties, flag_key=feature_flag.key
                ),
                "evaluation_distinct_id": response_evaluation_distinct_id,
                "conditions": detailed_conditions,
            }

            response_serializer = FeatureFlagTestEvaluationResponseSerializer(data=response_data)
            response_serializer.is_valid(raise_exception=True)
            return Response(response_serializer.data)

        except Exception as e:
            logger.exception(
                "Error evaluating flag '%s' for distinct_id='%s' person_id='%s' timestamp='%s': %s",
                feature_flag.key,
                distinct_id,
                person_id,
                timestamp,
                e,
                extra={
                    "flag_key": feature_flag.key,
                    "distinct_id": distinct_id,
                    "person_id": person_id,
                    "timestamp": timestamp,
                    "groups": groups,
                },
            )
            capture_exception(e)
            return Response({"error": "Failed to evaluate flag"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(
        methods=["GET"],
        detail=True,
        required_scopes=["feature_flag:read"],
        authentication_classes=[
            TeamSecretTokenAuthentication,
            ProjectSecretAPIKeyAuthentication,
        ],
        permission_classes=[TeamSecretTokenPermission],
        throttle_classes=[RemoteConfigThrottle, RemoteConfigProjectSecretApiKeyTeamThrottle],
    )
    def remote_config(self, request: request.Request, **kwargs):
        response = self._remote_config_response(request, **kwargs)
        # Temporary (Rust remote_config port, phase 2): shadow-compare against Rust; delete after cutover.
        # Guarded here too so a bug in the throwaway shadow can never break the live endpoint.
        try:
            shadow_compare_remote_config(request, response, project_id=self.project_id, key=kwargs["pk"])
        except Exception:
            logger.exception("remote_config shadow comparison failed")
        return response

    def _remote_config_response(self, request: request.Request, **kwargs) -> Response:
        is_flag_id_provided = kwargs["pk"].isdigit()

        try:
            feature_flag = (
                FeatureFlag.objects.get(pk=kwargs["pk"], team__project_id=self.project_id)
                if is_flag_id_provided
                else FeatureFlag.objects.get(key=kwargs["pk"], team__project_id=self.project_id)
            )
        except FeatureFlag.DoesNotExist:
            return Response(status=status.HTTP_404_NOT_FOUND)

        if not feature_flag.is_remote_configuration:
            return Response(status=status.HTTP_404_NOT_FOUND)

        # Remote config usage is tracked for telemetry only (never billed), and only genuine SDK
        # fetches (legacy team secret token or feature-flag-scoped PSAK, both phs_…) count. Session
        # and personal-key requests are the app's own preview/decrypt feature, not customer usage,
        # and a session-authenticated GET would otherwise let a cross-site request inflate the team's
        # usage numbers.
        should_count = is_service_auth(request)

        if not feature_flag.has_encrypted_payloads:
            payloads = feature_flag.filters.get("payloads", {})
            if should_count:
                increment_request_count(self.team.pk, 1, FlagRequestType.REMOTE_CONFIG)
            return Response(payloads.get("true") or None)

        # Note: This decryption step is protected by the feature_flag:read scope, so we can assume the
        # user has access to the flag. However get_decrypted_flag_payloads_protected will also check the authentication
        # method used to make the request as it is used in non-protected endpoints.
        decrypted_flag_payloads = get_decrypted_flag_payloads_protected(
            request, feature_flag.filters.get("payloads", {})
        )

        # Count after a successful decryption so a decrypt failure (500) is never counted.
        if should_count:
            increment_request_count(self.team.pk, 1, FlagRequestType.REMOTE_CONFIG)

        return Response(decrypted_flag_payloads["true"] or None)

    @validated_request(
        query_serializer=ActivityQuerySerializer,
        responses={
            200: OpenApiResponse(response=ActivityLogPaginatedResponseSerializer),
            404: OpenApiResponse(response=None),
        },
    )
    @action(methods=["GET"], detail=True, required_scopes=["activity_log:read"])
    def activity(self, request: request.Request, **kwargs):
        limit = request.validated_query_data["limit"]
        page = request.validated_query_data["page"]

        item = self.get_object()

        activity_page = load_activity(
            scope="FeatureFlag",
            team_id=self.team_id,
            item_ids=[str(item.id)],
            limit=limit,
            page=page,
        )
        return activity_page_response(activity_page, limit, page, request)


class LegacyFeatureFlagViewSet(FeatureFlagViewSet):
    param_derived_from_user_current_team = "project_id"


class CanEditFeatureFlag(BasePermission):
    """
    Permission class to check if a user can edit a specific feature flag.
    This leverages PostHog's existing access control system for feature flags.
    """

    def has_object_permission(self, request, view, obj):
        from posthog.rbac.user_access_control import UserAccessControl

        # Get the team from the object (feature flag)
        team = obj.team if hasattr(obj, "team") else obj

        # Get user access control for this team
        user_access_control = UserAccessControl(user=request.user, team=team)

        # Check if user has editor or higher access to feature flags for this team
        return user_access_control.check_access_level_for_object(obj, "editor")
