"""Exposure criteria resolution and exposure filters shared by the experiment query runners."""

import logging
from collections.abc import Collection
from datetime import UTC, datetime
from typing import Optional, Union

import posthoganalytics

from posthog.schema import (
    ActionsNode,
    ExperimentEventExposureConfig,
    ExperimentExposureCriteria,
    MultipleVariantHandling,
)

from posthog.hogql import ast
from posthog.hogql.property import action_to_expr, property_to_expr

from posthog.models.team.team import Team

from products.actions.backend.models.action import Action

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
# $feature_flag_called even where the two overlap. Only experiments whose start_date is at or
# after the cutoff can rely on $experiment_exposure covering their whole exposure window.
EXPERIMENT_EXPOSURE_EVENT_CUTOFF = datetime(2026, 9, 1, tzinfo=UTC)


def resolve_default_exposure_event(team: Team, start_date: Optional[datetime]) -> str:
    """
    Returns the event to count exposures on when the experiment doesn't configure a custom one.

    Experiments started at or after EXPERIMENT_EXPOSURE_EVENT_CUTOFF use $experiment_exposure,
    provided the team is flagged into the rollout. Everything else stays on $feature_flag_called:
    older experiments predate the new event, and because ingestion duplicates flag events into
    $experiment_exposure, counting exactly one of the two is what avoids double counting.
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
                else:
                    criteria_copy[config_key] = ExperimentEventExposureConfig.model_validate(config)

        return ExperimentExposureCriteria.model_validate(criteria_copy)


def is_default_exposure_config(config: Union[ActionsNode, ExperimentEventExposureConfig, None]) -> bool:
    """A missing config or one naming a default exposure event is the default exposure, not a
    custom one (same convention as get_exposure_event_and_property)."""
    if config is None:
        return True
    return isinstance(config, ExperimentEventExposureConfig) and config.event in (
        DEFAULT_EXPOSURE_EVENT,
        EXPERIMENT_EXPOSURE_EVENT,
    )


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


def get_test_accounts_filter(
    team: Team, exposure_criteria: Union[ExperimentExposureCriteria, dict, None] = None
) -> list[ast.Expr]:
    criteria = normalize_to_exposure_criteria(exposure_criteria)

    filter_test_accounts = criteria.filterTestAccounts if criteria else False

    if filter_test_accounts and isinstance(team.test_account_filters, list) and len(team.test_account_filters) > 0:
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

    if isinstance(exposure_config, ActionsNode):
        # build_exposure_event_conditions applies the action filter.
        feature_flag_variant_property = f"$feature/{feature_flag_key}"
        event = None
    elif (
        exposure_config
        and hasattr(exposure_config, "event")
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
    exposure_config: Optional[Union[ActionsNode, ExperimentEventExposureConfig]],
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
        action = Action.objects.get(pk=action_id, team=team)
        return action_to_expr(action)
    except Action.DoesNotExist:
        logger.warning(f"Action {action_id} not found for team {team.id}. Exposure query will return no results.")
        return ast.Constant(value=False)


def _build_event_filters(
    exposure_config: Optional[Union[ActionsNode, ExperimentEventExposureConfig]],
    team: Team,
    feature_flag_key: Optional[str],
    default_exposure_event: str,
) -> list[ast.Expr]:
    if isinstance(exposure_config, ActionsNode):
        return [_build_action_filter(int(exposure_config.id), team)]

    event = _get_event_name_from_config(exposure_config, default_exposure_event)
    filters: list[ast.Expr] = [
        ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["event"]),
            right=ast.Constant(value=event),
        )
    ]

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
    exposure_config: Optional[Union[ActionsNode, ExperimentEventExposureConfig]], team: Team
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


def get_entity_key(group_type_index: Optional[int]) -> str:
    if isinstance(group_type_index, int):
        return f"$group_{group_type_index}"
    return "person_id"
