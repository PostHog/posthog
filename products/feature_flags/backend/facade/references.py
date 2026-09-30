"""The cohorts and flags a feature flag's stored config references.

The SDK definitions payload and the Rust service cache both need two reads of a
``filters`` document: which cohorts its release conditions reference, and which
properties make it depend on other flags. Both are config version 1 knowledge
(``groups[*].properties`` with ``type == "cohort"`` or ``type == "flag"``), so this
module owns them behind the format check. A document in any other format raises
``ConfigFormatError`` before a v1 key is read; it is never read as a flag with no
references, because a producer that silently dropped the references would publish an
unsupported document into a feed built for v1 readers.

Consumers keep their own meaning of a reference: the definitions payload rewrites flag
references from ids to keys and annotates them with a dependency chain, the service
cache parses them as integer ids, and the model resolves cohort ids against the
database. ``flag_dependency_properties`` therefore returns the caller's own property
dicts so those in-place rewrites keep working.

Deliberately free of Django/DRF imports (same reason as ``facade.filters``).
"""

from collections.abc import Mapping
from typing import Any

from products.feature_flags.backend.facade.config import ConfigFormatError, detect_config_format
from products.feature_flags.backend.types import FlagProperty, PropertyFilterType


def referenced_cohort_ids(filters: Mapping[str, Any] | None) -> set[int]:
    """Cohort ids the release conditions of a v1 document reference.

    Raises ``ConfigFormatError`` for any other config format. A ``value`` that is not an
    integer is skipped, the same tolerance every producer already applied; a consumer
    that needs strictness resolves the ids itself.
    """
    cohort_ids: set[int] = set()
    for prop in _v1_properties(filters, PropertyFilterType.COHORT):
        value = prop.get("value")
        if value is None:
            continue
        try:
            cohort_ids.add(int(value))
        except (TypeError, ValueError):
            continue
    return cohort_ids


def flag_dependency_properties(filters: Mapping[str, Any] | None) -> list[FlagProperty]:
    """The ``type == "flag"`` properties in the release conditions of a v1 document.

    Raises ``ConfigFormatError`` for any other config format. The returned dicts are the
    caller's own objects, so a consumer can rewrite them in place. ``key`` holds the
    referenced flag's id or key; the consumer decides which it accepts.
    """
    return _v1_properties(filters, PropertyFilterType.FLAG)


def _v1_properties(filters: Mapping[str, Any] | None, property_type: PropertyFilterType) -> list[FlagProperty]:
    config_format = detect_config_format(filters)
    if config_format.kind != "v1":
        raise ConfigFormatError(config_format)
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
