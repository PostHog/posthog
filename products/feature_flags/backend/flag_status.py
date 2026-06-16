from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from django.db.models import Q, QuerySet

import structlog

from posthog.date_util import thirty_days_ago

from .models.feature_flag import FeatureFlag

logger = structlog.get_logger(__name__)

FeatureFlagStatusReason = str


class FeatureFlagStatus(StrEnum):
    ACTIVE = "active"
    STALE = "stale"
    ARCHIVED = "archived"
    DELETED = "deleted"
    UNKNOWN = "unknown"


@dataclass
class FeatureFlagRolloutSummary:
    # Whether the flag is effectively rolled out to everyone, independent of recent evaluation.
    effectively_full_rollout: bool
    # Whether any release condition has property filters (conditionally targeted vs. blanket rollout).
    has_targeting_conditions: bool
    # Highest rollout percentage across release conditions, or None when there are no conditions.
    max_rollout_percentage: int | None
    # Whether the flag serves multiple variants.
    is_multivariate: bool


def exclude_archived_unless_requested(queryset: QuerySet, *, requested: bool) -> QuerySet:
    """Hide archived flags unless the caller explicitly asked for them.

    This is the API's default for the list, `matching_ids`, and filter-based `bulk_delete`
    paths — archived flags stay out of "select all" / bulk-delete sets unless `archived` is
    passed. `requested` is whether the caller provided an `archived` param (the value filter
    itself is applied separately). The frontend `flagMatchesFilters` keeps its own mirror.
    """
    if not requested:
        return queryset.filter(archived=False)
    return queryset


def filter_flags_by_active_param(queryset: QuerySet, value: str | bool) -> QuerySet:
    """
    Filter a FeatureFlag queryset by the `active` param (STALE / true / false).

    Source of truth for both the feature_flags viewset (`_apply_filters`) and Max's
    listing path. Handles string values (from URL query params) and native booleans
    (from JSON bodies). When updating the STALE logic, also update
    `FeatureFlagStatusChecker.get_status` so the filter and the per-flag status agree.
    """
    if value == "STALE":
        # Get stale flags using the best available signal:
        # 1. If last_called_at exists: flag hasn't been called in 30+ days
        # 2. If last_called_at is NULL: flag is 100% rolled out and 30+ days old
        stale_threshold = thirty_days_ago()
        usage_based_stale = Q(last_called_at__lt=stale_threshold, active=True)
        # nosemgrep: python.django.security.audit.query-set-extra.avoid-query-set-extra (static SQL, no user input)
        config_based_queryset = queryset.filter(
            last_called_at__isnull=True,
            active=True,
            created_at__lt=stale_threshold,
        ).extra(
            where=[
                """
                (
                    (
                        EXISTS (
                            SELECT 1 FROM jsonb_array_elements(posthog_featureflag.filters->'groups') AS elem
                            WHERE elem->>'rollout_percentage' = '100'
                            AND (elem->'properties')::text = '[]'::text
                        )
                        AND (posthog_featureflag.filters->>'multivariate' IS NULL
                            OR posthog_featureflag.filters->'multivariate' = '{}'::jsonb
                            OR jsonb_array_length(posthog_featureflag.filters->'multivariate'->'variants') = 0)
                    )
                    OR
                    (
                        EXISTS (
                            SELECT 1 FROM jsonb_array_elements(posthog_featureflag.filters->'multivariate'->'variants') AS variant
                            WHERE variant->>'rollout_percentage' = '100'
                        )
                        AND EXISTS (
                            SELECT 1 FROM jsonb_array_elements(posthog_featureflag.filters->'groups') AS elem
                            WHERE elem->>'rollout_percentage' = '100'
                            AND (elem->'properties')::text = '[]'::text
                        )
                    )
                    OR
                    (
                        EXISTS (
                            SELECT 1 FROM jsonb_array_elements(posthog_featureflag.filters->'groups') AS elem
                            WHERE elem->>'rollout_percentage' = '100'
                            AND (elem->'properties')::text = '[]'::text
                            AND elem->'variant' IS NOT NULL
                            AND elem->>'variant' IS NOT NULL
                        )
                        AND (posthog_featureflag.filters->>'multivariate' IS NOT NULL AND jsonb_array_length(posthog_featureflag.filters->'multivariate'->'variants') > 0)
                    )
                    OR (posthog_featureflag.filters IS NULL OR posthog_featureflag.filters = '{}'::jsonb)
                )
                """
            ]
        )
        return queryset.filter(usage_based_stale) | config_based_queryset

    # Handle both string "true"/"false" and boolean True/False
    is_active = value == "true" or value is True
    return queryset.filter(active=is_active)


# FeatureFlagStatusChecker is used to determine the status of a feature flag for a given user.
# Eventually, this may be used to automatically archive old flags that are no longer in use.
#
# Status can be one of the following:
# - ACTIVE: The feature flag is actively evaluated and in use.
# - STALE: The feature flag is likely safe to remove. Detection uses the best available signal:
#       1. If last_called_at exists: flag hasn't been called in 30+ days (usage-based)
#       2. If last_called_at is NULL: flag is 100% rolled out and 30+ days old (config-based)
# - ARCHIVED: The feature flag has been archived (done for good, kept for historical data).
# - DELETED: The feature flag has been soft deleted.
# - UNKNOWN: The feature flag is not found in the database.
#
# When we update the logic for stale flags, do check/update the function `_filter_request`` in feature_flag.py
class FeatureFlagStatusChecker:
    def __init__(
        self,
        feature_flag_id: int | None = None,
        feature_flag: FeatureFlag | None = None,
    ):
        self.feature_flag_id = feature_flag_id
        self.feature_flag = feature_flag

    def get_status(self) -> tuple[FeatureFlagStatus, FeatureFlagStatusReason]:
        if not self.feature_flag_id and not self.feature_flag:
            return FeatureFlagStatus.UNKNOWN, "Must provide feature flag or feature flag id"

        try:
            flag = (
                FeatureFlag.objects_including_soft_deleted.get(pk=self.feature_flag_id)
                if self.feature_flag_id
                else self.feature_flag
            )
        except FeatureFlag.DoesNotExist:
            return FeatureFlagStatus.UNKNOWN, "Flag could not be found"

        if not flag:
            return FeatureFlagStatus.UNKNOWN, "Flag could not be loaded"

        if flag.deleted:
            return FeatureFlagStatus.DELETED, "Flag has been deleted"

        if flag.archived:
            return FeatureFlagStatus.ARCHIVED, "Flag has been archived"

        # Disabled flags are not evaluated for staleness
        if not flag.active:
            return FeatureFlagStatus.ACTIVE, "Flag is disabled (not evaluated for staleness)"

        # Use the best available signal to determine if flag is stale:
        # 1. If we have usage data (last_called_at), use that - it's the most accurate
        # 2. If no usage data, fall back to configuration-based detection

        if flag.last_called_at is not None:
            # We have usage data - use it as the primary signal
            is_stale, stale_reason = self.is_flag_stale_by_usage(flag)
            if is_stale:
                return FeatureFlagStatus.STALE, stale_reason
            # Flag has recent usage
            days_since_called = (datetime.now(UTC) - flag.last_called_at).days
            if days_since_called == 0:
                return FeatureFlagStatus.ACTIVE, "Flag was called today"
            return (
                FeatureFlagStatus.ACTIVE,
                f"Flag was last called {days_since_called} day{'s' if days_since_called != 1 else ''} ago",
            )
        else:
            # No usage data - fall back to configuration-based detection
            # Only for flags that are old enough (30+ days) to have had a chance to be called
            is_flag_at_least_thirty_days_old = flag.created_at < thirty_days_ago()
            if is_flag_at_least_thirty_days_old:
                is_fully_rolled_out, rolled_out_reason = self.is_flag_fully_rolled_out(flag)
                if is_fully_rolled_out:
                    return FeatureFlagStatus.STALE, rolled_out_reason

        return FeatureFlagStatus.ACTIVE, "Flag has no usage data yet"

    def is_flag_stale_by_usage(self, flag: FeatureFlag) -> tuple[bool, FeatureFlagStatusReason]:
        """
        Check if flag is stale based on usage data (last_called_at).
        A flag is stale if it hasn't been called in 30+ days.
        """
        assert flag.last_called_at is not None, "last_called_at must not be None"
        stale_threshold = datetime.now(UTC) - timedelta(days=30)

        if flag.last_called_at < stale_threshold:
            days_since_called = (datetime.now(UTC) - flag.last_called_at).days
            return True, f"Flag has not been called in {days_since_called} days"

        return False, ""

    def get_rollout_summary(self, flag: FeatureFlag) -> "FeatureFlagRolloutSummary":
        """
        Summarize the flag's rollout configuration so callers can determine rollout
        completeness (e.g. "fully rolled out / GA") without re-parsing ``filters``.

        This is independent of ``get_status``: ``status`` reflects recent evaluation
        (was the flag called), while this reflects configuration. A flag can be
        ``active`` while only partially rolled out, or fully rolled out but ``stale``.
        """
        filters = flag.filters or {}
        groups = filters.get("groups") or []
        multivariate = filters.get("multivariate")

        has_targeting_conditions = False
        max_rollout_percentage: int | None = None
        for group in groups:
            if group.get("properties"):
                has_targeting_conditions = True
            # A missing rollout_percentage evaluates to 100% at runtime, so it counts as 100 here.
            # This is deliberately looser than effectively_full_rollout / is_group_fully_rolled_out,
            # which require an explicit 100.
            percentage = group.get("rollout_percentage")
            percentage = 100 if percentage is None else percentage
            max_rollout_percentage = (
                percentage if max_rollout_percentage is None else max(max_rollout_percentage, percentage)
            )

        is_fully_rolled_out, _ = self.is_flag_fully_rolled_out(flag)

        return FeatureFlagRolloutSummary(
            effectively_full_rollout=is_fully_rolled_out,
            has_targeting_conditions=has_targeting_conditions,
            max_rollout_percentage=max_rollout_percentage,
            is_multivariate=bool(multivariate and multivariate.get("variants")),
        )

    def is_flag_fully_rolled_out(self, flag: FeatureFlag) -> tuple[bool, FeatureFlagStatusReason]:
        multivariate = (flag.filters or {}).get("multivariate", None)
        # An empty/missing variant list is treated as boolean, matching the STALE SQL filter
        # (which routes `jsonb_array_length(variants) = 0` into the boolean branch).
        has_variants = bool(multivariate and multivariate.get("variants"))
        if has_variants:
            is_multivariate_flag_fully_rolled_out, fully_rolled_out_variant_name = (
                self.is_multivariate_flag_fully_rolled_out(flag)
            )
            if is_multivariate_flag_fully_rolled_out:
                return True, f'This flag will always use the variant "{fully_rolled_out_variant_name}"'
        elif self.is_boolean_flag_fully_rolled_out(flag):
            return True, 'This boolean flag will always evaluate to "true"'

        return False, ""

    def is_multivariate_flag_fully_rolled_out(self, flag: FeatureFlag) -> tuple[bool, str]:
        # If flag is multivariant and one variant is rolled out to 100%,
        # and there is a release condition set to 100%, it is fully rolled out.
        #
        # Alternatively, if there is a release condition set to 100% and it has a
        # variant override, the flag is fully rolled out.
        fully_rolled_out_variant_key: str | None = None
        some_release_condition_fully_rolled_out = False
        fully_rolled_out_release_condition_variant_override: str | None = None

        multivariate = (flag.filters or {}).get("multivariate") or {}
        variants = multivariate.get("variants", [])
        for variant in variants:
            if variant.get("rollout_percentage") == 100:
                fully_rolled_out_variant_key = variant.get("key")
                break

        for release_condition in (flag.filters or {}).get("groups", []):
            if self.is_group_fully_rolled_out(release_condition):
                some_release_condition_fully_rolled_out = True
                fully_rolled_out_release_condition_variant_override = (
                    fully_rolled_out_release_condition_variant_override or release_condition.get("variant", None)
                )

        fully_rolled_out_variant = (
            fully_rolled_out_release_condition_variant_override or fully_rolled_out_variant_key or ""
        )
        return some_release_condition_fully_rolled_out and (
            fully_rolled_out_release_condition_variant_override is not None or fully_rolled_out_variant_key is not None
        ), fully_rolled_out_variant

    def is_group_fully_rolled_out(self, group: dict) -> bool:
        rollout_percentage = group.get("rollout_percentage")
        properties = group.get("properties", [])
        return rollout_percentage == 100 and len(properties) == 0

    def is_boolean_flag_fully_rolled_out(self, flag: FeatureFlag) -> bool:
        # Treat missing filters, `{}`, and `{"groups": []}` as "no release conditions"
        # and therefore fully rolled out. Not a supported state, but legacy data hits
        # all three shapes (especially `{"groups": []}` post-backfill).
        release_conditions = (flag.filters or {}).get("groups", [])
        if not release_conditions:
            logger.debug(f"Boolean flag {flag.id} has no release conditions, so it is rolled out to 100%")
            return True

        # If flag is boolean flag and rolled release conditions have rolled out to 100%, it is fully rolled out.
        # The fully rolled out release condition must have no properties set.
        for release_condition in release_conditions:
            rollout_percentage = release_condition.get("rollout_percentage")
            properties = release_condition.get("properties", [])
            if rollout_percentage == 100 and len(properties) == 0:
                logger.debug(f"Boolean flag {flag.id} has a release conditions rolled out to 100%")
                return True

        return False
