from dataclasses import asdict
from typing import Any

from products.experiments.backend.facade.contracts import ExperimentHealthInputsTrafficStatus
from products.experiments.backend.health.checks.forced_variant import needs_condition_set_traffic
from products.experiments.backend.health.condition_set_traffic import denied_scanned_properties
from products.experiments.backend.health.context import (
    ConditionSetTraffic,
    FlagState,
    Split,
    SplitHistory,
    SplitHistoryNotChecked,
)
from products.experiments.backend.health.exposure_inputs import ExposureInputs
from products.experiments.backend.health.loader import HealthInputs


def _health_inputs_split(split: Split) -> list[dict[str, Any]]:
    return [{"key": variant.key, "rollout_percentage": variant.rollout_percentage} for variant in split]


def _health_inputs_flag(flag: FlagState) -> dict[str, Any]:
    reachable = {condition.number: condition for condition in flag.reachable_conditions}
    return {
        "active": flag.active,
        "deleted": flag.deleted,
        "release_conditions": [
            {
                "number": number,
                "rollout_percentage": group.rollout_percentage,
                "property_count": group.property_count,
                "reachable": number in reachable,
                "pinned_variant": reachable[number].pinned_variant if number in reachable else None,
            }
            for number, group in enumerate(flag.release_groups, start=1)
        ],
        "variants": _health_inputs_split(flag.variants),
    }


def _health_inputs_split_history(history: SplitHistory | SplitHistoryNotChecked) -> dict[str, Any]:
    if isinstance(history, SplitHistory):
        # The counted changes are the tail of every change, so their count marks where counting starts.
        first_counted = len(history.changes) - len(history.counted_changes)
        reason, exposed_before_first, exposed_between = None, history.exposed_before_first, history.exposed_between
    else:
        first_counted = len(history.changes)
        reason, exposed_before_first, exposed_between = history.reason.value, None, None
    return {
        "checked": reason is None,
        "not_checked_reason": reason,
        "launched_at": history.launched_at,
        "team_timezone": history.team_timezone,
        "changes": [
            {
                "changed_at": change.changed_at,
                "before": _health_inputs_split(change.before),
                "after": _health_inputs_split(change.after),
                "counted": index >= first_counted,
            }
            for index, change in enumerate(history.changes)
        ],
        "exposed_before_first": exposed_before_first,
        "exposed_between": exposed_between,
    }


def _health_inputs_traffic(traffic: ConditionSetTraffic) -> dict[str, Any]:
    return {
        "since": traffic.since,
        "team_timezone": traffic.team_timezone,
        "people_by_set": [
            {"condition_set": condition_set, "people": people}
            for condition_set, people in sorted(traffic.people_by_set.items())
        ],
        "calls": traffic.calls,
        "remotely_evaluated_calls": traffic.remotely_evaluated_calls,
    }


def _health_inputs_traffic_status(inputs: HealthInputs) -> ExperimentHealthInputsTrafficStatus:
    ctx = inputs.context
    # Mirrors the order of the early returns in `load_condition_set_traffic`.
    if ctx.condition_set_traffic is not None:
        return ExperimentHealthInputsTrafficStatus.READ
    if not needs_condition_set_traffic(ctx):
        return ExperimentHealthInputsTrafficStatus.NOT_NEEDED
    if not inputs.reader_access.can_query_events:
        return ExperimentHealthInputsTrafficStatus.NO_QUERY_ACCESS
    if denied_scanned_properties(inputs.reader_access):
        return ExperimentHealthInputsTrafficStatus.DENIED_PROPERTIES
    if inputs.flag_version is None:
        return ExperimentHealthInputsTrafficStatus.NO_FLAG_VERSION
    return ExperimentHealthInputsTrafficStatus.UNKNOWN


def _health_inputs_exposures(exposures: ExposureInputs) -> dict[str, Any]:
    totals = exposures.totals
    return {
        "status": exposures.status,
        "computed_at": exposures.computed_at,
        "totals": {
            "total_exposures": dict(totals.total_exposures),
            "multiple_variant_handling": totals.multiple_variant_handling.value,
            "sample_ratio_mismatch_p_value": totals.sample_ratio_mismatch_p_value,
            "hours_since_launch": totals.hours_since_launch,
        }
        if totals
        else None,
        "findings": [finding.model_dump(mode="json") for finding in exposures.findings],
        "error": exposures.error,
    }


def health_inputs_payload(inputs: HealthInputs) -> dict[str, Any]:
    """The inputs as plain data in the shape of `ExperimentHealthInputsSerializer`, so the presentation layer renders
    them without reading the health package's types."""
    ctx, reader_access = inputs.context, inputs.reader_access
    return {
        "is_launched": ctx.is_launched,
        "is_running": ctx.is_running,
        "has_ended": ctx.has_ended,
        "is_paused": ctx.is_paused,
        "archived": ctx.archived,
        "baseline_variant_key": ctx.baseline_variant_key,
        "excluded_variant_keys": sorted(ctx.excluded_variant_keys),
        "primary_metric_count": ctx.primary_metric_count,
        "secondary_metric_count": ctx.secondary_metric_count,
        "flag": _health_inputs_flag(ctx.flag) if ctx.flag else None,
        "split_history": _health_inputs_split_history(ctx.split_history) if ctx.split_history else None,
        "condition_set_traffic_status": _health_inputs_traffic_status(inputs),
        "condition_set_traffic": _health_inputs_traffic(ctx.condition_set_traffic)
        if ctx.condition_set_traffic
        else None,
        "reader_access": {
            "can_read_flag_history": reader_access.can_read_flag_history,
            "can_query_events": reader_access.can_query_events,
            "denied_event_properties": sorted(reader_access.denied_event_properties),
        },
        "exposures": _health_inputs_exposures(inputs.exposures),
        "project": asdict(inputs.project),
    }
