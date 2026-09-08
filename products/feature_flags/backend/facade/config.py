"""Format detection and structural read DTOs for stored feature flag ``filters``.

A flag's ``filters`` JSON is one of two stored config formats. Config version 1 is the shape
every current reader knows: ``groups``, ``multivariate``, ``payloads`` and friends. Config
version 2 is a separate document selected by ``filters.version == 2``. One document is
entirely v1 or entirely v2. ``FeatureFlag.version``, the row's concurrency counter, is
unrelated to ``filters.version``.

Detection follows the Feature Flag Rules v2 contract: an absent ``version`` or a number that
equals 1 selects v1, a number that equals 2 selects v2, and everything else is unsupported.
A JSON string or boolean never selects a version. An unsupported document is never read as
v1, so a reader with only a v1 arm checks the format before it touches any v1 key.

The v2 DTOs are structural reads of a stored document. They carry the fields later consumers
route on (return type, ordered rule identities, experiment identity) and nothing else. The
full v2 schema lives in the contract; do not grow this module into a second copy of it.

Deliberately free of Django/DRF imports (same reason as ``facade.filters``): consumer model
modules import this at module level.
"""

from collections.abc import Mapping
from typing import Any, Literal

from posthog.dataclasses import frozen

ConfigFormatKind = Literal["v1", "v2", "unsupported"]
FlagReturnType = Literal["boolean", "string", "number", "object"]
RuleType = Literal["targeted_release", "percentage_rollout", "experiment"]
FlagValue = bool | str | int | float | dict[str, Any]


@frozen
class ConfigFormat:
    kind: ConfigFormatKind
    # The stored ``version`` as read, kept for diagnostics. None when absent or stored as null.
    raw_version: object


class ConfigFormatError(ValueError):
    """A reader received a stored config in a format it has no arm for."""

    def __init__(self, config_format: ConfigFormat) -> None:
        super().__init__(
            f"config format {config_format.kind!r} (version={config_format.raw_version!r}) is not handled here"
        )
        self.config_format = config_format


def detect_config_format(filters: Mapping[str, Any] | None) -> ConfigFormat:
    if not filters or "version" not in filters:
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


@frozen
class ExperimentRuleIdentity:
    rule_id: str
    experiment_id: int


@frozen
class RuleV2:
    id: str
    rule_type: RuleType
    experiment: ExperimentRuleIdentity | None


@frozen
class ConfigV2:
    return_type: FlagReturnType
    default_value: FlagValue | None
    rules: tuple[RuleV2, ...]  # stored order, which is evaluation order
    aggregation_group_type_index: int | None


def parse_v2_config(filters: Mapping[str, Any]) -> ConfigV2:
    """Structural read of a stored v2 document.

    Validates nothing: the write boundary owns that. A document that reached storage without a
    required key fails here with a KeyError instead of being coerced into a partial read.
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
        rule_type=rule_type,
        experiment=ExperimentRuleIdentity(rule_id=rule["id"], experiment_id=rule["experiment_id"])
        if rule_type == "experiment"
        else None,
    )
