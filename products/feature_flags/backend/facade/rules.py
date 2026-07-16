"""The experiment-rule view of a feature flag's config.

A v1 flag hosting an experiment is a single implicit experiment rule: the flag-wide
``multivariate`` variants, the first release group's rollout percentage, and the
flag-level holdout/aggregation settings. This module derives that normalized rule
config from today's ``filters`` format; when the rule-level flag model lands, the
derivation becomes a read off the rule itself and consumers are untouched.

The DTO stays deliberately minimal while the rule-level model is being designed:
no seed handling, no reason mapping. It is the seam for the format swap — do not
grow it into a general flag-read layer (``flag.variants`` and friends remain the
right interface for plain reads).

Deliberately free of Django/DRF imports (same reason as ``facade.filters``):
consumer model modules import this at module level.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class HoldoutRef:
    id: int
    exclusion_percentage: float | None


@dataclass(frozen=True)
class ExperimentRuleConfig:
    variants: list[dict]  # v1 variant dicts: {key, rollout_percentage, name?}
    rollout_percentage: float | None
    assign_variant_by: int | None  # v1: the flag's aggregation_group_type_index (None = persons)
    holdout: HoldoutRef | None


def experiment_rule_from_filters(current_filters: dict) -> ExperimentRuleConfig:
    """Derive the implicit experiment rule from a v1 flag's ``filters`` dict."""
    groups = current_filters.get("groups") or []
    holdout = current_filters.get("holdout") or None
    return ExperimentRuleConfig(
        # Explicit nulls occur in real flag data (see FeatureFlag.variants) — coalesce them too.
        variants=(current_filters.get("multivariate") or {}).get("variants") or [],
        rollout_percentage=groups[0].get("rollout_percentage") if groups else None,
        assign_variant_by=current_filters.get("aggregation_group_type_index"),
        holdout=HoldoutRef(id=holdout["id"], exclusion_percentage=holdout.get("exclusion_percentage"))
        if holdout
        else None,
    )
