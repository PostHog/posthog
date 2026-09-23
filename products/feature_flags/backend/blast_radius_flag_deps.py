from collections.abc import Callable
from typing import Any, Optional

from posthog.hogql import ast
from posthog.hogql.property import property_to_expr
from posthog.hogql.visitor import clone_expr

from posthog.models.filters import Filter
from posthog.models.property import Property
from posthog.models.team.team import Team

from products.feature_flags.backend.models.feature_flag import FeatureFlag

# A dependency chain deeper than this falls back to the neutral estimate. Cycles are rejected at
# save time, so the cap only guards against pathological chains blowing up the query.
MAX_DEPENDENCY_DEPTH = 5

NEUTRAL = 1.0


class FlagDependencyEstimator:
    """
    Translates a flag-dependency filter (`type: "flag"`, `flag_evaluates_to`) into a HogQL
    expression for the probability that the dependency flag evaluates to the requested value
    for a person.

    Flag matching hashes the distinct_id, so a person-grained query cannot say whether one
    person is in a rollout. It can say how likely they are, which is what a sizing estimate
    needs: summing the probability over persons gives the expected number of matches.

    The model follows the flags service. Condition sets are checked in stored order and the
    first one whose targeting matches and whose rollout admits the person wins. Every set of a
    flag compares the same hash against its rollout, so a person targeted by several sets is
    admitted with probability max(rollout) rather than the sum. The winning set's pinned
    variant applies when it has one; otherwise the variant is a second, independent hash split
    by the variant rollouts.

    Not modeled, on purpose: hash key overrides (experience continuity), super conditions,
    holdout groups, and group-aggregated dependency flags. Those fall back to the neutral
    estimate, which is the pre-existing behavior of counting every person.
    """

    def __init__(self, team: Team, clean_condition: Callable[[Team, dict], Filter]):
        self.team = team
        # The caller's condition cleaner normalizes values and relative dates the same way for the
        # dependency flag's stored filters as for the condition being sized.
        self.clean_condition = clean_condition

    def probability_expr(self, flag_property: Property) -> ast.Expr:
        return self._probability_expr(flag_property, depth=0, seen=frozenset())

    def _probability_expr(self, flag_property: Property, depth: int, seen: frozenset[int]) -> ast.Expr:
        requested = _requested_value(flag_property.value)
        flag = self._find_flag(flag_property.key)
        if flag is None or not flag.active:
            # A missing, deleted, or disabled dependency evaluates to false for everyone.
            return _from_true_probability(requested, ast.Constant(value=0.0))
        if flag.pk in seen or depth >= MAX_DEPENDENCY_DEPTH:
            return ast.Constant(value=NEUTRAL)

        admitted_by_set = self._admitted_probabilities(flag, depth, seen | {flag.pk})
        if admitted_by_set is None:
            return ast.Constant(value=NEUTRAL)

        if isinstance(requested, bool):
            return _from_true_probability(requested, _running_max(admitted_by_set))
        return _variant_probability(flag, admitted_by_set, requested)

    def _find_flag(self, reference: str) -> Optional[FeatureFlag]:
        queryset = FeatureFlag.objects.filter(team__project_id=self.team.project_id, deleted=False)
        if reference.isdigit():
            return queryset.filter(pk=int(reference)).first()
        return queryset.filter(key=reference).first()

    def _admitted_probabilities(self, flag: FeatureFlag, depth: int, seen: frozenset[int]) -> Optional[list[ast.Expr]]:
        """
        One expression per condition set, in stored order: the probability that the set's targeting
        matches the person and its rollout admits them. None when a set cannot be sized per person.
        """
        admitted: list[ast.Expr] = []
        for condition in flag.conditions:
            if _is_group_aggregated(flag, condition):
                return None
            rollout = float(
                condition.get("rollout_percentage") if condition.get("rollout_percentage") is not None else 100
            )
            factors: list[ast.Expr] = [ast.Constant(value=rollout / 100)]

            properties = condition.get("properties") or []
            plain_properties = [prop for prop in properties if prop.get("type") != "flag"]
            if plain_properties:
                cleaned = self.clean_condition(self.team, {"properties": plain_properties})
                targeting = property_to_expr(cleaned.property_groups, self.team, scope="person")
                factors.append(ast.Call(name="if", args=[targeting, ast.Constant(value=1.0), ast.Constant(value=0.0)]))
            for prop in properties:
                if prop.get("type") == "flag":
                    nested = Property(key=str(prop.get("key")), type="flag", value=prop.get("value"))
                    factors.append(self._probability_expr(nested, depth + 1, seen))

            admitted.append(_product(factors))
        return admitted


def _from_true_probability(requested: bool | str, true_probability: ast.Expr) -> ast.Expr:
    if requested is True:
        return true_probability
    if requested is False:
        return ast.ArithmeticOperation(
            op=ast.ArithmeticOperationOp.Sub, left=ast.Constant(value=1.0), right=true_probability
        )
    # A variant of a flag that never evaluates true is never served.
    return ast.Constant(value=0.0)


def _variant_probability(flag: FeatureFlag, admitted_by_set: list[ast.Expr], variant: str) -> ast.Expr:
    variant_keys = {v.get("key") for v in flag.variants}
    share_by_hash = next(
        (float(v.get("rollout_percentage") or 0) / 100 for v in flag.variants if v.get("key") == variant), 0.0
    )

    terms: list[ast.Expr] = []
    previous_max: ast.Expr = ast.Constant(value=0.0)
    for condition, admitted in zip(flag.conditions, admitted_by_set):
        pinned = condition.get("variant")
        if pinned in variant_keys:
            share = 1.0 if pinned == variant else 0.0
        else:
            share = share_by_hash
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
    if isinstance(value, bool):
        return value
    text = str(value)
    if text.lower() == "true":
        return True
    if text.lower() == "false":
        return False
    return text


def _is_group_aggregated(flag: FeatureFlag, condition: dict) -> bool:
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
