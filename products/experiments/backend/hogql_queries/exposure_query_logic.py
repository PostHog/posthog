"""Exposure criteria resolution and exposure filters shared by the experiment query runners."""

import logging
from collections.abc import Collection
from datetime import UTC, datetime
from typing import Optional, Union

import posthoganalytics

from posthog.schema import (
    ActionsNode,
    BehavioralPropertyFilter,
    CohortPropertyFilter,
    EventPropertyFilter,
    ExperimentEventExposureConfig,
    ExperimentExposureCriteria,
    ExperimentWarehouseNativeExposureConfig,
    GroupPropertyFilter,
    MultipleVariantHandling,
    PersonMetadataPropertyFilter,
    PersonPropertyFilter,
    PropertyOperator,
    SessionPropertyFilter,
)

from posthog.hogql import ast
from posthog.hogql.errors import ExposedHogQLError
from posthog.hogql.property import action_to_expr, operator_is_negative, property_to_expr
from posthog.hogql.utils import map_virtual_properties

from posthog.models.team.team import Team

from products.actions.backend.facade.api import get_action
from products.actions.backend.facade.contracts import ActionNotFound

logger = logging.getLogger(__name__)

# The event an experiment counts exposures on when its criteria don't name one and
# resolve_default_exposure_event does not move it to EXPERIMENT_EXPOSURE_EVENT. Consumers that
# resolve criteria through this module's helpers key off this constant. If it changes, update the
# variant-property pairing in `get_exposure_event_and_property` and the handling of configs that
# explicitly name `$feature_flag_called` too.
DEFAULT_EXPOSURE_EVENT = "$feature_flag_called"

# The dedicated exposure event that replaces $feature_flag_called as the default,
# gated per team by the flag below while it rolls out.
EXPERIMENT_EXPOSURE_EVENT = "$experiment_exposure"
EXPERIMENT_EXPOSURE_EVENT_FLAG = "experiment-exposure-event"

# The start of $experiment_exposure ingestion. Experiments started before this timestamp ran
# (at least partly) without $experiment_exposure, so they must keep counting exposures via
# $feature_flag_called, and read the $experiment_exposure copy next to it
# (exposure_event_name_filter). Only experiments whose start_date is at or after the cutoff can
# rely on $experiment_exposure covering their whole exposure window.
EXPERIMENT_EXPOSURE_EVENT_CUTOFF = datetime(2026, 9, 1, tzinfo=UTC)

# What an SDK puts on the $experiment_exposure event it sends when a feature flag rule assigns a variant.
# A rule-linked experiment reads these and never $feature_flag_response: two variants can return one value.
RULE_ID_PROPERTY = "$feature_flag_rule_id"
RULE_VARIANT_KEY_PROPERTY = "$feature_flag_variant_key"


def resolve_default_exposure_event(team: Team, start_date: Optional[datetime]) -> str:
    """
    Returns the event to count exposures on when the experiment doesn't configure a custom one.

    Experiments started at or after EXPERIMENT_EXPOSURE_EVENT_CUTOFF use $experiment_exposure,
    provided the team is flagged into the rollout. Everything else resolves to
    $feature_flag_called, because older experiments predate the new event. The exposure filters
    read $feature_flag_called together with its $experiment_exposure copy (see
    exposure_event_name_filter).
    """
    if start_date is None:
        return DEFAULT_EXPOSURE_EVENT
    if start_date.tzinfo is None:
        # Query-supplied start dates can be naive ISO strings; the stored values are UTC.
        start_date = start_date.replace(tzinfo=UTC)
    if start_date < EXPERIMENT_EXPOSURE_EVENT_CUTOFF:
        return DEFAULT_EXPOSURE_EVENT
    # only_evaluate_locally keeps this off the network, because it runs on the query hot path. An
    # inconclusive or failed local evaluation falls back to the pre-rollout default.
    try:
        enabled = posthoganalytics.feature_enabled(
            EXPERIMENT_EXPOSURE_EVENT_FLAG,
            str(team.id),
            groups={"project": str(team.id)},
            group_properties={"project": {"id": str(team.id)}},
            only_evaluate_locally=True,
            send_feature_flag_events=False,
        )
    except Exception:
        return DEFAULT_EXPOSURE_EVENT
    return EXPERIMENT_EXPOSURE_EVENT if enabled else DEFAULT_EXPOSURE_EVENT


def exposure_event_names(event: str, *, read_copies: bool = True) -> list[str]:
    """Returns the events that carry exposures for a resolved exposure event.

    An experiment on $feature_flag_called also reads $experiment_exposure, unless `read_copies`
    is False. Ingestion stops writing $feature_flag_called to events for an organization on
    FLAG_EVALUATIONS_ONLY. For a team whose flag calls ingestion copies, the $experiment_exposure
    copy then carries the exposures. Before that, a call and its copy are two rows for one
    exposure. Every exposure read aggregates per entity (first exposure time, variant), so the two
    rows give the same result as one.
    """
    if event == DEFAULT_EXPOSURE_EVENT and read_copies:
        return [DEFAULT_EXPOSURE_EVENT, EXPERIMENT_EXPOSURE_EVENT]
    return [event]


def exposure_event_name_filter(event: str, *, read_copies: bool = True) -> ast.Expr:
    """Matches the events that `exposure_event_names` returns for a resolved exposure event."""
    names = exposure_event_names(event, read_copies=read_copies)
    if len(names) > 1:
        return ast.CompareOperation(
            op=ast.CompareOperationOp.In,
            left=ast.Field(chain=["event"]),
            right=ast.Constant(value=names),
        )
    return ast.CompareOperation(
        op=ast.CompareOperationOp.Eq,
        left=ast.Field(chain=["event"]),
        right=ast.Constant(value=names[0]),
    )


# What a new experiment filters test accounts by when its criteria don't say. It does not follow
# Team.test_account_filters_default_checked: most projects leave that field null, while nearly
# every experiment stores filterTestAccounts true.
DEFAULT_FILTER_TEST_ACCOUNTS = True


def apply_exposure_criteria_defaults(exposure_criteria: Union[dict, None]) -> dict:
    """Fill in what a new experiment gets when its criteria leave a field out.

    Both experiment creation and the reads that estimate a baseline for a not-yet-created
    experiment go through here, so the two cannot describe different populations.
    """
    result = dict(exposure_criteria or {})
    if result.get("filterTestAccounts") is None:
        result["filterTestAccounts"] = DEFAULT_FILTER_TEST_ACCOUNTS
    return result


def multivariate_flag_response_expr() -> ast.Expr:
    """Matches the `$feature_flag_called` rows ingestion copies into `$experiment_exposure`.

    Ingestion has no flag definitions, so it infers multivariate from the response shape: a
    non-empty string that is neither "true" nor "false" (`isMultivariateFeatureFlagCalledEvent` in
    `nodejs/src/ingestion/common/steps/event-processing/create-event-step.ts`). A read of
    `$feature_flag_called` that stands in for `$experiment_exposure` has to apply the same rule, or
    the two events describe different populations.
    """
    return ast.CompareOperation(
        op=ast.CompareOperationOp.NotIn,
        left=ast.Call(
            name="coalesce",
            args=[
                ast.Call(name="toString", args=[ast.Field(chain=["properties", "$feature_flag_response"])]),
                ast.Constant(value=""),
            ],
        ),
        right=ast.Constant(value=["", "true", "false"]),
    )


def resolve_flag_call_source_event(events_present: Collection[str]) -> str:
    """Which of the two flag-call events a team-wide read must count, given the events it observed.

    `$experiment_exposure` is an ingestion-side copy of `$feature_flag_called`, so counting both
    double counts every multivariate call. Ingestion makes the copy only for the teams on its
    duplication list, which is separate from EXPERIMENT_EXPOSURE_EVENT_FLAG, so what the team's
    rows carry decides and the flag does not.

    This is not `resolve_default_exposure_event`: that one answers what a new experiment would
    count, which can differ from what the project's events carry.
    """
    return EXPERIMENT_EXPOSURE_EVENT if EXPERIMENT_EXPOSURE_EVENT in events_present else DEFAULT_EXPOSURE_EVENT


def _is_actions_node_dict(config: dict) -> bool:
    return config.get("kind") == "ActionsNode"


def normalize_to_exposure_criteria(
    exposure_criteria: Union[ExperimentExposureCriteria, dict, None],
) -> Optional[ExperimentExposureCriteria]:
    """Converts stored criteria (a JSONField dict) to ExperimentExposureCriteria. A typed object passes through."""
    if exposure_criteria is None:
        return None

    if isinstance(exposure_criteria, ExperimentExposureCriteria):
        return exposure_criteria

    if isinstance(exposure_criteria, dict):
        criteria_copy = dict(exposure_criteria)
        for config_key in ("exposure_config", "activation_config"):
            config = criteria_copy.get(config_key)
            if config and isinstance(config, dict):
                if _is_actions_node_dict(config):
                    criteria_copy[config_key] = ActionsNode.model_validate(config)
                elif config.get("kind") == "ExperimentWarehouseNativeExposureConfig":
                    criteria_copy[config_key] = ExperimentWarehouseNativeExposureConfig.model_validate(config)
                else:
                    criteria_copy[config_key] = ExperimentEventExposureConfig.model_validate(config)

        return ExperimentExposureCriteria.model_validate(criteria_copy)


def is_default_exposure_config(
    config: Union[ActionsNode, ExperimentEventExposureConfig, ExperimentWarehouseNativeExposureConfig, None],
) -> bool:
    """A missing config or one naming a default exposure event is the default exposure, not a
    custom one (same convention as get_exposure_event_and_property)."""
    if config is None:
        return True
    return isinstance(config, ExperimentEventExposureConfig) and config.event in (
        DEFAULT_EXPOSURE_EVENT,
        EXPERIMENT_EXPOSURE_EVENT,
    )


def rule_exposure_criteria_error(exposure_criteria: Union[ExperimentExposureCriteria, dict, None]) -> Optional[str]:
    """Why these exposure criteria cannot apply to a rule-linked experiment, or None when they can.

    Such an experiment counts only the $experiment_exposure events that carry its rule. A custom
    exposure event or an action carries no rule, so it cannot tell the rules of one flag apart. An
    activation event could build on the rule's exposures, but the rule analysis does not read one yet.
    Test account filtering, the handling of multiple variants and property filters on the default
    exposure all apply.
    """
    criteria = normalize_to_exposure_criteria(exposure_criteria)
    if criteria is None:
        return None
    if not is_default_exposure_config(criteria.exposure_config):
        return (
            "An experiment on a feature flag rule counts exposures on the $experiment_exposure event of its "
            "rule. A custom exposure event or action is not supported for it yet."
        )
    if criteria.activation_config is not None:
        return "An activation event is not supported yet for an experiment on a feature flag rule."
    return None


def has_activation_config(exposure_criteria: Union[ExperimentExposureCriteria, dict, None]) -> bool:
    """Whether the criteria put the experiment in activation mode: an activation event on top of
    the default exposure. A custom exposure_config disables activation (validation rejects the
    combination, but stored data predating it must not change semantics)."""
    criteria = normalize_to_exposure_criteria(exposure_criteria)
    return (
        criteria is not None
        and criteria.activation_config is not None
        and is_default_exposure_config(criteria.exposure_config)
    )


def get_multiple_variant_handling_from_experiment(
    exposure_criteria: Union[ExperimentExposureCriteria, dict, None],
) -> MultipleVariantHandling:
    criteria = normalize_to_exposure_criteria(exposure_criteria)

    if criteria and criteria.multiple_variant_handling:
        return criteria.multiple_variant_handling

    return MultipleVariantHandling.EXCLUDE


def resolve_filter_test_accounts(exposure_criteria: Union[ExperimentExposureCriteria, dict, None]) -> bool:
    """The filterTestAccounts a query must apply when the stored criteria don't carry one.

    Creation stamps DEFAULT_FILTER_TEST_ACCOUNTS, so absent criteria mean an experiment written
    before that defaulting existed, not an opt-out. The main results query has always read absence
    as the default, so every other surface must too, or it describes a different population than
    the results table.
    """
    criteria = normalize_to_exposure_criteria(exposure_criteria)
    if criteria is None or criteria.filterTestAccounts is None:
        return DEFAULT_FILTER_TEST_ACCOUNTS
    return criteria.filterTestAccounts


def applies_test_account_filters(
    team: Team, exposure_criteria: Union[ExperimentExposureCriteria, dict, None] = None
) -> bool:
    """Whether a query leaves out test accounts: the criteria ask for it, and the project has test account filters."""
    return (
        resolve_filter_test_accounts(exposure_criteria)
        and isinstance(team.test_account_filters, list)
        and len(team.test_account_filters) > 0
    )


def has_positive_test_account_filter(team: Team) -> bool:
    """Whether a project test account filter keeps what it matches, by a positive operator. A negative operator leaves
    out what it matches. A `hogql` filter has no operator to read, so it doesn't count."""
    if not isinstance(team.test_account_filters, list):
        return False
    return any(
        test_filter.get("type") != "hogql"
        and not operator_is_negative(test_filter.get("operator") or PropertyOperator.EXACT)
        for test_filter in team.test_account_filters
    )


def get_test_accounts_filter(
    team: Team, exposure_criteria: Union[ExperimentExposureCriteria, dict, None] = None
) -> list[ast.Expr]:
    if applies_test_account_filters(team, exposure_criteria):
        return [property_to_expr(property, team) for property in team.test_account_filters]
    return []


def get_exposure_event_and_property(
    feature_flag_key: str,
    exposure_criteria: Union[ExperimentExposureCriteria, dict, None] = None,
    *,
    default_exposure_event: str,
) -> tuple[Optional[str], str]:
    """
    Returns (event_name, feature_flag_variant_property) for exposures. event_name is None for an
    ActionsNode config, because an action can match several events.

    `default_exposure_event` is what the experiment's default exposure resolves to
    (`resolve_default_exposure_event`). It is required so that every consumer makes the rollout
    decision explicitly: resolve it for the experiment being served, or pass
    DEFAULT_EXPOSURE_EVENT where staying on the legacy event is the deliberate choice.
    """
    criteria = normalize_to_exposure_criteria(exposure_criteria)

    exposure_config = criteria.exposure_config if criteria else None

    if isinstance(exposure_config, ExperimentWarehouseNativeExposureConfig):
        raise ExposedHogQLError("Warehouse-native sources cannot be calculated yet.")
    if isinstance(exposure_config, ActionsNode):
        # build_exposure_event_conditions applies the action filter.
        feature_flag_variant_property = f"$feature/{feature_flag_key}"
        event = None
    elif (
        isinstance(exposure_config, ExperimentEventExposureConfig)
        and exposure_config.event
        and exposure_config.event not in (DEFAULT_EXPOSURE_EVENT, EXPERIMENT_EXPOSURE_EVENT)
    ):
        # A custom exposure event carries the variant in the $feature/<key> property.
        feature_flag_variant_property = f"$feature/{feature_flag_key}"
        event = exposure_config.event
    else:
        # $experiment_exposure is an ingestion-side duplicate of $feature_flag_called and carries
        # the same properties, so both resolve the variant from $feature_flag_response. A config
        # naming $feature_flag_called is the stored default rather than a custom choice, so it
        # follows the resolved default event the same way an absent config does.
        feature_flag_variant_property = "$feature_flag_response"
        if exposure_config is not None and getattr(exposure_config, "event", None) == EXPERIMENT_EXPOSURE_EVENT:
            event = EXPERIMENT_EXPOSURE_EVENT
        else:
            event = default_exposure_event

    return event, feature_flag_variant_property


def _get_event_name_from_config(
    exposure_config: Optional[
        Union[ActionsNode, ExperimentEventExposureConfig, ExperimentWarehouseNativeExposureConfig]
    ],
    default_exposure_event: str,
) -> str:
    if not exposure_config or not hasattr(exposure_config, "event"):
        return default_exposure_event

    event = exposure_config.event
    # An explicit $feature_flag_called config is the stored default, so it resolves like an
    # absent config instead of pinning the pre-rollout event.
    if not event or event == DEFAULT_EXPOSURE_EVENT:
        return default_exposure_event
    return str(event)


def _build_action_filter(action_id: int, team: Team) -> ast.Expr:
    """Build filter expression for an action, returning False if action not found."""
    try:
        action = get_action(action_id=action_id, team_id=team.pk)
        return action_to_expr(action)
    except ActionNotFound:
        logger.warning(f"Action {action_id} not found for team {team.id}. Exposure query will return no results.")
        return ast.Constant(value=False)


def _build_event_filters(
    exposure_config: Optional[
        Union[ActionsNode, ExperimentEventExposureConfig, ExperimentWarehouseNativeExposureConfig]
    ],
    team: Team,
    feature_flag_key: Optional[str],
    default_exposure_event: str,
) -> list[ast.Expr]:
    if isinstance(exposure_config, ActionsNode):
        return [_build_action_filter(int(exposure_config.id), team)]
    if isinstance(exposure_config, ExperimentWarehouseNativeExposureConfig):
        raise ExposedHogQLError("Warehouse-native sources cannot be calculated yet.")

    event = _get_event_name_from_config(exposure_config, default_exposure_event)
    filters: list[ast.Expr] = [exposure_event_name_filter(event)]

    # $feature_flag_called and $experiment_exposure are not specific to one flag, so without the
    # flag key filter, exposures of other experiments would count too.
    if event in (DEFAULT_EXPOSURE_EVENT, EXPERIMENT_EXPOSURE_EVENT) and feature_flag_key:
        filters.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["properties", "$feature_flag"]),
                right=ast.Constant(value=feature_flag_key),
            )
        )

    return filters


def _build_property_filters(
    exposure_config: Optional[
        Union[ActionsNode, ExperimentEventExposureConfig, ExperimentWarehouseNativeExposureConfig]
    ],
    team: Team,
) -> list[ast.Expr]:
    if not exposure_config or exposure_config.kind != "ExperimentEventExposureConfig" or not exposure_config.properties:
        return []

    property_filters = [property_to_expr(prop, team) for prop in exposure_config.properties]
    return [ast.And(exprs=property_filters)] if property_filters else []


def build_exposure_event_conditions(
    exposure_criteria: Union[ExperimentExposureCriteria, dict, None],
    team: Team,
    feature_flag_key: Optional[str],
    *,
    default_exposure_event: str,
) -> list[ast.Expr]:
    """
    Builds the event/action and property filters that define what counts as an exposure event,
    without the analysis-only conditions (date range, variant filter, test-account exclusion).
    Used by consumers that need "who was exposed" for serving decisions rather than metric
    analysis, such as the freeze-exposure snapshot scan.

    `default_exposure_event` follows the same contract as in `get_exposure_event_and_property`:
    resolve it per experiment to honor the $experiment_exposure rollout, or pass
    DEFAULT_EXPOSURE_EVENT where staying on the legacy event is the deliberate choice.
    """
    criteria = normalize_to_exposure_criteria(exposure_criteria)
    exposure_config = criteria.exposure_config if criteria else None
    return [
        *_build_event_filters(exposure_config, team, feature_flag_key, default_exposure_event),
        *_build_property_filters(exposure_config, team),
    ]


def exposure_criteria_on_the_event(
    exposure_criteria: Union[ExperimentExposureCriteria, dict, None],
) -> Optional[ExperimentExposureCriteria]:
    """
    The exposure criteria with only the filters that compare a property of the exposure event with a fixed value.
    HogQL compiles each of them to a read of that one property, so the filter reads nothing but the event. Its match
    can still depend on the type of the property and the timezone of the team.
    """
    criteria = normalize_to_exposure_criteria(exposure_criteria)
    config = criteria.exposure_config if criteria else None
    if criteria is None or not isinstance(config, ExperimentEventExposureConfig) or not config.properties:
        return criteria
    kept = [prop for prop in config.properties if _compares_an_event_value(prop)]
    return criteria.model_copy(update={"exposure_config": config.model_copy(update={"properties": kept})})


def exposure_filters_off_the_event_narrow_who(exposure_criteria: Union[ExperimentExposureCriteria, dict, None]) -> bool:
    """
    Whether every filter that `exposure_criteria_on_the_event` leaves out narrows down which persons, groups or
    sessions count. Without such a filter a query counts more exposures than the results do, never fewer. Any other
    filter, such as a HogQL expression or a virtual property, can read more than the event, or change its match with
    the clock or a team setting.
    """
    criteria = normalize_to_exposure_criteria(exposure_criteria)
    config = criteria.exposure_config if criteria else None
    if not isinstance(config, ExperimentEventExposureConfig):
        return True
    return all(_compares_an_event_value(prop) or isinstance(prop, _FILTERS_ON_WHO) for prop in config.properties or [])


_FILTERS_ON_WHO = (
    PersonPropertyFilter,
    PersonMetadataPropertyFilter,
    CohortPropertyFilter,
    BehavioralPropertyFilter,
    GroupPropertyFilter,
    SessionPropertyFilter,
)

# The operators that compare the property with the filter's own value. The others read team settings, such as the
# path cleaning rules, read other models, such as cohorts and flags, or parse dates.
_VALUE_OPERATORS = frozenset(
    {
        PropertyOperator.EXACT,
        PropertyOperator.IS_NOT,
        PropertyOperator.ICONTAINS,
        PropertyOperator.NOT_ICONTAINS,
        PropertyOperator.STARTS_WITH,
        PropertyOperator.NOT_STARTS_WITH,
        PropertyOperator.ENDS_WITH,
        PropertyOperator.NOT_ENDS_WITH,
        PropertyOperator.REGEX,
        PropertyOperator.NOT_REGEX,
        PropertyOperator.GT,
        PropertyOperator.GTE,
        PropertyOperator.LT,
        PropertyOperator.LTE,
        PropertyOperator.IS_SET,
        PropertyOperator.IS_NOT_SET,
        PropertyOperator.SEMVER_EQ,
        PropertyOperator.SEMVER_NEQ,
        PropertyOperator.SEMVER_GT,
        PropertyOperator.SEMVER_GTE,
        PropertyOperator.SEMVER_LT,
        PropertyOperator.SEMVER_LTE,
        PropertyOperator.SEMVER_TILDE,
        PropertyOperator.SEMVER_CARET,
        PropertyOperator.SEMVER_WILDCARD,
    }
)


def _compares_an_event_value(prop: object) -> bool:
    if not isinstance(prop, EventPropertyFilter):
        return False
    field = ast.Field(chain=["properties", prop.key])
    # A virtual property compiles to an expression that can read persons and team settings.
    return map_virtual_properties(field) is field and (prop.operator or PropertyOperator.EXACT) in _VALUE_OPERATORS


def aggregates_by_group(group_type_index: object) -> bool:
    return isinstance(group_type_index, int)


def get_entity_key(group_type_index: Optional[int]) -> str:
    if aggregates_by_group(group_type_index):
        return f"$group_{group_type_index}"
    return "person_id"
