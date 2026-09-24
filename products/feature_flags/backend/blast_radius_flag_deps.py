from collections.abc import Callable
from typing import Any, Optional

from django.core.exceptions import ObjectDoesNotExist

from rest_framework.exceptions import ValidationError

from posthog.hogql import ast
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.property import property_to_expr
from posthog.hogql.visitor import TraversingVisitor, clone_expr

from posthog.models.filters import Filter
from posthog.models.property import Property, PropertyGroup, PropertyOperatorType, PropertyValidationError
from posthog.models.team.team import Team
from posthog.utils import safe_int

from products.feature_flags.backend.models.feature_flag import FeatureFlag

# A dependency chain deeper than this falls back to the neutral estimate. Cycles are rejected at
# save time, so the cap only guards against pathological chains blowing up the query.
MAX_DEPENDENCY_DEPTH = 5

# Dependencies are deduplicated per condition, so a real configuration expands a handful of
# flags. The budget bounds the Postgres lookups when a chain fans out anyway.
MAX_DEPENDENCY_NODES = 50

# The variant model re-embeds every earlier set's expression for each later set, so the emitted
# expression can outgrow the dependency budget. The budget is charged while the expression is
# built, so an oversized one is abandoned before it is cloned any further.
MAX_WEIGHT_AST_NODES = 10_000

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
    into a HogQL expression for the probability that the condition's dependencies hold for a
    person the plain filters already matched.

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

    A condition is an AND tree in the flag editor. An OR group is sized as an inclusive or of
    its branches, each carrying its own plain predicate, and treats the branches as independent,
    which over-counts when two branches reference the same flag.

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
        self._dependency_nodes = 0
        self._ast_nodes = 0

    def weight_expr(self, group: PropertyGroup) -> ast.Expr:
        """Probability that the condition's flag dependencies hold for a person its plain filters match."""
        try:
            return self._group_weight(group, assumed={}, inside_or=False)
        except _DependencyBudgetExceeded:
            # A partially expanded chain would give a misleading number, so the whole weight is neutral.
            return ast.Constant(value=NEUTRAL)

    def _group_weight(self, group: PropertyGroup, assumed: dict[str, bool | str], inside_or: bool) -> ast.Expr:
        """
        Inside an AND the query's WHERE clause already applies the plain properties, so only the
        flag dependencies weigh in. Inside an OR the WHERE clause only says that some branch
        matched, so each branch carries its own plain predicate.
        """
        if _is_or(group):
            misses = [_complement(self._branch_weight(value, assumed)) for value in group.values]
            return _complement(_product(misses))

        properties, or_groups = _and_members(group)
        flags = [(str(prop.key), prop.value) for prop in properties if prop.type == "flag"]
        plain = [prop for prop in properties if prop.type != "flag"]
        requested_by_flag = _merge_requested_values(flags)
        if requested_by_flag is None:
            return ast.Constant(value=0.0)

        factors: list[ast.Expr] = []
        if plain and inside_or:
            factors.append(self._predicate_factor(plain))
        if flags:
            factors.append(self._conjunction_expr(flags, depth=0, seen=frozenset(), assumed=assumed))
        child_assumed = {**assumed, **requested_by_flag}
        factors.extend(self._group_weight(or_group, child_assumed, inside_or=True) for or_group in or_groups)
        return _product(factors) if factors else ast.Constant(value=1.0)

    def _branch_weight(self, value: Property | PropertyGroup, assumed: dict[str, bool | str]) -> ast.Expr:
        if isinstance(value, PropertyGroup):
            return self._group_weight(value, assumed, inside_or=True)
        if value.type == "flag":
            return self._conjunction_expr([(str(value.key), value.value)], depth=0, seen=frozenset(), assumed=assumed)
        return self._predicate_factor([value])

    def _predicate_factor(self, properties: list[Property]) -> ast.Expr:
        predicate = property_to_expr(
            PropertyGroup(type=PropertyOperatorType.AND, values=properties), self.team, scope="person"
        )
        self._charge(predicate)
        return ast.Call(name="if", args=[predicate, ast.Constant(value=1.0), ast.Constant(value=0.0)])

    def _conjunction_expr(
        self, references: list[tuple[str, Any]], depth: int, seen: frozenset[int], assumed: dict[str, bool | str]
    ) -> ast.Expr:
        """
        Probability that every referenced flag evaluates to its requested value. `assumed` holds the
        values the enclosing conjunctions already fixed. The flags service evaluates a flag once, so
        a reference to one of those is settled by that value rather than drawn again.
        """
        requested_by_flag = _merge_requested_values(references)
        if requested_by_flag is None:
            return ast.Constant(value=0.0)

        factors: list[ast.Expr] = []
        for reference, requested in requested_by_flag.items():
            settled = _settled_by(assumed.get(reference), requested)
            if settled is None:
                return ast.Constant(value=0.0)
            if settled:
                continue
            factors.append(self._probability_expr(reference, requested, depth, seen, {**assumed, **requested_by_flag}))
        return _product(factors) if factors else ast.Constant(value=1.0)

    def _probability_expr(
        self, reference: str, requested: bool | str, depth: int, seen: frozenset[int], assumed: dict[str, bool | str]
    ) -> ast.Expr:
        self._dependency_nodes += 1
        if self._dependency_nodes > MAX_DEPENDENCY_NODES:
            raise _DependencyBudgetExceeded()
        if depth >= MAX_DEPENDENCY_DEPTH:
            return ast.Constant(value=NEUTRAL)

        flag = self._find_flag(reference)
        if flag is None or not flag.active:
            # A missing, deleted, or disabled dependency evaluates to false for everyone.
            return ast.Constant(value=1.0 if requested is False else 0.0)
        if flag.pk in seen or _has_unmodeled_evaluation(flag):
            return ast.Constant(value=NEUTRAL)

        admitted_by_set = self._admitted_probabilities(flag, depth, seen | {flag.pk}, assumed)
        if admitted_by_set is None:
            return ast.Constant(value=NEUTRAL)

        if isinstance(requested, bool):
            return _from_true_probability(requested, _running_max(admitted_by_set))
        return self._variant_probability(flag, admitted_by_set, requested)

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

    def _admitted_probabilities(
        self, flag: FeatureFlag, depth: int, seen: frozenset[int], assumed: dict[str, bool | str]
    ) -> Optional[list[ast.Expr]]:
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
                self._charge(targeting)
                factors.append(ast.Call(name="if", args=[targeting, ast.Constant(value=1.0), ast.Constant(value=0.0)]))
            nested = [(str(prop.get("key")), prop.get("value")) for prop in properties if prop.get("type") == "flag"]
            if nested:
                factors.append(self._conjunction_expr(nested, depth + 1, seen, assumed))

            admitted.append(_product(factors))
        return admitted

    def _variant_probability(self, flag: FeatureFlag, admitted_by_set: list[ast.Expr], variant: str) -> ast.Expr:
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
            current_max = ast.Call(name="greatest", args=[self._clone(previous_max), admitted])
            if share > 0:
                # The set wins only for the slice of the hash range above every earlier admitted set.
                won = ast.ArithmeticOperation(
                    op=ast.ArithmeticOperationOp.Sub, left=self._clone(current_max), right=self._clone(previous_max)
                )
                terms.append(_product([won, ast.Constant(value=share)]))
            previous_max = current_max
        if not terms:
            return ast.Constant(value=0.0)
        return _sum(terms)

    def _clone(self, expr: ast.Expr) -> ast.Expr:
        self._charge(expr)
        return clone_expr(expr)

    def _charge(self, expr: ast.Expr) -> None:
        self._ast_nodes += _count_nodes(expr)
        if self._ast_nodes > MAX_WEIGHT_AST_NODES:
            raise _DependencyBudgetExceeded()


def _is_or(group: PropertyGroup) -> bool:
    return group.type == PropertyOperatorType.OR and len(group.values) > 1


def _and_members(group: PropertyGroup) -> tuple[list[Property], list[PropertyGroup]]:
    """The properties an AND tree requires together, and the OR groups nested in it."""
    properties: list[Property] = []
    or_groups: list[PropertyGroup] = []
    for value in group.values:
        if isinstance(value, Property):
            properties.append(value)
        elif _is_or(value):
            or_groups.append(value)
        else:
            nested_properties, nested_or_groups = _and_members(value)
            properties.extend(nested_properties)
            or_groups.extend(nested_or_groups)
    return properties, or_groups


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


def _settled_by(assumed: bool | str | None, requested: bool | str) -> Optional[bool]:
    """
    Whether a value an enclosing conjunction already fixed decides this request: True when it
    implies it, None when it contradicts it, False when the request needs its own probability.
    """
    if assumed is None:
        return False
    if _merge_requested_values([("flag", assumed), ("flag", requested)]) is None:
        return None
    # A variant implies `true`; `true` does not imply a variant, which keeps its own share.
    return assumed == requested or (requested is True and isinstance(assumed, str))


class _NodeCounter(TraversingVisitor):
    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def visit(self, node: ast.AST | None) -> None:
        self.count += 1
        return super().visit(node)


def _count_nodes(expr: ast.Expr) -> int:
    counter = _NodeCounter()
    counter.visit(expr)
    return counter.count


def _from_true_probability(requested: bool, true_probability: ast.Expr) -> ast.Expr:
    if requested:
        return true_probability
    return _complement(true_probability)


def _complement(probability: ast.Expr) -> ast.Expr:
    return ast.ArithmeticOperation(op=ast.ArithmeticOperationOp.Sub, left=ast.Constant(value=1.0), right=probability)


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
