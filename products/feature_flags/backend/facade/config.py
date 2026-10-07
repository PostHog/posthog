"""Format detection and structural read DTOs for stored feature flag ``filters``.

A flag's ``filters`` JSON is one of two stored config formats. Config version 1 is the shape
every current reader knows: ``groups``, ``multivariate``, ``payloads`` and friends. Config
version 2 is a separate document selected by ``filters.version == 2``. One document is
entirely v1 or entirely v2. ``FeatureFlag.version``, the row's concurrency counter, is
unrelated to ``filters.version``.

Detection follows the Feature Flag Rules v2 contract: an absent ``version`` or a number that
equals 1 selects v1, a number that equals 2 selects v2, and everything else is unsupported.
A JSON string or boolean never selects a version, and a stored value that is not an object
(a list, say) is unsupported outright. An unsupported document is never read as v1, so a
reader with only a v1 branch checks the format before it touches any v1 key.

The v2 DTOs are structural reads of a stored document. They carry the fields later consumers
route on (return type, ordered rule identities and values, experiment identity, and the cohort
and flag targeting predicates) and nothing else. The full v2 schema lives in the contract; do not
grow this module into a second copy of it.

Deliberately free of Django/DRF imports (same reason as ``facade.filters``): consumer model
modules import this at module level.

``decode_config`` is the read entry point for a reader that handles more than one format: it
returns one arm per format, and ``facade.references`` reads the cohorts and flags each arm names.
"""

from collections.abc import Mapping
from typing import Any, Literal, get_args

from posthog.dataclasses import frozen

from products.feature_flags.backend.types import PropertyFilterType

ConfigFormatKind = Literal["v1", "v2", "unsupported"]
FlagReturnType = Literal["boolean", "string", "number", "object"]
RuleType = Literal["targeted_release", "percentage_rollout", "experiment"]
FlagValue = bool | str | int | float | dict[str, Any]

_REFERENCE_PREDICATE_TYPES = (PropertyFilterType.COHORT, PropertyFilterType.FLAG)


@frozen
class ConfigFormat:
    kind: ConfigFormatKind
    # The stored ``version`` as read, kept for diagnostics. None when absent or stored as null.
    raw_version: object


class ConfigFormatError(ValueError):
    """A reader received a stored config in a format it does not support."""

    def __init__(self, config_format: ConfigFormat) -> None:
        super().__init__(f"config format {config_format.kind!r} is not handled here")
        self.config_format = config_format


def detect_config_format(filters: object) -> ConfigFormat:
    if filters is None:
        return ConfigFormat(kind="v1", raw_version=None)
    if not isinstance(filters, Mapping):
        # A list, string or number is no config document at all, so it is never read as v1.
        return ConfigFormat(kind="unsupported", raw_version=None)
    if "version" not in filters:
        return ConfigFormat(kind="v1", raw_version=None)
    version = filters["version"]
    # bool is an int subclass, so ``True == 1`` would read as v1 without this guard.
    if isinstance(version, bool) or not isinstance(version, int | float):
        return ConfigFormat(kind="unsupported", raw_version=version)
    if version == 1:
        return ConfigFormat(kind="v1", raw_version=version)
    if version == 2:
        return ConfigFormat(kind="v2", raw_version=version)
    return ConfigFormat(kind="unsupported", raw_version=version)


def require_v1_config(filters: Mapping[str, Any] | None) -> None:
    """Raise ``ConfigFormatError`` unless ``filters`` is a config version 1 document."""
    config_format = detect_config_format(filters)
    if config_format.kind != "v1":
        raise ConfigFormatError(config_format)


def is_v1_config(filters: object) -> bool:
    """Whether a stored ``filters`` value is a config version 1 document (or null)."""
    return detect_config_format(filters).kind == "v1"


@frozen
class RuleV2:
    id: str
    # The targeting predicates that name a cohort or another flag, as stored.
    reference_predicates: tuple[Mapping[str, Any], ...] = ()
    rule_type: RuleType
    experiment_id: int | None
    # None for an experiment rule, whose values sit on its variants.
    value: FlagValue | None
    # An experiment rule's variant values in stored order, equal values included; empty for other rules.
    variant_values: tuple[FlagValue, ...] = ()

    def __post_init__(self) -> None:
        if self.rule_type not in get_args(RuleType):
            raise ValueError("Unsupported feature flag rule type")


@frozen
class ConfigV2:
    return_type: FlagReturnType
    default_value: FlagValue | None
    rules: tuple[RuleV2, ...]  # stored order, which is evaluation order
    aggregation_group_type_index: int | None

    def __post_init__(self) -> None:
        if self.return_type not in get_args(FlagReturnType):
            raise ValueError("Unsupported feature flag return type")


@frozen
class ConfigV1:
    # The stored document. Its v1 keys are read where they are needed; no v1 type is built here.
    filters: Mapping[str, Any]


@frozen
class UnsupportedConfig:
    config_format: ConfigFormat


DecodedConfig = ConfigV1 | ConfigV2 | UnsupportedConfig


def decode_config(document: object) -> DecodedConfig:
    """Read a stored ``filters`` document into the arm for its format.

    Decoding is structural. It does not run the writer's validator, so a decoded v2 document
    can still hold shapes the writer does not admit yet. A v2 document that the structural
    read cannot take decodes as unsupported, so no reader acts on part of it.
    """
    config_format = detect_config_format(document)
    if config_format.kind == "v1":
        return ConfigV1(filters=document if isinstance(document, Mapping) else {})
    if config_format.kind == "v2" and isinstance(document, Mapping):
        try:
            return parse_v2_config(document)
        except (KeyError, TypeError, ValueError, AttributeError):
            config_format = ConfigFormat(kind="unsupported", raw_version=config_format.raw_version)
    return UnsupportedConfig(config_format=config_format)


def parse_v2_config(filters: Mapping[str, Any]) -> ConfigV2:
    """Structural read of a stored v2 document.

    Checks the return type and rule types so consumers can dispatch on their closed sets.
    The write boundary owns full schema validation. Missing required keys raise KeyError
    instead of being coerced into a partial read.
    """
    config_format = detect_config_format(filters)
    if config_format.kind != "v2":
        raise ConfigFormatError(config_format)
    return ConfigV2(
        return_type=filters["return_type"],
        default_value=filters["default_value"],
        rules=tuple(_rule_v2(rule) for rule in filters["rules"]),
        aggregation_group_type_index=filters.get("aggregation_group_type_index"),
    )


def _rule_v2(rule: Mapping[str, Any]) -> RuleV2:
    rule_type = rule["rule_type"]
    return RuleV2(
        id=rule["id"],
        reference_predicates=tuple(
            prop for prop in rule["targeting"]["properties"] if prop.get("type") in _REFERENCE_PREDICATE_TYPES
        ),
        rule_type=rule_type,
        experiment_id=rule["experiment_id"] if rule_type == "experiment" else None,
        value=None if rule_type == "experiment" else rule["value"],
        variant_values=tuple(variant["value"] for variant in rule["variants"]) if rule_type == "experiment" else (),
    )
