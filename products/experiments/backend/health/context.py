from collections.abc import Mapping

from posthog.schema import MultipleVariantHandling

from posthog.dataclasses import frozen

from products.experiments.backend.metric_resolution import saved_metric_link_role, saved_metric_links
from products.experiments.backend.models.experiment import Experiment


@frozen
class FlagVariant:
    key: str | None
    rollout_percentage: float | None


@frozen
class FlagReleaseGroup:
    rollout_percentage: float | None
    property_count: int | None


@frozen
class FlagState:
    active: bool
    deleted: bool
    release_groups: tuple[FlagReleaseGroup, ...]
    variants: tuple[FlagVariant, ...]


@frozen
class ExposureTotals:
    total_exposures: Mapping[str, int]
    multiple_variant_handling: MultipleVariantHandling


@frozen
class HealthContext:
    """Every input of the health checks, loaded once, so that each check is a pure function of it."""

    is_launched: bool
    has_ended: bool
    archived: bool
    flag: FlagState | None
    primary_metric_count: int
    secondary_metric_count: int
    exposures: ExposureTotals | None

    @property
    def is_running(self) -> bool:
        return self.is_launched and not self.has_ended


def parse_flag_state(*, active: bool, deleted: bool, groups: object, variants: object) -> FlagState:
    return FlagState(
        active=active,
        deleted=deleted,
        release_groups=tuple(_release_group(group) for group in groups) if isinstance(groups, list) else (),
        variants=tuple(_variant(variant) for variant in variants) if isinstance(variants, list) else (),
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
        active=bool(flag.active), deleted=bool(flag.deleted), groups=flag.conditions, variants=flag.variants
    )


def load_health_context(experiment: Experiment, exposures: ExposureTotals | None = None) -> HealthContext:
    shared_metric_roles = [saved_metric_link_role(link) for link in saved_metric_links(experiment)]
    return HealthContext(
        is_launched=experiment.is_launched,
        has_ended=experiment.is_stopped,
        archived=experiment.archived,
        flag=_load_flag_state(experiment),
        primary_metric_count=len(experiment.metrics or []) + shared_metric_roles.count("primary"),
        secondary_metric_count=len(experiment.metrics_secondary or []) + shared_metric_roles.count("secondary"),
        exposures=exposures,
    )
