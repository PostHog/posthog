"""
Shared exposure logic for experiment query runners.

This module contains common functions for handling experiment exposures,
including multiple variant handling and exposure filtering logic.
"""

import logging
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
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import action_to_expr, property_to_expr

from posthog.models.team.team import Team

from products.actions.backend.models.action import Action
from products.experiments.backend.hogql_queries import MULTIPLE_VARIANT_KEY

logger = logging.getLogger(__name__)

# The event an experiment counts exposures on when its criteria don't name one. If the default
# ever changes (e.g. to a dedicated exposure event), flip it here — consumers that resolve
# criteria through this module's helpers key off this constant. Note the variant-property
# pairing in `get_exposure_event_and_property` (and the handling of configs that explicitly
# name `$feature_flag_called`) must move with it.
DEFAULT_EXPOSURE_EVENT = "$feature_flag_called"

# The dedicated exposure event that replaces $feature_flag_called as the default,
# gated per team by the flag below while it rolls out.
EXPERIMENT_EXPOSURE_EVENT = "$experiment_exposure"
EXPERIMENT_EXPOSURE_EVENT_FLAG = "experiment-exposure-event"

# When $experiment_exposure ingestion goes live. Experiments started before this timestamp ran
# (at least partly) without the new event, so they must keep counting exposures via
# $feature_flag_called even where the two overlap. Only experiments whose start_date is at or
# after the cutoff can rely on $experiment_exposure covering their whole exposure window.
EXPERIMENT_EXPOSURE_EVENT_CUTOFF = datetime(2026, 8, 5, tzinfo=UTC)


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
    # only_evaluate_locally keeps this off the network - it runs on the query hot path, so an
    # inconclusive or failed local evaluation must fall back to the pre-rollout default.
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


def _is_actions_node_dict(config: dict) -> bool:
    """
    Helper to determine if a dict represents an ActionsNode.
    Checks for the 'kind' field first as the primary indicator.
    """
    return config.get("kind") == "ActionsNode"


def normalize_to_exposure_criteria(
    exposure_criteria: Union[ExperimentExposureCriteria, dict, None],
) -> Optional[ExperimentExposureCriteria]:
    """
    Normalizes various input types to a properly typed ExperimentExposureCriteria object.

    This handles the conversion from:
    - Django Experiment models (extracts exposure_criteria field)
    - Plain dictionaries (from JSONFields)
    - Already typed ExperimentExposureCriteria objects (passthrough)
    - None values

    Returns:
        ExperimentExposureCriteria object or None
    """
    if exposure_criteria is None:
        return None

    # Already a typed object, return as-is
    if isinstance(exposure_criteria, ExperimentExposureCriteria):
        return exposure_criteria

    # Convert dict to typed object
    if isinstance(exposure_criteria, dict):
        # Copy only known fields before the strict (extra="forbid") parse: the write-side
        # validator never rejected unknown top-level keys, so saved criteria can carry
        # stray ones (e.g. `properties`, which belongs at exposure_config.properties) —
        # erroring here would break every results/exposure query for that experiment.
        criteria_copy = {k: v for k, v in exposure_criteria.items() if k in ExperimentExposureCriteria.model_fields}
        # Also normalize nested configs if present
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
    """
    Determines how to handle entities exposed to multiple variants based on experiment configuration.
    """
    criteria = normalize_to_exposure_criteria(exposure_criteria)

    if criteria and criteria.multiple_variant_handling:
        return criteria.multiple_variant_handling

    # Default to "exclude" if not specified
    return MultipleVariantHandling.EXCLUDE


def get_variant_selection_expr(
    feature_flag_variant_property: str, multiple_variant_handling: MultipleVariantHandling
) -> ast.Expr:
    """
    Returns the appropriate variant selection expression based on multiple_variant_handling configuration.

    Args:
        feature_flag_variant_property: The property name containing the variant value
        multiple_variant_handling: How to handle multiple exposures (EXCLUDE or FIRST_SEEN)
    """
    variant_property_field = ast.Field(chain=["properties", feature_flag_variant_property])

    match multiple_variant_handling:
        case MultipleVariantHandling.FIRST_SEEN:
            # Use variant from earliest exposure (minimum timestamp)
            return parse_expr(
                "argMin({variant_property}, timestamp)",
                placeholders={
                    "variant_property": variant_property_field,
                },
            )
        case _:
            # Default behavior is EXCLUDE. Users who have seen more than one variant is assigned to the
            # MULTIPLE_VARIANT_KEY group
            return parse_expr(
                "if(count(distinct {variant_property}) > 1, {multiple_variant_key}, any({variant_property}))",
                placeholders={
                    "variant_property": variant_property_field,
                    "multiple_variant_key": ast.Constant(value=MULTIPLE_VARIANT_KEY),
                },
            )


def get_test_accounts_filter(
    team: Team, exposure_criteria: Union[ExperimentExposureCriteria, dict, None] = None
) -> list[ast.Expr]:
    """
    Returns test account filters based on experiment configuration.

    Args:
        team: The team object
        exposure_criteria: Experiment exposure criteria configuration
    """
    # Normalize to typed object
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
    Determines which event and feature flag variant property to use for exposures.

    Args:
        feature_flag_key: The feature flag key
        exposure_criteria: Experiment exposure criteria configuration
        default_exposure_event: What the experiment's default exposure resolves to
            (`resolve_default_exposure_event`). Required so every consumer makes the rollout
            decision explicitly: resolve it for the experiment being served, or pass
            DEFAULT_EXPOSURE_EVENT where staying on the legacy event is the deliberate choice.

    Returns:
        Tuple of (event_name, feature_flag_variant_property)
        event_name can be None for ActionsNode (actions can match multiple events)
    """
    # Normalize to typed object
    criteria = normalize_to_exposure_criteria(exposure_criteria)

    exposure_config = criteria.exposure_config if criteria else None

    # Handle ActionsNode
    if isinstance(exposure_config, ActionsNode):
        # For actions, we don't filter by event name (actions can match multiple events)
        # The action filter will be applied in build_exposure_event_conditions
        feature_flag_variant_property = f"$feature/{feature_flag_key}"
        event = None
    elif (
        exposure_config
        and hasattr(exposure_config, "event")
        and exposure_config.event
        and exposure_config.event not in (DEFAULT_EXPOSURE_EVENT, EXPERIMENT_EXPOSURE_EVENT)
    ):
        # For custom exposure events, we extract the event name from the exposure config
        # and get the variant from the $feature/<key> property
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
    """Extract event name from exposure config, defaulting to the resolved default exposure event."""
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
    """Build event/action filters based on exposure config."""
    # Handle action-based exposure
    if isinstance(exposure_config, ActionsNode):
        return [_build_action_filter(int(exposure_config.id), team)]

    # Handle event-based exposure
    event = _get_event_name_from_config(exposure_config, default_exposure_event)
    filters: list[ast.Expr] = [
        ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=["event"]),
            right=ast.Constant(value=event),
        )
    ]

    # Add feature flag key filter for $feature_flag_called events. $experiment_exposure gets the
    # same treatment: ingestion emits it for every experiment, so without this filter exposures
    # of other experiments would count too.
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
    """Build property filters from exposure config."""
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
    """
    Returns the appropriate entity key based on whether we're dealing with groups or persons.

    Args:
        group_type_index: Group type index if using groups, None for persons

    Returns:
        Entity key string (either "person_id" or "$group_{index}")
    """
    if isinstance(group_type_index, int):
        return f"$group_{group_type_index}"
    return "person_id"
