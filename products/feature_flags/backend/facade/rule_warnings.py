"""Rule warning detectors for validated config version 2 documents.

``review_config`` is the dormant entrypoint a later writer calls after resolving a request
into a complete candidate: it validates the candidate, then reports the three
configuration warnings (``UNREACHABLE_LOWER_RULE``, ``ROLLOUT_MISS_CAN_ENTER_LOWER_RULE``
and, given the stored config, ``RULE_ORDER_CHANGES_TRAFFIC``) as the existing
``ManagementWarning`` DTO. Warnings never make an invalid document acceptable: validation
raises first. The lifecycle codes (``ASSIGNMENT_RESET_CHANGES_TRAFFIC``,
``CONCLUSION_EXPANDS_POPULATION``) belong to the operation previews that own those
operations and are not detected here.

Every detector reasons over one *population*: the people who satisfy a rule's whole
predicate set. A rule provably applies to that population when its own predicate set is
a subset (rules AND their properties, so fewer predicates means a wider audience); any
other relation is inconclusive and stops the walk, so a warning is never derived from a
guess about how two different predicates overlap. Within a population, randomized rules
partition people by their hashes: the same seed reuses the same hash, and each distinct
hash (a rollout, variant or holdout hash of a seed) is an independent dimension. A rollout
of ``p`` percent includes the hash interval ``(0, p/100]``; 0 percent includes nobody, 100
percent everybody. An experiment rule without an experiment returns the default while
paused, then to its holdout share, then splits its enrolled share across its variants by
cumulative weight. This is decision-level reasoning about who can reach which rule, not a
second evaluator, and it never claims an exact affected percentage.
"""

from collections.abc import Iterator
from decimal import Decimal
from fractions import Fraction

from posthog.dataclasses import frozen

from products.feature_flags.backend.facade.config_validation import (
    Predicate,
    ValidatedConfig,
    ValidatedRule,
    ValidationLimits,
    validate_config,
)
from products.feature_flags.backend.facade.warnings import ManagementWarning

_Interval = tuple[Fraction, Fraction]  # (lo, hi] of a hash in (0, 1]
_Dimension = tuple[str, str]  # (hash use, seed)
_Box = dict[_Dimension, _Interval]  # an absent dimension is unconstrained
_FULL: _Interval = (Fraction(0), Fraction(1))


@frozen
class ConfigReview:
    config: ValidatedConfig
    warnings: tuple[ManagementWarning, ...]


def review_config(
    document: object, *, limits: ValidationLimits, current: ValidatedConfig | None = None
) -> ConfigReview:
    """Validate a complete candidate and report its configuration warnings.

    ``current`` is the stored config the candidate replaces; without it no reorder
    comparison is possible and no reorder warning is claimed.
    """
    config = validate_config(document, limits=limits)
    warnings = config_warnings(config)
    if current is not None:
        warnings += reorder_warnings(current, config)
    return ConfigReview(config=config, warnings=warnings)


def config_warnings(config: ValidatedConfig) -> tuple[ManagementWarning, ...]:
    """Warnings a config carries on its own, in rule order and without duplicates."""
    return (*_unreachable_lower_rules(config), *_rollout_miss_extensions(config))


def reorder_warnings(current: ValidatedConfig, proposed: ValidatedConfig) -> tuple[ManagementWarning, ...]:
    """``RULE_ORDER_CHANGES_TRAFFIC`` for each inverted rule pair whose reorder provably changes a value.

    A pair is inverted when both rules exist unchanged in both configs and their relative
    order flipped. A change is proven when some population settles on different values in
    the two orders before any inconclusive rule. A rule that is only present on one side,
    or whose evaluated content changed, is an edit rather than a reorder, so a value change
    it causes is never attributed to the order.
    """
    current_index = {rule.id: index for index, rule in enumerate(current.rules)}
    proposed_index = {rule.id: index for index, rule in enumerate(proposed.rules)}
    unchanged = [rule.id for rule in set(current.rules) & set(proposed.rules)]
    later_by_earlier: dict[str, list[str]] = {}
    for earlier in unchanged:
        for later in unchanged:
            if current_index[earlier] < current_index[later] and proposed_index[later] < proposed_index[earlier]:
                later_by_earlier.setdefault(earlier, []).append(later)
    if not later_by_earlier:
        return ()
    # A terminal miss serves the config default, so when the default is edited too those
    # outcomes differ because of the edit; only served rule values stay comparable.
    default_edited = current.default_value != proposed.default_value
    inversions: dict[tuple[str, str], int] = {}
    for population in {rule.predicates for rule in (*current.rules, *proposed.rules)}:
        after_by_rule: dict[str, list[tuple[_Box, _Outcome]]] = {}
        for box, outcome in _walk(proposed, population, split_variants=True).settled:
            after_by_rule.setdefault(proposed.rules[outcome.rule_index].id, []).append((box, outcome))
        for box_before, outcome_before in _walk(current, population, split_variants=True).settled:
            earlier = current.rules[outcome_before.rule_index].id
            for later in later_by_earlier.get(earlier, ()):
                for box_after, outcome_after in after_by_rule.get(later, ()):
                    if (
                        outcome_before.value != outcome_after.value
                        and (not default_edited or (outcome_before.served and outcome_after.served))
                        and (earlier, later) not in inversions
                        and _intersects(box_before, box_after)
                    ):
                        inversions[(earlier, later)] = proposed_index[later]
    return tuple(
        ManagementWarning(
            code="RULE_ORDER_CHANGES_TRAFFIC",
            detail=f"Moving rule {later_id} above rule {earlier_id} changes the value some people receive.",
            attr=f"filters.rules[{index}]",
        )
        for (earlier_id, later_id), index in sorted(inversions.items(), key=lambda item: (item[1], item[0]))
    )


def _unreachable_lower_rules(config: ValidatedConfig) -> Iterator[ManagementWarning]:
    for index, rule in enumerate(config.rules[1:], start=1):
        walk = _walk(config, rule.predicates, until=index)
        if walk.closed_by is None:
            continue
        blocker = config.rules[walk.closed_by]
        yield ManagementWarning(
            code="UNREACHABLE_LOWER_RULE",
            detail=f"Rule {rule.id} is never reached because rule {blocker.id} already returns a value for everyone it targets.",
            attr=f"filters.rules[{index}]",
        )


def _rollout_miss_extensions(config: ValidatedConfig) -> Iterator[ManagementWarning]:
    walks: dict[frozenset[Predicate], _Walk] = {}
    for upper_index, upper in enumerate(config.rules):
        if not _continues_after_partial_miss(upper):
            continue
        assert upper.rollout_percentage is not None
        upper_values = {variant.value for variant in upper.variants} if upper.variants else {upper.value}
        for lower_index in range(upper_index + 1, len(config.rules)):
            lower = config.rules[lower_index]
            if lower.value not in upper_values:
                continue
            population = _overlap(upper, lower)
            if population is None:
                continue
            # A shorter walk settles a prefix of a longer one, so the filter is the `until` bound.
            if population not in walks:
                walks[population] = _walk(config, population)
            served_by = {
                outcome.rule_index
                for _, outcome in walks[population].settled
                if outcome.served and outcome.rule_index <= lower_index
            }
            # Both rules must serve somebody here: an upper rule that includes nobody has no rollout to extend.
            if not {upper_index, lower_index} <= served_by:
                continue
            percentage = f"{upper.rollout_percentage.normalize():f}"
            yield ManagementWarning(
                code="ROLLOUT_MISS_CAN_ENTER_LOWER_RULE",
                detail=(
                    f"Rule {upper.id} continues after a rollout miss, so rule {lower.id} serves the same value "
                    f"to people outside its {percentage}% rollout."
                ),
                attr=f"filters.rules[{lower_index}]",
            )


def _continues_after_partial_miss(rule: ValidatedRule) -> bool:
    return (
        not rule.paused
        and rule.on_rollout_miss == "continue"
        and rule.rollout_percentage is not None
        and 0 < rule.rollout_percentage < 100
    )


def _overlap(a: ValidatedRule, b: ValidatedRule) -> frozenset[Predicate] | None:
    """The narrower of two populations when one provably contains the other, else None."""
    if a.predicates <= b.predicates:
        return b.predicates
    if b.predicates <= a.predicates:
        return a.predicates
    return None


@frozen
class _Outcome:
    value: str | None  # canonical JSON of the value served: the rule's or a variant's, or the config default
    served: bool  # True when the rule served its own value, False when it returned the default
    rule_index: int


@frozen
class _Walk:
    settled: tuple[tuple[_Box, _Outcome], ...]  # regions with a definite outcome
    closed_by: int | None  # the rule after which nothing was left to evaluate


def _has_contradictory_presence_checks(population: frozenset[Predicate]) -> bool:
    presence: dict[str, set[bool]] = {}
    for predicate in population:
        if predicate.operator in ("is_set", "is_not_set"):
            presence.setdefault(predicate.key, set()).add((predicate.operator == "is_set") != predicate.negation)
    return any(len(states) > 1 for states in presence.values())


def _walk(
    config: ValidatedConfig,
    population: frozenset[Predicate],
    *,
    until: int | None = None,
    split_variants: bool = False,
) -> _Walk:
    """Evaluate ``population`` through the rules before ``until`` (all rules when None).

    Stops at the first rule that does not provably apply to the population; the regions
    settled before it stay valid, the rest is unknown. Only value comparisons need an
    experiment rule's served region split by variant; without ``split_variants`` it has value None.
    """
    if _has_contradictory_presence_checks(population):
        return _Walk(settled=(), closed_by=None)
    open_boxes: list[_Box] = [{}]
    settled: list[tuple[_Box, _Outcome]] = []
    for index, rule in enumerate(config.rules[:until]):
        if not rule.predicates <= population:
            # Inconclusive: who passes this rule is unknown, so nothing below it can be settled
            # and the regions that were still open must not be reported as reaching anything.
            return _Walk(settled=tuple(settled), closed_by=None)
        next_open: list[_Box] = []
        for box in open_boxes:
            if rule.paused:
                settled.append((box, _Outcome(value=config.default_value, served=False, rule_index=index)))
                continue
            if rule.rule_type == "targeted_release":
                settled.append((box, _Outcome(value=rule.value, served=True, rule_index=index)))
                continue
            assert rule.seed is not None and rule.rollout_percentage is not None
            enrolling: _Box | None = box
            if rule.holdout is not None:
                held = _split(box, ("holdout", rule.holdout.seed), _threshold(rule.holdout.exclusion_percentage))
                enrolling = held.above
                if held.below is not None:
                    settled.append((held.below, _Outcome(value=config.default_value, served=False, rule_index=index)))
            if enrolling is None:
                continue
            rollout = _split(enrolling, ("rollout", rule.seed), _threshold(rule.rollout_percentage))
            included, missed = rollout.below, rollout.above
            if included is not None:
                for region, value in _served_regions(included, rule, split_variants):
                    settled.append((region, _Outcome(value=value, served=True, rule_index=index)))
            if missed is not None:
                if rule.on_rollout_miss == "return_default":
                    settled.append((missed, _Outcome(value=config.default_value, served=False, rule_index=index)))
                else:
                    next_open.append(missed)
        open_boxes = next_open
        if not open_boxes:
            return _Walk(settled=tuple(settled), closed_by=index)
    return _Walk(settled=tuple(settled), closed_by=None)


def _threshold(percentage: Decimal) -> Fraction:
    return Fraction(percentage) / 100


@frozen
class _Halves:
    """The parts of a box at or below and above a threshold on one hash, None when empty."""

    below: _Box | None
    above: _Box | None


def _split(box: _Box, dimension: _Dimension, threshold: Fraction) -> _Halves:
    lo, hi = box.get(dimension, _FULL)
    return _Halves(
        below={**box, dimension: (lo, min(hi, threshold))} if lo < min(hi, threshold) else None,
        above={**box, dimension: (max(lo, threshold), hi)} if max(lo, threshold) < hi else None,
    )


def _served_regions(box: _Box, rule: ValidatedRule, split_variants: bool) -> Iterator[tuple[_Box, str | None]]:
    if not (split_variants and rule.variants):
        yield box, rule.value
        return
    assert rule.seed is not None
    rest: _Box | None = box
    boundary = Fraction(0)
    for variant in rule.variants:
        boundary += _threshold(variant.weight)
        if rest is None:
            return
        halves = _split(rest, ("variant", rule.seed), boundary)
        rest = halves.above
        if halves.below is not None:
            yield halves.below, variant.value


def _intersects(a: _Box, b: _Box) -> bool:
    # Every stored interval is non-empty, so only seeds constrained on both sides can be disjoint.
    for seed in a.keys() & b.keys():
        (a_lo, a_hi), (b_lo, b_hi) = a[seed], b[seed]
        if max(a_lo, b_lo) >= min(a_hi, b_hi):
            return False
    return True
