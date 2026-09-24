from collections.abc import Callable
from typing import Any, Optional

from django.core.exceptions import ObjectDoesNotExist

from rest_framework.exceptions import ValidationError

from posthog.hogql import ast
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.property import property_to_expr
from posthog.hogql.visitor import clone_expr

from posthog.models.filters import Filter
from posthog.models.property import Property, PropertyValidationError
from posthog.models.team.team import Team
from posthog.utils import safe_int

from products.feature_flags.backend.models.feature_flag import FeatureFlag

# A dependency chain deeper than this falls back to the neutral estimate. Cycles are rejected at
# save time, so the cap only guards against pathological chains blowing up the query.
MAX_DEPENDENCY_DEPTH = 5

# Dependencies are deduplicated per condition, so a real configuration expands a handful of
# flags. The budget bounds the Postgres lookups and the query size when a chain fans out anyway.
MAX_DEPENDENCY_NODES = 50

# Probability used when a dependency cannot be sized per person: every person counts, which is
# what property_to_expr's neutral filter for flag properties already does.
NEUTRAL = 1.0

# Flag-level settings the flags service evaluates before, or instead of, the condition sets.
# The rollout model below does not apply to them.
_UNMODELED_FILTER_KEYS = ("holdout", "holdout_groups", "super_groups", "feature_enrollment", "early_exit")

# Errors that mean the dependency's stored targeting cannot be compiled. They describe that
# flag's configuration, not the caller's condition, so they must not surface as a 400.
_TARGETING_BUILD_ERRORS = (ValidationError, ExposedHogQLError, PropertyValidationError, ObjectDoesNotExist)


class _DependencyBudgetExceeded(Exception):
    pass


class FlagDependencyEstimator:
    """
    Translates the flag-dependency filters of a condition (`type: "flag"`, `flag_evaluates_to`)
    into a HogQL expression for the probability that every dependency flag evaluates to its
    requested value for a person.

    Flag matching hashes the distinct_id, so a person-grained query cannot say whether one
    person is in a rollout. It can say how likely they are, which is what a sizing estimate
    needs: summing the probability over persons gives the expected number of matches.

    The model follows the flags service. Condition sets are checked in stored order and the
    first one whose targeting matches and whose rollout admits the person wins. Every set of a
    flag compares the same hash against its rollout, so a person targeted by several sets is
    admitted with probability max(rollout) rather than the sum. The winning set's pinned
    variant applies when it has one; otherwise the variant is a second, independent hash split
    by the variant rollouts. A dependency is resolved by flag id only and a string value is a
    variant name, as the flags service does. The max over sets is exact when every non-rollout
    factor of a set is 0 or 1; a nested dependency inside a set makes it an approximation.

    Not modeled: holdouts, super conditions, feature enrollment, early exit and group-aggregated
    dependency flags, plus a dependency whose stored targeting cannot be compiled. Those fall
    back to the neutral estimate, which is the pre-existing behavior of counting every person.
    """

    def __init__(self, team: Team, clean_condition: Callable[[Team, dict], Filter]):
        self.team = team
        # Injected rather than imported: user_blast_radius imports this module, and its cleaner
        # must normalize the dependency's stored filters the same way as the condition being sized.
        self.clean_condition = clean_condition
        self._flags: dict[int, Optional[FeatureFlag]] = {}
        self._nodes = 0

    def weight_expr(self, flag_properties: list[Property]) -> ast.Expr:
        """Probability that every flag dependency in the condition evaluates to its requested value."""
        references = [(str(prop.key), prop.value) for prop in flag_properties]
        try:
            return self._conjunction_expr(references, depth=0, seen=frozenset())
        except _DependencyBudgetExceeded:
            # A partially expanded chain would give a misleading number, so the whole weight is neutral.
            return ast.Constant(value=NEUTRAL)

    def _conjunction_expr(self, references: list[tuple[str, Any]], depth: int, seen: frozenset[int]) -> ast.Expr:
        requested_by_flag = _merge_requested_values(references)
        if requested_by_flag is None:
            # The flags service evaluates a flag once, so contradictory requests never match.
            return ast.Constant(value=0.0)
        return _product(
            [
                self._probability_expr(reference, requested, depth, seen)
                for reference, requested in requested_by_flag.items()
            ]
        )

    def _probability_expr(self, reference: str, requested: bool | str, depth: int, seen: frozenset[int]) -> ast.Expr:
        self._nodes += 1
        if self._nodes > MAX_DEPENDENCY_NODES:
            raise _DependencyBudgetExceeded()
        if depth >= MAX_DEPENDENCY_DEPTH:
            return ast.Constant(value=NEUTRAL)

        flag = self._find_flag(reference)
        if flag is None or not flag.active:
            # A missing, deleted, or disabled dependency evaluates to false for everyone.
            return ast.Constant(value=1.0 if requested is False else 0.0)
        if flag.pk in seen or _has_unmodeled_evaluation(flag):
            return ast.Constant(value=NEUTRAL)

        admitted_by_set = self._admitted_probabilities(flag, depth, seen | {flag.pk})
        if admitted_by_set is None:
            return ast.Constant(value=NEUTRAL)

        if isinstance(requested, bool):
            return _from_true_probability(requested, _running_max(admitted_by_set))
        return _variant_probability(flag, admitted_by_set, requested)

    def _find_flag(self, reference: str) -> Optional[FeatureFlag]:
        # The flags service resolves a dependency by id only, so a key reference never matches.
        flag_id = safe_int(reference)
        if flag_id is None:
            return None
        if flag_id not in self._flags:
            self._flags[flag_id] = FeatureFlag.objects.filter(
                team__project_id=self.team.project_id, deleted=False, pk=flag_id
            ).first()
        return self._flags[flag_id]

    def _admitted_probabilities(self, flag: FeatureFlag, depth: int, seen: frozenset[int]) -> Optional[list[ast.Expr]]:
        """
        One expression per condition set, in stored order: the probability that the set's targeting
        matches the person and its rollout admits them. None when a set cannot be sized per person.
        """
        admitted: list[ast.Expr] = []
        for condition in flag.conditions:
            if _is_group_aggregated(flag, condition):
                return None
            rollout_percentage = condition.get("rollout_percentage")
            rollout = 1.0 if rollout_percentage is None else float(rollout_percentage) / 100
            factors: list[ast.Expr] = [ast.Constant(value=rollout)]

            properties = condition.get("properties") or []
            plain_properties = [prop for prop in properties if prop.get("type") != "flag"]
            if plain_properties:
                try:
                    cleaned = self.clean_condition(self.team, {"properties": plain_properties})
                    targeting = property_to_expr(cleaned.property_groups, self.team, scope="person")
                except _TARGETING_BUILD_ERRORS:
                    return None
                factors.append(ast.Call(name="if", args=[targeting, ast.Constant(value=1.0), ast.Constant(value=0.0)]))
            nested = [(str(prop.get("key")), prop.get("value")) for prop in properties if prop.get("type") == "flag"]
            if nested:
                factors.append(self._conjunction_expr(nested, depth + 1, seen))

            admitted.append(_product(factors))
        return admitted


def _merge_requested_values(references: list[tuple[str, Any]]) -> Optional[dict[str, bool | str]]:
    """
    The one value each dependency flag must evaluate to, keyed by reference. None when two
    filters on the same flag contradict each other. `true` matches any served variant, so it
    narrows to a variant requested alongside it.
    """
    merged: dict[str, bool | str] = {}
    for reference, value in references:
        requested = _requested_value(value)
        previous = merged.get(reference)
        if previous is None or previous == requested or (previous is True and requested is not False):
            merged[reference] = requested
        elif requested is True and previous is not False:
            continue
        else:
            return None
    return merged


def _from_true_probability(requested: bool, true_probability: ast.Expr) -> ast.Expr:
    if requested:
        return true_probability
    return ast.ArithmeticOperation(
        op=ast.ArithmeticOperationOp.Sub, left=ast.Constant(value=1.0), right=true_probability
    )


def _variant_probability(flag: FeatureFlag, admitted_by_set: list[ast.Expr], variant: str) -> ast.Expr:
    variant_keys = {v.get("key") for v in flag.variants}
    hashed_variant_share = next(
        (float(v.get("rollout_percentage") or 0) / 100 for v in flag.variants if v.get("key") == variant), 0.0
    )

    terms: list[ast.Expr] = []
    previous_max: ast.Expr = ast.Constant(value=0.0)
    for condition, admitted in zip(flag.conditions, admitted_by_set):
        pinned = condition.get("variant")
        if pinned in variant_keys:
            share = 1.0 if pinned == variant else 0.0
        else:
            share = hashed_variant_share
        # previous_max is reused in `won` below, so every use needs its own copy of the node.
        current_max = ast.Call(name="greatest", args=[clone_expr(previous_max), admitted])
        if share > 0:
            # The set wins only for the slice of the hash range above every earlier admitted set.
            won = ast.ArithmeticOperation(
                op=ast.ArithmeticOperationOp.Sub, left=clone_expr(current_max), right=clone_expr(previous_max)
            )
            terms.append(_product([won, ast.Constant(value=share)]))
        previous_max = current_max
    if not terms:
        return ast.Constant(value=0.0)
    return _sum(terms)


def _requested_value(value: Any) -> bool | str:
    # The flags service compares a string value against the served variant name only, so a
    # string "true" is a variant name, not the boolean.
    if isinstance(value, bool):
        return value
    return str(value)


def _has_unmodeled_evaluation(flag: FeatureFlag) -> bool:
    filters = flag.get_filters()
    return any(filters.get(key) for key in _UNMODELED_FILTER_KEYS)


def _is_group_aggregated(flag: FeatureFlag, condition: dict[str, Any]) -> bool:
    if "aggregation_group_type_index" in condition:
        return condition["aggregation_group_type_index"] is not None
    return flag.aggregation_group_type_index is not None


def _running_max(exprs: list[ast.Expr]) -> ast.Expr:
    result: ast.Expr = ast.Constant(value=0.0)
    for expr in exprs:
        result = ast.Call(name="greatest", args=[result, expr])
    return result


def _product(factors: list[ast.Expr]) -> ast.Expr:
    result = factors[0]
    for factor in factors[1:]:
        result = ast.ArithmeticOperation(op=ast.ArithmeticOperationOp.Mult, left=result, right=factor)
    return result


def _sum(terms: list[ast.Expr]) -> ast.Expr:
    result = terms[0]
    for term in terms[1:]:
        result = ast.ArithmeticOperation(op=ast.ArithmeticOperationOp.Add, left=result, right=term)
    return result
