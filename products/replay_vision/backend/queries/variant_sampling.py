"""Per-variant sampling rates for experiment scanners.

One rate per scanner samples variants proportionally to rollout, so a 90/10 split at a 10% rate
yields ~90 control observations per 10 test. Balanced sampling instead spends the same total
budget about evenly across the watched variants: each variant's rate is `r / (k · share)`, capped
at 1, with a capped variant's unspent budget redistributed to the others so a small variant can
never shrink the total.

Rates are recomputed from the live rollout shares on every sweep, estimate, and backfill tick, so
a mid-experiment rollout change adjusts them on the next tick. The plan cannot create sessions a
small variant does not have: a capped variant is sampled whole and stays thin.
"""

from collections.abc import Sequence

from rest_framework.exceptions import ValidationError

from posthog.dataclasses import frozen
from posthog.models.team import Team


@frozen
class VariantSamplingPlan:
    # Hash-threshold rate per watched variant, each in 0..1.
    rates: dict[str, float]
    # Each watched variant's share of the watched population (normalized over the watched set).
    population_shares: dict[str, float]

    @property
    def effective_rate(self) -> float:
        """The fraction of the watched population the plan samples overall: the scanner's own
        rate until a cap binds, then less budget than asked finds sessions to spend itself on."""
        return sum(self.population_shares[variant] * rate for variant, rate in self.rates.items())


def plan_variant_sampling(
    sampling_rate: float, rollout_shares: dict[str, float], selected: Sequence[str] | None
) -> VariantSamplingPlan | None:
    """The per-variant plan, or None when balancing changes nothing (one watched variant or no shares).

    Water-filling: every uncapped variant gets an equal slice of the remaining budget; a variant
    whose whole population fits inside its slice is sampled at 1 and frees the rest of its slice.
    """
    selected_keys = [key for key in (selected if selected is not None else rollout_shares) if key in rollout_shares]
    if len(selected_keys) <= 1:
        return None
    raw = {key: max(0.0, float(rollout_shares[key])) for key in selected_keys}
    total = sum(raw.values())
    population_shares = (
        {key: value / total for key, value in raw.items()}
        if total > 0
        else {key: 1.0 / len(selected_keys) for key in selected_keys}
    )

    budget = max(0.0, min(1.0, sampling_rate))
    rates: dict[str, float] = {}
    remaining = set(selected_keys)
    while remaining:
        slice_per_variant = budget / len(remaining)
        capped = {key for key in remaining if population_shares[key] <= slice_per_variant}
        if not capped:
            for key in remaining:
                rates[key] = slice_per_variant / population_shares[key]
            break
        for key in capped:
            rates[key] = 1.0
            budget -= population_shares[key]
        budget = max(0.0, budget)
        remaining -= capped
    return VariantSamplingPlan(rates=rates, population_shares=population_shares)


def variant_sampling_plan_for_scope(
    team: Team, *, scope: dict | None, scanner_config: dict | None, sampling_rate: float
) -> VariantSamplingPlan | None:
    """The plan for a scanner (or frozen snapshot) scope, from the flag's live rollout shares.

    None when the scanner watches no experiment, balancing is off, only one variant is watched, or
    the shares can't be read (the caller then falls back to plain sampling; the scan itself stays
    the loud path for an unresolvable experiment).
    """
    experiment_id = (scope or {}).get("experiment_id")
    if experiment_id is None:
        return None
    config = scanner_config if isinstance(scanner_config, dict) else {}
    if config.get("balance_variants") is False:
        return None
    # Deferred: the experiments replay facade pulls in the recordings query modules, which circle
    # back into this package's importers.
    from products.experiments.backend.facade.replay import variant_rollout_shares  # noqa: PLC0415

    try:
        shares = variant_rollout_shares(team, experiment_id=experiment_id)
    except ValidationError:
        return None
    assert scope is not None
    return plan_variant_sampling(sampling_rate, shares, scope.get("variants"))
