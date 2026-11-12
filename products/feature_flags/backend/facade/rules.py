"""The experiment-rule view of a feature flag's config.

A v1 flag hosting an experiment is a single implicit experiment rule: the flag-wide
``multivariate`` variants, the first release group's rollout percentage, and the
flag-level holdout/aggregation settings. This module derives that normalized rule
config from the v1 ``filters`` format behind a format check, so a document in another
config format is never read as v1.

A config version 2 flag holds its experiment rules explicitly. ``experiment_rule_snapshot``
cuts one of them out of the document with the flag context around it, and
``experiment_rule_from_snapshot`` reads a snapshot into the same normalized rule config.
A consumer that must not follow later edits of the flag keeps the snapshot.

The DTO stays deliberately minimal: no seed handling, no reason mapping. It is the
seam between the two formats — do not grow it into a general flag-read layer
(``flag.variants`` and friends remain the right interface for plain reads).

Deliberately free of Django/DRF imports (same reason as ``facade.filters``):
consumer model modules import this at module level.
"""

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from products.feature_flags.backend.facade.config import ConfigFormatError, detect_config_format

EXPERIMENT_RULE_TYPE = "experiment"


@dataclass(frozen=True)
class HoldoutRef:
    # None for a holdout that is local to a config version 2 rule, which names no shared holdout.
    id: int | None
    exclusion_percentage: float | None


@dataclass(frozen=True)
class ExperimentRuleConfig:
    variants: list[dict]  # v1 variant dicts: {key, rollout_percentage, name?}
    rollout_percentage: float | None
    assign_variant_by: int | None  # the flag's aggregation_group_type_index (None = persons)
    holdout: HoldoutRef | None
    # The config version 2 rule this was read from. None for a v1 flag, whose document is the one implicit rule.
    rule_id: str | None = None
    # The flag's key when the rule was read, which a snapshot keeps after a rename. None for a v1 flag.
    flag_key: str | None = None


class ExperimentRuleError(ValueError):
    """A config version 2 document or a rule snapshot does not hold the experiment rule a reader asked for."""


def experiment_rule_from_filters(current_filters: dict) -> ExperimentRuleConfig:
    """Derive the implicit experiment rule from a flag's ``filters`` dict.

    Only config version 1 carries an implicit rule. Any other format raises
    ``ConfigFormatError`` before any v1 key is read. Legacy filters can carry stray
    ``version`` keys, so an unsupported discriminator does not imply a v2 shape.
    """
    config_format = detect_config_format(current_filters)
    if config_format.kind != "v1":
        raise ConfigFormatError(config_format)
    return _v1_experiment_rule(current_filters)


def _v1_experiment_rule(current_filters: dict) -> ExperimentRuleConfig:
    """Derive the implicit experiment rule from a v1 ``filters`` dict.

    Tolerant of legacy null/partial shapes: an explicit null ``multivariate`` reads as no
    variants, and a holdout without an ``id`` reads as no holdout.
    """
    groups = current_filters.get("groups") or []
    holdout = current_filters.get("holdout") or {}
    holdout_id = holdout.get("id")
    return ExperimentRuleConfig(
        # Explicit nulls occur in real flag data (see FeatureFlag.variants) — coalesce them too.
        variants=(current_filters.get("multivariate") or {}).get("variants") or [],
        rollout_percentage=groups[0].get("rollout_percentage") if groups else None,
        assign_variant_by=current_filters.get("aggregation_group_type_index"),
        holdout=HoldoutRef(id=holdout_id, exclusion_percentage=holdout.get("exclusion_percentage"))
        if holdout_id
        else None,
    )


def experiment_rule_ids(current_filters: Mapping[str, Any]) -> list[str]:
    """The IDs of the experiment rules in a config version 2 document, in evaluation order.

    Any other format raises ``ConfigFormatError``: a v1 document has one implicit rule and no rule IDs.
    """
    rule_ids = (rule.get("id") for rule in _v2_rules(current_filters) if rule.get("rule_type") == EXPERIMENT_RULE_TYPE)
    return [rule_id for rule_id in rule_ids if isinstance(rule_id, str)]


def experiment_rule_snapshot(
    current_filters: Mapping[str, Any], rule_id: str, *, flag_id: int, flag_key: str, flag_version: int | None
) -> dict[str, Any]:
    """One experiment rule of a config version 2 document, with the flag context an analysis needs.

    The result is plain JSON: the rule as stored, and the flag's identity, row version, return type,
    default value and aggregation. ``experiment_rule_from_snapshot`` reads it back, so a reader can keep
    the snapshot and stay independent of later edits to the flag. The rule holds its seed, as the stored
    document does, so a snapshot must not reach an evaluation response or an event.

    Raises ``ExperimentRuleError`` when the document has no experiment rule with this ID, and
    ``ConfigFormatError`` when the document is not config version 2.
    """
    rule = next((rule for rule in _v2_rules(current_filters) if same_rule_id(rule.get("id"), rule_id)), None)
    if rule is None:
        raise ExperimentRuleError(f"The feature flag {flag_key} has no rule with the ID {rule_id}")
    if rule.get("rule_type") != EXPERIMENT_RULE_TYPE:
        raise ExperimentRuleError(f"The rule {rule_id} of the feature flag {flag_key} is not an experiment rule")
    snapshot = {
        "flag": {
            "id": flag_id,
            "key": flag_key,
            "version": flag_version,
            "return_type": current_filters.get("return_type"),
            "default_value": deepcopy(current_filters.get("default_value")),
            "aggregation_group_type_index": current_filters.get("aggregation_group_type_index"),
        },
        "rule": deepcopy(dict(rule)),
    }
    # Reading it back proves that every later reader can.
    experiment_rule_from_snapshot(snapshot)
    return snapshot


def experiment_rule_from_snapshot(snapshot: object) -> ExperimentRuleConfig:
    """The normalized rule config of an ``experiment_rule_snapshot``.

    Raises ``ExperimentRuleError`` for a snapshot it cannot read in full. It never fills a gap from a
    default, because the reader would then analyse a rule that was not the one evaluated.
    """
    if not isinstance(snapshot, Mapping):
        raise ExperimentRuleError("The experiment rule snapshot is not an object")
    flag, rule = snapshot.get("flag"), snapshot.get("rule")
    if not isinstance(flag, Mapping) or not isinstance(rule, Mapping):
        raise ExperimentRuleError("The experiment rule snapshot has no flag or no rule")
    rule_id = rule.get("id")
    if not isinstance(rule_id, str) or not rule_id or rule.get("rule_type") != EXPERIMENT_RULE_TYPE:
        raise ExperimentRuleError("The experiment rule snapshot does not hold an experiment rule")
    flag_key = flag.get("key")
    if not isinstance(flag_key, str) or not flag_key:
        raise ExperimentRuleError(f"The snapshot of the experiment rule {rule_id} has no flag key")
    variants = rule.get("variants")
    if not isinstance(variants, list) or len(variants) < 2:
        raise ExperimentRuleError(f"The experiment rule {rule_id} has fewer than two variants")
    aggregation = flag.get("aggregation_group_type_index")
    if aggregation is not None and not _is_integer(aggregation):
        raise ExperimentRuleError(f"The experiment rule {rule_id} has an aggregation that is not a group type index")
    rollout_percentage = rule.get("rollout_percentage")
    if not _is_number(rollout_percentage):
        raise ExperimentRuleError(f"The experiment rule {rule_id} has no rollout percentage")
    return ExperimentRuleConfig(
        variants=[_v1_variant(variant, rule_id) for variant in variants],
        rollout_percentage=rollout_percentage,
        assign_variant_by=aggregation,
        holdout=_rule_local_holdout(rule.get("holdout"), rule_id),
        rule_id=rule_id,
        flag_key=flag_key,
    )


def same_rule_id(stored: object, wanted: object) -> bool:
    """Whether two rule IDs name one rule. A rule ID is a UUID, and a caller can hold it in another spelling
    than the document stores."""
    try:
        return UUID(str(stored)) == UUID(str(wanted))
    except ValueError:
        return False


def _v2_rules(current_filters: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    config_format = detect_config_format(current_filters)
    if config_format.kind != "v2":
        raise ConfigFormatError(config_format)
    rules = current_filters.get("rules")
    if not isinstance(rules, list) or not all(isinstance(rule, Mapping) for rule in rules):
        raise ExperimentRuleError("The feature flag config has no list of rules")
    return rules


def _v1_variant(variant: object, rule_id: str) -> dict:
    """A rule variant as a v1 variant dict. A variant's weight is its share of the subjects the rule
    enrolls, which is what a v1 variant's rollout percentage is."""
    key = variant.get("key") if isinstance(variant, Mapping) else None
    weight = variant.get("weight") if isinstance(variant, Mapping) else None
    if not isinstance(key, str) or not key or not _is_number(weight):
        raise ExperimentRuleError(f"The experiment rule {rule_id} has a variant without a key or a weight")
    return {"key": key, "rollout_percentage": weight}


def _rule_local_holdout(holdout: object, rule_id: str) -> HoldoutRef | None:
    if holdout is None:
        return None
    exclusion_percentage = holdout.get("exclusion_percentage") if isinstance(holdout, Mapping) else None
    if not _is_number(exclusion_percentage):
        raise ExperimentRuleError(f"The experiment rule {rule_id} has a holdout without an exclusion percentage")
    return HoldoutRef(id=None, exclusion_percentage=exclusion_percentage)


def _is_number(value: object) -> bool:
    # bool is an int subclass, and a JSON true is no percentage.
    return isinstance(value, int | float) and not isinstance(value, bool)


def _is_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)
