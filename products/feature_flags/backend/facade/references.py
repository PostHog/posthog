"""The cohorts and flags a feature flag's stored config references.

``references`` reads a decoded config of either format and returns identities only: cohort
ids and flag ids, never the stored dicts. Config version 1 holds cohort and flag references
as ``groups[*].properties`` with ``type == "cohort"`` or ``type == "flag"``. Config version 2
holds the same property shapes in each rule's targeting. An unsupported document raises
``ConfigFormatError``; it is never read as a flag with no references.

``referenced_cohort_ids`` and ``flag_dependency_properties`` serve the SDK definitions
payload, which carries v1 documents only. It rewrites flag references from ids to keys and
annotates them with a dependency chain, so ``flag_dependency_properties`` returns the
caller's own property dicts and those in-place rewrites keep working. Both raise
``ConfigFormatError`` for any other format, because a producer that silently dropped the
references would publish an unsupported document into a feed built for v1 readers.

Deliberately free of Django/DRF imports (same reason as ``facade.filters``).
"""

from collections.abc import Iterable, Mapping
from typing import Any, Literal

from posthog.dataclasses import frozen

from products.feature_flags.backend.facade.config import (
    ConfigFormatError,
    ConfigV1,
    DecodedConfig,
    UnsupportedConfig,
    decode_config,
    require_v1_config,
)
from products.feature_flags.backend.types import FlagProperty, PropertyFilterType

# "skip" drops a reference whose id is not an integer; "raise" lets int()'s error out.
InvalidIds = Literal["skip", "raise"]


@frozen
class FlagReferences:
    cohort_ids: tuple[int, ...] = ()  # first-seen order
    flag_ids: tuple[int, ...] = ()  # first-seen order


def references(
    config: DecodedConfig, *, invalid_cohort_ids: InvalidIds = "skip", invalid_flag_ids: InvalidIds = "skip"
) -> FlagReferences:
    """The cohorts and flags a decoded config names.

    A v1 document whose groups or properties are not lists of objects raises AttributeError or
    TypeError, as the v1 readers always did; the caller decides whether that skips the row or
    fails.
    """
    if isinstance(config, UnsupportedConfig):
        raise ConfigFormatError(config.config_format)
    if isinstance(config, ConfigV1):
        groups = config.filters.get("groups") or []
        predicates = [prop for group in groups for prop in group.get("properties") or []]
    else:
        predicates = [prop for rule in config.rules for prop in rule.reference_predicates]
    return FlagReferences(
        cohort_ids=_ids(predicates, PropertyFilterType.COHORT, "value", invalid_cohort_ids),
        flag_ids=_ids(predicates, PropertyFilterType.FLAG, "key", invalid_flag_ids),
    )


def _ids(
    predicates: Iterable[Mapping[str, Any]], property_type: PropertyFilterType, field: str, invalid_ids: InvalidIds
) -> tuple[int, ...]:
    ids: dict[int, None] = {}
    for prop in predicates:
        if prop.get("type") != property_type:
            continue
        value: Any = prop.get(field)
        try:
            ids[int(value)] = None
        except (TypeError, ValueError, OverflowError):
            if invalid_ids == "raise":
                raise
    return tuple(ids)


def referenced_cohort_ids(filters: Mapping[str, Any] | None) -> set[int]:
    """Cohort ids the release conditions of a v1 document reference.

    Raises ``ConfigFormatError`` for any other config format. A ``value`` that is not an
    integer is skipped, the same tolerance every producer already applied; a consumer
    that needs strictness resolves the ids itself.
    """
    require_v1_config(filters)
    return set(references(decode_config(filters)).cohort_ids)


def flag_dependency_properties(filters: Mapping[str, Any] | None) -> list[FlagProperty]:
    """The ``type == "flag"`` properties in the release conditions of a v1 document.

    Raises ``ConfigFormatError`` for any other config format. The returned dicts are the
    caller's own objects, so a consumer can rewrite them in place. ``key`` holds the
    referenced flag's id or key; the consumer decides which it accepts.
    """
    return _v1_properties(filters, PropertyFilterType.FLAG)


def _v1_properties(filters: Mapping[str, Any] | None, property_type: PropertyFilterType) -> list[FlagProperty]:
    require_v1_config(filters)
    # Only ``groups`` can hold cohort or flag properties: ``feature_enrollment`` is a
    # boolean gate evaluated against ``$feature_enrollment/*`` person properties, and
    # ``holdout`` carries no property filters. Explicit nulls occur in stored v1 data
    # (see FeatureFlag.conditions); read them as empty.
    return [
        prop
        for group in (filters or {}).get("groups") or []
        for prop in group.get("properties") or []
        if prop.get("type") == property_type
    ]
