from collections.abc import Callable
from typing import Any, Optional

from django.core.exceptions import ObjectDoesNotExist

from rest_framework.exceptions import ValidationError

from posthog.hogql import ast
from posthog.hogql.errors import (
    ExposedHogQLError,
    NotImplementedError as HogQLNotImplementedError,
)
from posthog.hogql.property import property_to_expr
from posthog.hogql.visitor import TraversingVisitor, clone_expr

from posthog.models.filters import Filter
from posthog.models.property import Property, PropertyGroup, PropertyOperatorType, PropertyValidationError
from posthog.models.team.team import Team
from posthog.utils import safe_int

from products.feature_flags.backend.facade.config import detect_config_format
from products.feature_flags.backend.facade.filters import EVALUATED_BEFORE_RELEASE_CONDITIONS
from products.feature_flags.backend.models.feature_flag import FeatureFlag

# Neither the flags service nor the save path limits how deep a dependency chain goes, so the
# cap only guards against a pathological chain. Past it the whole weight is neutral.
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
# The rollout model below does not apply to them. Feature enrollment reads a person property
# the configuration does not carry, so it joins the shared list here.
_UNMODELED_FILTER_KEYS = EVALUATED_BEFORE_RELEASE_CONDITIONS | {"feature_enrollment"}

# Errors that mean the dependency's stored targeting cannot be compiled. They describe that
# flag's configuration, not the caller's condition, so they must not surface as a 400. This
# mirrors the build-time errors unevaluable_filters_as_validation_errors converts.
_TARGETING_BUILD_ERRORS = (
    ValidationError,
    ExposedHogQLError,
    HogQLNotImplementedError,
    PropertyValidationError,
    ObjectDoesNotExist,
)


class _DependencyBudgetExceeded(Exception):
    pass


class _DependencyMissing(Exception):
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

    A dependency the flags service cannot resolve, because the flag is missing, deleted or not
    stored in config version 1, makes the dependent flag false for everyone, whatever value the
    condition asks for.

    Not modeled: holdouts, super conditions, feature enrollment, early exit and group-aggregated
    dependency flags, a dependency whose stored targeting cannot be compiled, a chain past the
    depth or node budgets, and a condition that is not an AND list, the only shape the flag
    editor sends. Those fall back to the neutral estimate, which is the pre-existing behavior of
    counting every person.
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
        properties = _conjunction_properties(group)
        if properties is None:
            return ast.Constant(value=NEUTRAL)
        references = [(str(prop.key), prop.value) for prop in properties if prop.type == "flag"]
        try:
            return self._conjunction_expr(references, depth=0, seen=frozenset(), assumed={})
        except _DependencyBudgetExceeded:
            # A partially expanded chain would give a misleading number, so the whole weight is neutral.
            return ast.Constant(value=NEUTRAL)
        except _DependencyMissing:
            return ast.Constant(value=0.0)

    def _conjunction_expr(
        self, references: list[tuple[str, Any]], depth: int, seen: frozenset[int], assumed: dict[str, bool | str]
    ) -> ast.Expr:
        """
        Probability that every referenced flag evaluates to its requested value. `assumed` holds the
        values the enclosing conjunctions already fixed. The flags service evaluates a flag once, so
        a reference to one of those is settled by that value rather than drawn again, and a variant
        of a flag fixed to `true` is conditional on that draw.
        """
        requested_by_flag = _merge_requested_values(references)
        child_assumed = _merge_requested_values([*assumed.items(), *references])
        if requested_by_flag is None or child_assumed is None:
            return ast.Constant(value=0.0)

        factors: list[ast.Expr] = []
        for reference, requested in requested_by_flag.items():
            settled = _settled_by(assumed.get(reference), requested)
            if settled is None:
                return ast.Constant(value=0.0)
            if settled:
                continue
            given_true = assumed.get(reference) is True
            factors.append(self._probability_expr(reference, requested, depth, seen, child_assumed, given_true))
        return _product(factors) if factors else ast.Constant(value=1.0)

    def _probability_expr(
        self,
        reference: str,
        requested: bool | str,
        depth: int,
        seen: frozenset[int],
        assumed: dict[str, bool | str],
        given_true: bool = False,
    ) -> ast.Expr:
        self._dependency_nodes += 1
        if self._dependency_nodes > MAX_DEPENDENCY_NODES or depth >= MAX_DEPENDENCY_DEPTH:
            raise _DependencyBudgetExceeded()

        flag = self._find_flag(reference)
        if flag is None or detect_config_format(flag.get_filters()).kind != "v1":
            raise _DependencyMissing()
        if not flag.active:
            # A disabled dependency is pre-seeded as false, so the flags service still evaluates the
            # dependent flag against it.
            return ast.Constant(value=1.0 if requested is False else 0.0)
        if flag.pk in seen or _has_unmodeled_evaluation(flag):
            return ast.Constant(value=NEUTRAL)

        admitted_by_set = self._admitted_probabilities(flag, depth, seen | {flag.pk}, assumed)
        if admitted_by_set is None:
            return ast.Constant(value=NEUTRAL)

        if isinstance(requested, bool):
            return _from_true_probability(requested, _running_max(admitted_by_set))
        variant = self._variant_probability(flag, admitted_by_set, requested)
        if not given_true:
            return variant
        # The enclosing conjunction already drew `true`, so only the variant's share of it is new.
        served = _running_max([self._clone(admitted) for admitted in admitted_by_set])
        return ast.Call(
            name="if",
            args=[
                ast.CompareOperation(op=ast.CompareOperationOp.Gt, left=served, right=ast.Constant(value=0.0)),
                ast.ArithmeticOperation(op=ast.ArithmeticOperationOp.Div, left=variant, right=self._clone(served)),
                ast.Constant(value=0.0),
            ],
        )

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
                factors.append(self._indicator(targeting))
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
        for index, condition in enumerate(flag.conditions):
            pinned = condition.get("variant")
            if pinned in variant_keys:
                share = 1.0 if pinned == variant else 0.0
            else:
                share = hashed_variant_share
            if share == 0:
                continue
            # The set wins only for the slice of the hash range above every earlier admitted set.
            # Each running max is a flat array, so the depth stays constant however many sets.
            up_to_here = _running_max([self._clone(admitted) for admitted in admitted_by_set[: index + 1]])
            before = _running_max([self._clone(admitted) for admitted in admitted_by_set[:index]])
            won = ast.ArithmeticOperation(op=ast.ArithmeticOperationOp.Sub, left=up_to_here, right=before)
            terms.append(_product([won, ast.Constant(value=share)]))
        if not terms:
            return ast.Constant(value=0.0)
        return ast.Call(name="arraySum", args=[ast.Array(exprs=terms)])

    def _indicator(self, predicate: ast.Expr) -> ast.Expr:
        self._charge(predicate)
        return ast.Call(name="if", args=[predicate, ast.Constant(value=1.0), ast.Constant(value=0.0)])

    def _clone(self, expr: ast.Expr) -> ast.Expr:
        self._charge(expr)
        return clone_expr(expr)

    def _charge(self, expr: ast.Expr) -> None:
        self._ast_nodes += _count_nodes(expr)
        if self._ast_nodes > MAX_WEIGHT_AST_NODES:
            raise _DependencyBudgetExceeded()


def _conjunction_properties(group: PropertyGroup) -> Optional[list[Property]]:
    """The properties an AND tree requires together, or None when the tree holds an OR group."""
    if group.type == PropertyOperatorType.OR and len(group.values) > 1:
        return None
    properties: list[Property] = []
    for value in group.values:
        if isinstance(value, Property):
            properties.append(value)
            continue
        nested = _conjunction_properties(value)
        if nested is None:
            return None
        properties.extend(nested)
    return properties


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
    return ast.ArithmeticOperation(
        op=ast.ArithmeticOperationOp.Sub, left=ast.Constant(value=1.0), right=true_probability
    )


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
    # A flat array rather than nested greatest() calls, so a flag with hundreds of sets does not
    # exhaust the recursion limit in the visitors and the printer.
    return ast.Call(name="arrayMax", args=[ast.Array(exprs=[ast.Constant(value=0.0), *exprs])])


def _product(factors: list[ast.Expr]) -> ast.Expr:
    result = factors[0]
    for factor in factors[1:]:
        result = ast.ArithmeticOperation(op=ast.ArithmeticOperationOp.Mult, left=result, right=factor)
    return result
