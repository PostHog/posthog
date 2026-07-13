import copy
import json
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Optional, cast

from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.postgres.aggregates import ArrayAgg
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import DatabaseError, models, transaction
from django.db.models import Q, QuerySet
from django.db.models.signals import post_delete, post_save
from django.http import HttpRequest
from django.utils import timezone

import structlog
from django_deprecate_fields import deprecate_field

from posthog.caching.flags_redis_cache import write_flags_to_cache
from posthog.constants import ENRICHED_DASHBOARD_INSIGHT_IDENTIFIER, PropertyOperatorType
from posthog.exceptions_capture import capture_exception
from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.file_system.constants import DEFAULT_SURFACE
from posthog.models.file_system.file_system_mixin import FileSystemSyncMixin
from posthog.models.file_system.file_system_representation import FileSystemRepresentation
from posthog.models.property import GroupTypeIndex
from posthog.models.property.property import Property, PropertyGroup
from posthog.models.signals import mutable_receiver
from posthog.models.utils import RootTeamManager, RootTeamMixin

from products.cohorts.backend.models.cohort import Cohort, CohortOrEmpty
from products.experiments.backend.models.experiment import live_experiment_exists

FIVE_DAYS = 60 * 60 * 24 * 5  # 5 days in seconds

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    from django.db.models.fields.related_descriptors import RelatedManager

    from posthog.models.team import Team

    from products.feature_flags.backend.models.evaluation_context import FeatureFlagEvaluationContext


def default_filters() -> dict:
    return {"groups": []}


def build_scheduled_change_serializer_data(flag: "FeatureFlag", payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Shape a scheduled-change payload into the serializer data applying it would produce.

    Single source of truth for both the creation-time approval gate
    (``products.approvals.backend.scheduled_changes.scheduled_change_serializer_data``) and the
    apply-time dispatcher (``FeatureFlag.scheduled_changes_dispatcher``), so the change the gate
    evaluates is exactly the change the applier makes — previously two hand-kept-in-sync copies,
    and the deep-copy-before-mutating fix had to be patched into both separately.

    Returns ``{"active": ...}`` / ``{"filters": ...}`` for a recognized payload, or ``None`` when
    the payload is malformed (missing ``operation``/``value``) or its operation is unrecognized.
    Callers decide what ``None`` means: the gate declines to gate an uninterpretable change; the
    dispatcher raises. Apply-time-only validation (variant rollout sums, payload-key matching)
    stays in the dispatcher.
    """
    operation = payload.get("operation")
    if operation is None or "value" not in payload:
        return None
    value = payload["value"]

    if operation == "update_status":
        return {"active": value}

    current_filters = flag.get_filters()

    if operation == "add_release_condition":
        new_groups = value.get("groups", []) if isinstance(value, dict) else []
        return {
            "filters": {
                **current_filters,
                "groups": current_filters.get("groups", []) + new_groups,
            }
        }

    if operation == "update_variants":
        if not isinstance(value, dict):
            return None
        new_variants = value.get("variants", [])
        new_payloads = value.get("payloads", {})
        # Deep-copy before mutating: current_filters is flag.filters (a live reference), so assigning
        # into its nested multivariate dict would mutate the flag's pre-change state in place and
        # defeat the approval gate's old-vs-new comparison.
        updated_multivariate = copy.deepcopy(current_filters.get("multivariate", {}))
        updated_multivariate["variants"] = new_variants
        return {
            "filters": {
                **current_filters,
                "multivariate": updated_multivariate,
                "payloads": new_payloads,
            }
        }

    return None


class FeatureFlagManager(RootTeamManager):
    def get_queryset(self):
        return super().get_queryset().exclude(deleted=True)


class FeatureFlag(FileSystemSyncMixin, ModelActivityMixin, RootTeamMixin, models.Model):
    # Reverse relation from FeatureFlagEvaluationContext.feature_flag (related_name="flag_evaluation_contexts").
    if TYPE_CHECKING:
        flag_evaluation_contexts: RelatedManager[FeatureFlagEvaluationContext]

    # When adding new fields, make sure to update organization_feature_flags.py::copy_flags
    key = models.CharField(max_length=400)
    name = models.TextField(
        blank=True
    )  # contains description for the FF (field name `name` is kept for backwards-compatibility)

    filters = models.JSONField(default=default_filters)
    # DEPRECATED: rollout percentage now lives in filters["groups"][N]["rollout_percentage"]
    rollout_percentage = deprecate_field(models.IntegerField(null=True, blank=True))

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(null=True, auto_now=True)
    deleted = models.BooleanField(default=False)
    active = models.BooleanField(default=True)
    # Archived flags are "done for good" (e.g. a finished experiment's flag): hidden from
    # the flag list by default but kept so linked experiments/surveys retain their data.
    # An archived flag must be disabled — enforced at the DB level by the
    # `archived_flag_must_be_disabled` check constraint below, so writers that bypass the
    # serializer (e.g. the experiment service) can't persist an archived-but-still-serving flag.
    archived = models.BooleanField(default=False, db_default=False)

    version = models.IntegerField(default=1, null=True)
    last_modified_by = models.ForeignKey(
        "posthog.User",
        on_delete=models.SET_NULL,
        null=True,
        related_name="updated_feature_flags",
        db_index=False,
    )

    rollback_conditions = models.JSONField(null=True, blank=True)
    performed_rollback = models.BooleanField(null=True, blank=True)

    ensure_experience_continuity = models.BooleanField(default=False, null=True, blank=True)
    usage_dashboard = models.ForeignKey("dashboards.Dashboard", on_delete=models.SET_NULL, null=True, blank=True)
    analytics_dashboards: models.ManyToManyField = models.ManyToManyField(
        "dashboards.Dashboard",
        through="FeatureFlagDashboards",
        related_name="analytics_dashboards",
        related_query_name="analytics_dashboard",
    )
    # whether a feature is sending us rich analytics, like views & interactions.
    has_enriched_analytics = models.BooleanField(default=False, null=True, blank=True)

    is_remote_configuration = models.BooleanField(default=False, null=True, blank=True)
    has_encrypted_payloads = models.BooleanField(default=False, null=True, blank=True)

    EVALUATION_RUNTIME_CHOICES = [
        ("server", "Server"),
        ("client", "Client"),
        ("all", "All"),
    ]
    evaluation_runtime = models.CharField(
        max_length=10,
        choices=EVALUATION_RUNTIME_CHOICES,
        default="all",
        null=True,
        blank=True,
        help_text="Specifies where this feature flag should be evaluated",
    )

    BUCKETING_IDENTIFIER_CHOICES = [
        ("distinct_id", "User ID (default)"),
        ("device_id", "Device ID"),
    ]
    bucketing_identifier = models.CharField(
        max_length=50,
        choices=BUCKETING_IDENTIFIER_CHOICES,
        default="distinct_id",
        null=True,
        blank=True,
        help_text="Identifier used for bucketing users into rollout and variants",
    )

    # Cache projection: stored in Redis but not a DB field. Avoids N+1 queries
    # when accessing evaluation context names for many flags at once.
    _evaluation_tag_names: Optional[list[str]] = None

    # Cache projection: whether the flag backs an experiment. Annotated via a bulk
    # Exists query (or read from cache) to avoid a per-flag experiment lookup.
    _has_experiment: Optional[bool] = None

    last_called_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Last time this feature flag was called (from $feature_flag_called events)",
    )

    objects = FeatureFlagManager()  # type: ignore
    objects_including_soft_deleted: models.Manager["FeatureFlag"] = RootTeamManager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "key"], name="unique key for team"),
            # An archived flag must be disabled — keeps an archived flag from ever serving traffic,
            # regardless of which code path wrote it.
            models.CheckConstraint(condition=~Q(archived=True, active=True), name="archived_flag_must_be_disabled"),
        ]
        db_table = "posthog_featureflag"

    def __str__(self):
        return f"{self.key} ({self.pk})"

    def _tombstone_suffix(self) -> str:
        # Soft-deleting a flag that's still referenced (e.g. by a stopped experiment)
        # renames its key to free the original for reuse. This is the single source of
        # truth for that suffix — both tombstoned_key() and key_without_tombstone() use it.
        return f":deleted:{self.id}"

    def tombstoned_key(self) -> str:
        # The key to store when soft-deleting this flag. The id keeps it unique while
        # freeing the original key for a new flag.
        return f"{self.key}{self._tombstone_suffix()}"

    def key_without_tombstone(self) -> str:
        # The original key, with the soft-delete tombstone stripped. Readers that need
        # the pre-deletion key (e.g. experiment query runners resolving historical
        # events) call this. Only strips when the flag is actually deleted, so a live
        # flag whose key coincidentally ends this way is left untouched.
        suffix = self._tombstone_suffix()
        if self.deleted and self.key.endswith(suffix):
            return self.key[: -len(suffix)]
        return self.key

    def clean(self) -> None:
        """Reject encrypted payloads on non-remote-config flags.

        Django does not invoke clean() from save(), so this fires only from
        admin and explicit full_clean() callers. The HTTP path is gated by
        FeatureFlagSerializer._validate_encrypted_payloads_require_remote_config.
        """
        super().clean()
        if self.has_encrypted_payloads and not self.is_remote_configuration:
            raise ValidationError("Encrypted payloads require the flag to be a remote configuration.")

    @classmethod
    def get_file_system_unfiled(cls, team: "Team", surface: str = DEFAULT_SURFACE) -> QuerySet["FeatureFlag"]:
        base_qs = cls.objects.filter(team=team, deleted=False)
        return cls._filter_unfiled_queryset(base_qs, team, type="feature_flag", ref_field="id", surface=surface)

    def get_file_system_representation(self) -> FileSystemRepresentation:
        return FileSystemRepresentation(
            base_folder=self._get_assigned_folder("Unfiled/Feature Flags"),
            type="feature_flag",  # sync with APIScopeObject in scopes.py
            ref=str(self.id),
            name=self.key or "Untitled",
            href=f"/feature_flags/{self.id}",
            meta={
                "created_at": str(self.created_at),
                "created_by": self.created_by_id,
            },
            should_delete=self.deleted,
        )

    def get_analytics_metadata(self) -> dict:
        filter_count = sum(len(condition.get("properties", [])) for condition in self.conditions)
        variants_count = len(self.variants)
        payload_count = len(self._payloads)

        return {
            "groups_count": len(self.conditions),
            "has_variants": variants_count > 0,
            "variants_count": variants_count,
            "has_filters": filter_count > 0,
            "has_rollout_percentage": any(condition.get("rollout_percentage") for condition in self.conditions),
            "filter_count": filter_count,
            "created_at": self.created_at,
            "aggregating_by_groups": self.aggregation_group_type_index is not None,
            "payload_count": payload_count,
        }

    @property
    def conditions(self):
        "Each feature flag can have multiple conditions to match, they are OR-ed together."
        return self.get_filters().get("groups", []) or []

    @property
    def has_feature_enrollment(self) -> bool:
        return bool(self.get_filters().get("feature_enrollment", False))

    @property
    def holdout(self):
        return self.get_filters().get("holdout", None)

    @property
    def _payloads(self):
        return self.get_filters().get("payloads", {}) or {}

    def get_payload(self, match_val: str) -> Optional[object]:
        return self._payloads.get(match_val, None)

    @property
    def aggregation_group_type_index(self) -> Optional[GroupTypeIndex]:
        "If None, aggregating this feature flag by persons, otherwise by groups of given group_type_index"
        return self.get_filters().get("aggregation_group_type_index", None)

    @property
    def variants(self):
        # :TRICKY: .get("multivariate", {}) returns "None" if the key is explicitly set to "null" inside json filters
        multivariate = self.get_filters().get("multivariate", None)
        if isinstance(multivariate, dict):
            variants = multivariate.get("variants", None)
            if isinstance(variants, list):
                return variants
        return []

    @property
    def usage_dashboard_has_enriched_insights(self) -> bool:
        if not self.usage_dashboard:
            return False

        return any(
            ENRICHED_DASHBOARD_INSIGHT_IDENTIFIER in (tile.insight.name or "")
            for tile in self.usage_dashboard.tiles.all()
            if tile.insight
        )

    @property
    def evaluation_tag_names(self) -> list[str] | None:
        """
        Returns evaluation context names for this flag.

        Preferred source is the cache-populated list from Redis (set on instances
        as `_evaluation_tag_names`). If not present, falls back to the DB relation
        via `flag_evaluation_contexts` → `EvaluationContext.name`.
        """
        cached = getattr(self, "_evaluation_tag_names", None)
        if cached is not None:
            return cached

        try:
            return [
                ec.evaluation_context.name
                for ec in self.flag_evaluation_contexts.select_related("evaluation_context").all()
            ]
        except (AttributeError, DatabaseError):
            return None

    def get_filters(self) -> dict:
        return self.filters

    def transform_cohort_filters_for_easy_evaluation(
        self,
        using_database: str = "default",
        seen_cohorts_cache: Optional[dict[int, CohortOrEmpty]] = None,
    ):
        """
        Expands cohort filters into person property filters when possible.
        This allows for easy local flag evaluation.
        """
        # Expansion depends on number of conditions on the flag.
        # If flag has only the cohort condition, we get more freedom to maneuver in the cohort expansion.
        # If flag has multiple conditions, we can only expand the cohort condition if it's a single property group.
        # Also support only a single cohort expansion. i.e. a flag with multiple cohort conditions will not be expanded.
        # Few more edge cases are possible here, where expansion is possible, but it doesn't seem
        # worth it trying to catch all of these.

        if seen_cohorts_cache is None:
            seen_cohorts_cache = {}

        if len(self.get_cohort_ids(using_database=using_database, seen_cohorts_cache=seen_cohorts_cache)) != 1:
            return self.conditions

        cohort_group_rollout = None
        cohort: CohortOrEmpty = None

        parsed_conditions = []
        for condition in self.conditions:
            if condition.get("variant"):
                # variant overrides are not supported for cohort expansion.
                return self.conditions

            cohort_condition = False
            props = condition.get("properties", [])
            cohort_group_rollout = condition.get("rollout_percentage")
            for prop in props:
                if prop.get("type") == "cohort":
                    cohort_condition = True
                    cohort_id = int(prop.get("value"))
                    if cohort_id:
                        if len(props) > 1:
                            # We cannot expand this cohort condition if it's not the only property in its group.
                            return self.conditions
                        try:
                            if cohort_id in seen_cohorts_cache:
                                cohort = seen_cohorts_cache[cohort_id]
                                if not cohort:
                                    return self.conditions
                            else:
                                cohort = Cohort.objects.db_manager(using_database).get(
                                    pk=cohort_id,
                                    team__project_id=self.team.project_id,
                                    deleted=False,
                                )
                                seen_cohorts_cache[cohort_id] = cohort
                        except Cohort.DoesNotExist:
                            seen_cohorts_cache[cohort_id] = ""
                            return self.conditions
            if not cohort_condition:
                # flag group without a cohort filter, let it be as is.
                parsed_conditions.append(condition)

        if not cohort or len(cohort.properties.flat) == 0:
            return self.conditions

        if not all(property.type == "person" for property in cohort.properties.flat):
            # Cohorts containing non-person property types (e.g. behavioral, person_metadata)
            # are deliberately not inlined into flag groups. They flow to SDKs as cohort
            # references; modern SDKs raise InconclusiveMatchError on unknown property types
            # and fall back to /flags/, where the Rust matcher handles them.
            #
            # Note: do NOT route person_metadata through the legacy posthog/queries/base.py
            # paths (`property_to_Q` / `match_property`). Those don't recognize the type;
            # `match_property` in particular dispatches purely on `key` and would silently
            # produce a wrong-but-not-erroring result.
            return self.conditions

        if any(property.negation for property in cohort.properties.flat):
            # Local evaluation doesn't support negation.
            return self.conditions

        # all person properties, so now if we can express the cohort as feature flag groups, we'll be golden.

        # If there's only one effective property group, we can always express this as feature flag groups.
        # A single ff group, if cohort properties are AND'ed together.
        # Multiple ff groups, if cohort properties are OR'ed together.
        from posthog.models.property.util import clear_excess_levels

        target_properties = clear_excess_levels(cohort.properties)

        if isinstance(target_properties, Property):
            # cohort was effectively a single property.
            parsed_conditions.append(
                {
                    "properties": [target_properties.to_dict()],
                    "rollout_percentage": cohort_group_rollout,
                }
            )

        elif isinstance(target_properties.values[0], Property):
            # Property Group of properties
            if target_properties.type == PropertyOperatorType.AND:
                parsed_conditions.append(
                    {
                        "properties": [prop.to_dict() for prop in target_properties.values],
                        "rollout_percentage": cohort_group_rollout,
                    }
                )
            else:
                # cohort OR requires multiple ff group
                for prop in target_properties.values:
                    parsed_conditions.append(
                        {
                            "properties": [prop.to_dict()],
                            "rollout_percentage": cohort_group_rollout,
                        }
                    )
        else:
            # If there's nested property groups, we need to express that as OR of ANDs.
            # Being a bit dumb here, and not trying to apply De Morgan's law to coerce AND of ORs into OR of ANDs.
            if target_properties.type == PropertyOperatorType.AND:
                return self.conditions

            for prop_group in cast(list[PropertyGroup], target_properties.values):
                if (
                    len(prop_group.values) == 0
                    or not isinstance(prop_group.values[0], Property)
                    or (prop_group.type == PropertyOperatorType.OR and len(prop_group.values) > 1)
                ):
                    # too nested or invalid, bail out
                    return self.conditions

                parsed_conditions.append(
                    {
                        "properties": [prop.to_dict() for prop in prop_group.values],
                        "rollout_percentage": cohort_group_rollout,
                    }
                )

        return parsed_conditions

    def get_cohort_ids(
        self,
        using_database: str = "default",
        seen_cohorts_cache: Optional[dict[int, CohortOrEmpty]] = None,
        sort_by_topological_order=False,
        stop_traversal_at_static: bool = False,
    ) -> list[int]:
        from products.cohorts.backend.models.util import get_all_cohort_dependencies, sort_cohorts_topologically

        if seen_cohorts_cache is None:
            seen_cohorts_cache = {}

        cohort_ids = set()
        for condition in self.conditions:
            props = condition.get("properties", [])
            for prop in props:
                if prop.get("type") == "cohort":
                    cohort_id = int(prop.get("value"))
                    try:
                        if cohort_id in seen_cohorts_cache:
                            cohort: CohortOrEmpty = seen_cohorts_cache[cohort_id]
                            if not cohort:
                                continue
                        else:
                            cohort = Cohort.objects.db_manager(using_database).get(
                                pk=cohort_id,
                                team__project_id=self.team.project_id,
                                deleted=False,
                            )
                            seen_cohorts_cache[cohort_id] = cohort

                        cohort_ids.add(cohort.pk)
                        cohort_ids.update(
                            [
                                dependency_cohort.pk
                                for dependency_cohort in get_all_cohort_dependencies(
                                    cohort,
                                    using_database=using_database,
                                    seen_cohorts_cache=seen_cohorts_cache,
                                    stop_traversal_at_static=stop_traversal_at_static,
                                )
                            ]
                        )
                    except Cohort.DoesNotExist:
                        seen_cohorts_cache[cohort_id] = ""
                        continue
        if sort_by_topological_order:
            return sort_cohorts_topologically(cohort_ids, seen_cohorts_cache)

        return list(cohort_ids)

    def scheduled_changes_dispatcher(
        self,
        payload,
        user: Optional[AbstractBaseUser] = None,
        scheduled_change_id: Optional[int] = None,
    ):
        from products.feature_flags.backend.api.feature_flag import FeatureFlagSerializer

        if "operation" not in payload or "value" not in payload:
            raise Exception("Invalid payload")

        # Store scheduled change context on the instance for activity logging
        if scheduled_change_id is not None:
            self._scheduled_change_context = {"scheduled_change_id": scheduled_change_id}

        http_request = HttpRequest()
        # We kind of cheat here set the request user to the user who created the scheduled change
        # It's not the correct type, but it matches enough to get the job done
        http_request.user = user or self.created_by  # type: ignore
        http_request.method = "PATCH"  # This is a partial update, not a new creation
        context = {
            "request": http_request,
            "team_id": self.team_id,
            "project_id": self.team.project_id,
        }

        # Apply-time-only validation for variant changes, before shaping the payload. The gate skips
        # these because an invalid change can't be approved into applying anyway; here they surface
        # as errors at fire time.
        if payload["operation"] == "update_variants":
            variant_data = payload["value"]
            new_variants = variant_data.get("variants", [])
            new_payloads = variant_data.get("payloads", {})

            if new_variants:
                total_rollout = sum(variant.get("rollout_percentage", 0) for variant in new_variants)
                if total_rollout != 100:
                    raise ValueError(f"Invalid variant rollout percentages: sum is {total_rollout}, must be 100")

            variant_keys = {v.get("key") for v in new_variants}
            payload_keys = set(new_payloads.keys()) if new_payloads else set()

            # Only validate payload-variant key matching if both exist and are non-empty
            # Allow no payloads (for variants without payloads) or empty variants
            if payload_keys and variant_keys and not payload_keys.issubset(variant_keys):
                invalid_keys = payload_keys - variant_keys
                raise ValueError(f"Payload keys {invalid_keys} don't match variant keys {variant_keys}")

        # Shape the payload through the shared builder the approval gate also uses, so the applied
        # change is exactly the one the gate evaluated.
        serializer_data = build_scheduled_change_serializer_data(self, payload)
        if serializer_data is None:
            raise Exception(f"Unrecognized operation: {payload['operation']}")

        serializer = FeatureFlagSerializer(self, data=serializer_data, context=context, partial=True)
        if serializer.is_valid(raise_exception=True):
            serializer.save()

    @property
    def uses_cohorts(self) -> bool:
        for condition in self.conditions:
            props = condition.get("properties") or []
            for prop in props:
                if prop.get("type") == "cohort":
                    return True
        return False


@mutable_receiver([post_save, post_delete], sender=FeatureFlag)
def refresh_flag_cache_on_updates(sender, instance, **kwargs):
    # Defer cache update until after the transaction commits
    # This ensures the database has the new data before we query it
    transaction.on_commit(lambda: set_feature_flags_for_team_in_cache(instance.team.project_id))


class FeatureFlagHashKeyOverride(models.Model):
    # Can't use a foreign key to feature_flag_key directly, since
    # the unique constraint is on (team_id+key), and not just key.
    # A standard id foreign key leads to INNER JOINs every time we want to get the key
    # and we only ever want to get the key.
    feature_flag_key = models.CharField(max_length=400)
    # DO_NOTHING: Person/Team deletion handled manually via FeatureFlagHashKeyOverride.objects.filter(...).delete()
    # in delete_bulky_postgres_data(). Django CASCADE doesn't work across separate databases.
    # db_constraint=False: No database FK constraint - FeatureFlagHashKeyOverride may live in separate database
    person = models.ForeignKey("posthog.Person", on_delete=models.DO_NOTHING, db_constraint=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.DO_NOTHING, db_constraint=False)
    hash_key = models.CharField(max_length=400)

    class Meta:
        # migrations managed via rust/persons_migrations
        managed = False
        constraints = [
            models.UniqueConstraint(
                fields=["team", "person", "feature_flag_key"],
                name="Unique hash_key for a user/team/feature_flag combo",
            )
        ]
        db_table = "posthog_featureflaghashkeyoverride"


# DEPRECATED: This model is no longer used, but it's not deleted to avoid downtime
class FeatureFlagOverride(models.Model):
    feature_flag = models.ForeignKey("FeatureFlag", on_delete=models.CASCADE)
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE)
    override_value = models.JSONField()
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "feature_flag", "team"],
                name="unique feature flag for a user/team combo",
            )
        ]
        db_table = "posthog_featureflagoverride"


def get_feature_flags(
    team: Optional["Team"] = None,
    project_id: Optional[int] = None,
    exclude_encrypted_payloads: bool = False,
) -> list[FeatureFlag]:
    """
    Fetch FeatureFlag objects for a team or project.

    Evaluation tags are always aggregated using ArrayAgg for performance.
    This avoids N+1 queries when serializing flags with evaluation tags.

    Args:
        team: Team to get flags for (mutually exclusive with project_id)
        project_id: Project ID to get flags for (mutually exclusive with team)
        exclude_encrypted_payloads: If True, exclude flags with
            has_encrypted_payloads=True. These flags can only be accessed
            via the /remote_config endpoint, which handles decryption.
            The model invariant guarantees has_encrypted_payloads implies
            is_remote_configuration, so this filter covers all encrypted flags.

    Returns:
        List of FeatureFlag model instances with evaluation tags pre-loaded
    """
    # Build query filter
    filter_kwargs: dict[str, Any]
    if team is not None:
        filter_kwargs = {"team": team}
    elif project_id is not None:
        filter_kwargs = {"team__project_id": project_id}
    else:
        raise ValueError("Either team or project_id must be provided")

    # Include disabled flags (active=False) so flag dependencies can reference them
    # and evaluate them as false, rather than raising DependencyNotFound errors.

    # Aggregate evaluation context names into a string array per flag in one query,
    # avoiding N+1 queries when serializing many flags.
    qs = FeatureFlag.objects.filter(**filter_kwargs)

    # Use .exclude() (not .filter(=False)) so legacy rows with NULL
    # has_encrypted_payloads remain included, matching prior behavior.
    if exclude_encrypted_payloads:
        qs = qs.exclude(has_encrypted_payloads=True)

    qs = qs.annotate(
        evaluation_tag_names_agg=ArrayAgg(
            "flag_evaluation_contexts__evaluation_context__name",
            filter=Q(flag_evaluation_contexts__isnull=False),
            distinct=True,
        ),
        has_experiment_agg=live_experiment_exists(),
    )

    all_feature_flags = list(qs)

    # Transfer the aggregated tag names to the _evaluation_tag_names attribute
    # so the serializer can access them without additional queries. This is a
    # cache projection pattern - we're storing derived data on the model instance
    # that will be serialized to cache.
    for _flag in all_feature_flags:
        try:
            _flag._evaluation_tag_names = getattr(_flag, "evaluation_tag_names_agg", None)
        except AttributeError:
            # evaluation_tag_names_agg field missing from aggregation query
            _flag._evaluation_tag_names = None
        _flag._has_experiment = _flag.has_experiment_agg

    return all_feature_flags


def serialize_feature_flags(flags: list[FeatureFlag]) -> list[dict[str, Any]]:
    """
    Serialize FeatureFlag objects to dictionary format.

    Args:
        flags: List of FeatureFlag instances to serialize

    Returns:
        List of serialized flag dictionaries
    """
    from products.feature_flags.backend.api.feature_flag import EvaluationFeatureFlagSerializer

    serialized_data = EvaluationFeatureFlagSerializer(flags, many=True).data
    return list(serialized_data)


def set_feature_flags_for_team_in_cache(
    project_id: int,
) -> list[FeatureFlag]:
    # Fetch flags once (with evaluation contexts pre-loaded)
    all_feature_flags = get_feature_flags(project_id=project_id)

    # Serialize for cache storage
    serialized_flags = serialize_feature_flags(all_feature_flags)

    # Write to Redis cache
    write_flags_to_cache(f"team_feature_flags_{project_id}", json.dumps(serialized_flags), FIVE_DAYS)

    return all_feature_flags


def get_feature_flags_for_team_in_cache(project_id: int) -> Optional[list[FeatureFlag]]:
    try:
        flag_data = cache.get(f"team_feature_flags_{project_id}")
    except Exception:
        logger.exception("Redis is unavailable")
        return None

    if flag_data is not None:
        try:
            parsed_data = json.loads(flag_data)
            flags = [_feature_flag_from_cache_entry(entry) for entry in parsed_data]
            # Filter to only return active flags. The cache includes inactive flags
            # for dependency resolution (used by the Rust service), but Python callers
            # expect only active flags for backward compatibility.
            return [f for f in flags if f.active]
        except Exception as e:
            logger.exception("Error parsing flags from cache")
            capture_exception(e)
            return None

    return None


@lru_cache(maxsize=1)
def _feature_flag_model_field_names() -> frozenset[str]:
    """Names accepted by the FeatureFlag constructor (concrete fields only), used to
    separate real model fields from serializer-only extras in cached payloads. The
    field set is constant for the process, so it's computed once and cached."""
    names: set[str] = set()
    for field in FeatureFlag._meta.concrete_fields:
        names.add(field.name)
        names.add(field.attname)  # FK attnames like `team_id`
    return frozenset(names)


def _feature_flag_from_cache_entry(entry: dict[str, Any]) -> FeatureFlag:
    """Reconstruct a FeatureFlag from one cached payload entry.

    The cache payload comes from EvaluationFeatureFlagSerializer, which emits
    SerializerMethodFields (e.g. `evaluation_contexts`, `has_experiment`) that are not
    model fields. Keep only real model fields so unknown extras are ignored rather than
    crashing the FeatureFlag(**...) constructor; known extras are then assigned onto the
    instance.
    """
    model_field_names = _feature_flag_model_field_names()
    model_fields = {key: value for key, value in entry.items() if key in model_field_names}

    flag = FeatureFlag(**model_fields)
    # Evaluation contexts are derived data, not a DB field. Accept both the current
    # `evaluation_contexts` key and the legacy `evaluation_tags` key for entries
    # written before the rename.
    flag._evaluation_tag_names = entry.get("evaluation_contexts", entry.get("evaluation_tags"))
    # Preserve has_experiment so a cache-read flag answers without a per-flag experiment query.
    flag._has_experiment = entry.get("has_experiment")
    return flag


class FeatureFlagDashboards(models.Model):
    feature_flag = models.ForeignKey("FeatureFlag", on_delete=models.CASCADE)
    dashboard = models.ForeignKey("dashboards.Dashboard", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["feature_flag", "dashboard"],
                name="unique feature flag for a dashboard",
            )
        ]
        db_table = "posthog_featureflagdashboards"
