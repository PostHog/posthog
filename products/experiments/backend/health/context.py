from collections.abc import Mapping

from posthog.schema import MultipleVariantHandling

from posthog.dataclasses import frozen


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


def parse_flag_state(*, active: bool, deleted: bool, filters: object) -> FlagState:
    if not isinstance(filters, dict):
        filters = {}
    groups = filters.get("groups")
    multivariate = filters.get("multivariate")
    variants = multivariate.get("variants") if isinstance(multivariate, dict) else None
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
