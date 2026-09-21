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
guess about how two different predicates overlap. Within a population, percentage rules
partition people by their assignment hash: the same seed reuses the same hash, and
different seeds are modelled as independent dimensions. A rollout of ``p`` percent
includes the hash interval ``(0, p/100]``; 0 percent includes nobody, 100 percent
everybody. This is decision-level reasoning about who can reach which rule, not a second
evaluator, and it never claims an exact affected percentage.
"""

from collections.abc import Iterator
from fractions import Fraction
from itertools import product

from posthog.dataclasses import frozen

from products.feature_flags.backend.facade.config_validation import (
    Predicate,
    ValidatedConfig,
    ValidatedRule,
    ValidationLimits,
    validate_config,
)
from products.feature_flags.backend.facade.warnings import ManagementWarning

_Interval = tuple[Fraction, Fraction]  # (lo, hi] of the assignment hash in (0, 1]
_Box = dict[str, _Interval]  # per seed; an absent seed is unconstrained
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
    unchanged = set(current.rules) & set(proposed.rules)
    # A terminal miss serves the config default, so when the default is edited too those
    # outcomes differ because of the edit; only served rule values stay comparable.
    default_edited = current.default_value != proposed.default_value
    current_index = {rule.id: index for index, rule in enumerate(current.rules)}
    proposed_index = {rule.id: index for index, rule in enumerate(proposed.rules)}
    inversions: dict[tuple[str, str], int] = {}
    for population in {rule.predicates for rule in (*current.rules, *proposed.rules)}:
        before = _walk(current, population)
        after = _walk(proposed, population)
        for (box_before, outcome_before), (box_after, outcome_after) in product(before.settled, after.settled):
            earlier = current.rules[outcome_before.rule_index]
            later = proposed.rules[outcome_after.rule_index]
            values_differ = outcome_before.value != outcome_after.value
            values_comparable = not default_edited or (outcome_before.served and outcome_after.served)
            # Only a pair present in both configs has both indexes, so this covers "unchanged" too.
            order_flipped = (
                earlier in unchanged
                and later in unchanged
                and current_index[earlier.id] < current_index[later.id]
                and proposed_index[later.id] < proposed_index[earlier.id]
            )
            if (
                values_differ
                and values_comparable
                and order_flipped
                and (earlier.id, later.id) not in inversions
                and _intersects(box_before, box_after)
            ):
                inversions[(earlier.id, later.id)] = proposed_index[later.id]
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
        for lower_index in range(upper_index + 1, len(config.rules)):
            lower = config.rules[lower_index]
            if lower.value != upper.value:
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
        rule.rule_type == "percentage_rollout"
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
    value: bool | None  # the value served: the rule's, or the config default on a terminal miss
    served: bool  # True when the rule's own value was served, False for a terminal miss
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


def _walk(config: ValidatedConfig, population: frozenset[Predicate], *, until: int | None = None) -> _Walk:
    """Evaluate ``population`` through the rules before ``until`` (all rules when None).

    Stops at the first rule that does not provably apply to the population; the regions
    settled before it stay valid, the rest is unknown.
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
            if rule.rule_type == "targeted_release":
                settled.append((box, _Outcome(value=rule.value, served=True, rule_index=index)))
                continue
            assert rule.seed is not None and rule.rollout_percentage is not None
            lo, hi = box.get(rule.seed, _FULL)
            threshold = Fraction(rule.rollout_percentage) / 100
            if lo < min(hi, threshold):
                included = {**box, rule.seed: (lo, min(hi, threshold))}
                settled.append((included, _Outcome(value=rule.value, served=True, rule_index=index)))
            if max(lo, threshold) < hi:
                missed = {**box, rule.seed: (max(lo, threshold), hi)}
                if rule.on_rollout_miss == "return_default":
                    settled.append((missed, _Outcome(value=config.default_value, served=False, rule_index=index)))
                else:
                    next_open.append(missed)
        open_boxes = next_open
        if not open_boxes:
            return _Walk(settled=tuple(settled), closed_by=index)
    return _Walk(settled=tuple(settled), closed_by=None)


def _intersects(a: _Box, b: _Box) -> bool:
    # Every stored interval is non-empty, so only seeds constrained on both sides can be disjoint.
    for seed in a.keys() & b.keys():
        (a_lo, a_hi), (b_lo, b_hi) = a[seed], b[seed]
        if max(a_lo, b_lo) >= min(a_hi, b_hi):
            return False
    return True
