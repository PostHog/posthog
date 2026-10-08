"""Per-variant sampling rates for experiment scanners.

One rate per scanner samples variants proportionally to their traffic, so a 90/10 population at a
10% rate yields ~90 control observations per 10 test. Balanced sampling instead spends the same
total budget about evenly across the watched variants: each variant's rate is `r / (k · share)`,
capped at 1, with a capped variant's unspent budget redistributed to the others so a small variant
can never shrink the total.

Shares come from counting the actually exposed persons per variant over the experiment window, not
from the flag's rollout percentages: a rollout that changed mid-experiment leaves the window's mix
far from the current percentages, and rates planned against the wrong mix overspend the budget.
The counts are recomputed on every sweep, estimate, and backfill tick, so a traffic shift adjusts
them on the next tick. The plan cannot create sessions a small variant does not have: a capped
variant is sampled whole and stays thin.
"""

from collections.abc import Sequence

import structlog
from rest_framework.exceptions import ValidationError

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import ClickHouseUser
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.models.team import Team
from posthog.models.user import User

from products.access_control.backend.facade.user_access_control import UserAccessControlError
from products.replay_vision.backend.models.replay_scanner import ScannerType

logger = structlog.get_logger(__name__)

# The counts aggregate scans the same exposure window the candidate query joins each tick, so it
# gets a matching but tighter budget: a plan that can't be computed falls back to plain sampling
# rather than holding the tick.
_EXPOSURE_COUNTS_MAX_EXECUTION_SECONDS = 60


@frozen
class VariantSamplingPlan:
    # Hash-threshold rate per watched variant, each in 0..1.
    rates: dict[str, float]
    # Each watched variant's share of the watched exposed population (normalized over the watched set).
    population_shares: dict[str, float]

    @property
    def effective_rate(self) -> float:
        """The fraction of the watched population the plan samples overall.

        Redistribution spends the whole budget (shares sum to 1 and the rate is clamped to 0..1),
        so this always equals the scanner's own rate — which is why the volume estimate can project
        with the plain rate whether balancing is on or off. Kept as the checked statement of that
        invariant rather than re-derived at call sites.
        """
        return sum(self.population_shares[variant] * rate for variant, rate in self.rates.items())


def plan_variant_sampling(
    sampling_rate: float, exposure_weights: dict[str, float], selected: Sequence[str] | None
) -> VariantSamplingPlan | None:
    """The per-variant plan, or None when balancing changes nothing (one watched variant or no weights).

    ``exposure_weights`` is each variant's exposed-population size in any consistent unit (person
    counts in production); it is normalized here. Water-filling: every uncapped variant gets an
    equal slice of the remaining budget; a variant whose whole population fits inside its slice is
    sampled at 1 and frees the rest of its slice.
    """
    selected_keys = [key for key in (selected if selected is not None else exposure_weights) if key in exposure_weights]
    if len(selected_keys) <= 1:
        return None
    raw = {key: max(0.0, float(exposure_weights[key])) for key in selected_keys}
    total = sum(raw.values())
    population_shares = (
        {key: value / total for key, value in raw.items()}
        if total > 0
        else {key: 1.0 / len(selected_keys) for key in selected_keys}
    )

    budget = max(0.0, min(1.0, sampling_rate))
    if budget <= 0:
        # Rate 0 means paused; the cap-at-1 arm below must not turn "no budget" into
        # "sample a zero-share variant whole".
        return VariantSamplingPlan(rates=dict.fromkeys(selected_keys, 0.0), population_shares=population_shares)
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
    team: Team,
    *,
    scanner_type: str,
    scope: dict | None,
    scanner_config: dict | None,
    sampling_rate: float,
    user: User | None,
    scanner_id: str | None = None,
) -> VariantSamplingPlan | None:
    """The plan for an experiment scanner (or its frozen snapshot), from the window's exposure counts.

    None when the scanner is not the experiment type (legacy column-targeted scanners keep plain
    sampling — flipping their behavior on deploy is not this function's call), balancing is off,
    only one variant is watched, or the population can't be counted (the caller then falls back to
    plain sampling; the scan itself stays the loud path for an unresolvable experiment).
    """
    if scanner_type != ScannerType.EXPERIMENT:
        return None
    experiment_id = (scope or {}).get("experiment_id")
    if experiment_id is None:
        return None
    config = scanner_config if isinstance(scanner_config, dict) else {}
    if config.get("balance_variants") is False:
        return None
    assert scope is not None
    # A legacy column scope narrows with the singular `variant`; treating it as "every variant"
    # would balance a population the exposure join has already narrowed to one arm.
    selected = scope.get("variants") or ([scope["variant"]] if scope.get("variant") else None)
    counts = _variant_exposure_counts(
        team, experiment_id=experiment_id, selected=selected, user=user, scanner_id=scanner_id
    )
    if counts is None:
        return None
    return plan_variant_sampling(sampling_rate, counts, selected)


def _variant_exposure_counts(
    team: Team, *, experiment_id: int, selected: Sequence[str] | None, user: User | None, scanner_id: str | None
) -> dict[str, float] | None:
    """Exposed persons per watched variant over the experiment window, or None when uncountable.

    A watched variant with no exposures counts as 0, so a variant ramped down mid-experiment keeps
    its real (small) weight instead of the rollout percentage's fiction. Fails open: a plan is an
    optimization of how the budget is spent, so a failed count must cost this tick balance, not
    candidates.
    """
    # Deferred: the experiments replay facade pulls in the recordings query modules, which circle
    # back into this package's importers.
    from products.experiments.backend.facade.replay import (  # noqa: PLC0415
        exposed_persons_select,
        resolve_exposure_linkage,
        validate_experiment_exposure_access,
    )

    try:
        # The same object-level gate every other exposure read runs, as the same principal the
        # candidate query authorizes; a denied or missing principal costs balance, not candidates.
        validate_experiment_exposure_access(team, user, experiment_id)
    except UserAccessControlError:
        return None
    try:
        linkage = resolve_exposure_linkage(
            team, experiment_id=experiment_id, variants=list(selected) if selected is not None else None
        )
    except ValidationError:
        return None
    counts_query = ast.SelectQuery(
        select=[
            ast.Field(chain=["variant"]),
            ast.Alias(
                alias="exposed", expr=ast.Call(name="count", distinct=True, args=[ast.Field(chain=["person_id"])])
            ),
        ],
        select_from=ast.JoinExpr(table=exposed_persons_select(linkage, include_multiple_variant=False)),
        group_by=[ast.Field(chain=["variant"])],
    )
    try:
        with tags_context(product=Product.REPLAY_VISION, feature=Feature.ENRICHMENT, scanner_id=scanner_id):
            response = execute_hogql_query(
                counts_query,
                team=team,
                query_type="ReplayVisionVariantExposureCountsQuery",
                settings=HogQLGlobalSettings(max_execution_time=_EXPOSURE_COUNTS_MAX_EXECUTION_SECONDS),
                ch_user=ClickHouseUser.REPLAY_VISION,
            )
    except Exception:
        logger.warning(
            "replay_vision.variant_exposure_counts_failed", experiment_id=experiment_id, scanner_id=scanner_id
        )
        return None
    counts: dict[str, float] = dict.fromkeys(linkage.requested_variants, 0.0)
    for row in response.results or []:
        counts[str(row[0])] = float(row[1])
    return counts
