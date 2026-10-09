from collections.abc import Mapping

from posthog.schema import MultipleVariantHandling

from posthog.dataclasses import frozen

from products.experiments.backend.metric_resolution import saved_metric_link_role, saved_metric_links
from products.experiments.backend.models.experiment import Experiment
from products.feature_flags.backend.facade.filters import pinned_variant, reachable_conditions


@frozen
class FlagVariant:
    key: str | None
    rollout_percentage: float | None


@frozen
class FlagReleaseGroup:
    rollout_percentage: float | None
    property_count: int | None


@frozen
class ReachableCondition:
    # Numbered from 1, as the page labels the release conditions ("Set 2").
    number: int
    pinned_variant: str | None


@frozen
class FlagState:
    active: bool
    deleted: bool
    release_groups: tuple[FlagReleaseGroup, ...]
    variants: tuple[FlagVariant, ...]
    # The release conditions that can serve a request, in evaluation order.
    reachable_conditions: tuple[ReachableCondition, ...]


@frozen
class ExposureTotals:
    total_exposures: Mapping[str, int]
    multiple_variant_handling: MultipleVariantHandling
    # None when the exposure query had too little data for the sample ratio test.
    sample_ratio_mismatch_p_value: float | None
    hours_since_launch: float | None


@frozen
class HealthContext:
    """Every input of the health checks, loaded once, so that each check is a pure function of it."""

    is_launched: bool
    is_running: bool
    has_ended: bool
    is_paused: bool
    archived: bool
    flag: FlagState | None
    primary_metric_count: int
    secondary_metric_count: int
    exposures: ExposureTotals | None


def parse_flag_state(
    *,
    active: bool,
    deleted: bool,
    groups: object,
    variants: object,
    aggregation_group_type_index: int | None = None,
    early_exit: bool = False,
) -> FlagState:
    conditions = groups if isinstance(groups, list) else []
    flag_variants = tuple(_variant(variant) for variant in variants) if isinstance(variants, list) else ()
    variant_keys = {variant.key for variant in flag_variants if variant.key}
    reachable = reachable_conditions(conditions, flag_aggregation=aggregation_group_type_index, early_exit=early_exit)
    return FlagState(
        active=active,
        deleted=deleted,
        release_groups=tuple(_release_group(group) for group in conditions),
        variants=flag_variants,
        reachable_conditions=tuple(
            ReachableCondition(number=index + 1, pinned_variant=pinned_variant(conditions[index], variant_keys))
            for index in reachable
        ),
    )


def _release_group(group: object) -> FlagReleaseGroup:
    if not isinstance(group, dict):
        return FlagReleaseGroup(rollout_percentage=None, property_count=None)
    properties = group.get("properties")
    return FlagReleaseGroup(
        rollout_percentage=_percentage(group.get("rollout_percentage")),
        property_count=len(properties) if isinstance(properties, list) else None,
    )


def _variant(variant: object) -> FlagVariant:
    if not isinstance(variant, dict):
        return FlagVariant(key=None, rollout_percentage=None)
    key = variant.get("key")
    return FlagVariant(
        key=key if isinstance(key, str) else None,
        rollout_percentage=_percentage(variant.get("rollout_percentage")),
    )


def _percentage(value: object) -> float | None:
    # The page compares with `=== 0` and `=== 100`, so only a JSON number can match. A string or a
    # boolean must not, and Python's `False == 0` would let a boolean through.
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _load_flag_state(experiment: Experiment) -> FlagState | None:
    # django-stubs types the id as int, but an unsaved instance can carry None.
    feature_flag_id: int | None = experiment.feature_flag_id
    if feature_flag_id is None:
        return None
    flag = experiment.feature_flag
    return parse_flag_state(
        active=bool(flag.active),
        deleted=bool(flag.deleted),
        groups=flag.conditions,
        variants=flag.variants,
        aggregation_group_type_index=flag.aggregation_group_type_index,
        early_exit=flag.early_exit,
    )


def load_health_context(experiment: Experiment, exposures: ExposureTotals | None = None) -> HealthContext:
    shared_metric_roles = [saved_metric_link_role(link) for link in saved_metric_links(experiment)]
    return HealthContext(
        is_launched=experiment.is_launched,
        is_running=experiment.is_running,
        has_ended=experiment.is_stopped,
        is_paused=experiment.is_paused,
        archived=experiment.archived,
        flag=_load_flag_state(experiment),
        primary_metric_count=len(experiment.metrics or []) + shared_metric_roles.count("primary"),
        secondary_metric_count=len(experiment.metrics_secondary or []) + shared_metric_roles.count("secondary"),
        exposures=exposures,
    )
