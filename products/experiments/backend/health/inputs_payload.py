import json
from dataclasses import asdict
from datetime import datetime
from typing import Any

from products.experiments.backend.facade.contracts import (
    ExperimentHealthFlagChangeKind,
    ExperimentHealthInputsTrafficStatus,
)
from products.experiments.backend.health.condition_set_traffic import (
    denied_scanned_properties,
    needs_condition_set_traffic,
)
from products.experiments.backend.health.context import (
    ConditionSetTraffic,
    FlagChange,
    FlagHistory,
    FlagHistoryNotChecked,
    FlagState,
    LatestCalculation,
    MetricCompiles,
)
from products.experiments.backend.health.exposure_inputs import ExposureInputs
from products.experiments.backend.health.loader import HealthInputs
from products.feature_flags.backend.facade.edits import (
    BucketingChange,
    BucketingSetting,
    ConditionsChange,
    ReleaseCondition,
    Split,
    SplitChange,
)


def _health_inputs_split(split: Split) -> list[dict[str, Any]]:
    return [{"key": variant.key, "rollout_percentage": variant.rollout_percentage} for variant in split]


def _health_inputs_percentage(value: float | None) -> str:
    # Written as the page writes a number, so 50.0 reads "50%".
    if value is None:
        return "unset"
    return f"{int(value) if value.is_integer() else value}%"


def _health_inputs_split_text(split: Split) -> str:
    if not split:
        return "none"
    return ", ".join(
        f"{variant.key if variant.key is not None else 'no key'} {_health_inputs_percentage(variant.rollout_percentage)}"
        for variant in split
    )


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
        "split_text": _health_inputs_split_text(flag.variants),
    }


_SETTING_LABELS = {
    BucketingSetting.KEY: "Key",
    BucketingSetting.AGGREGATION: "Match by group type",
    BucketingSetting.BUCKETING_IDENTIFIER: "Bucketing identifier",
    BucketingSetting.EXPERIENCE_CONTINUITY: "Persist across authentication",
}


def _health_inputs_bucketing_value(value: str | int | bool | None) -> str:
    if value is None:
        return "none"
    return value if isinstance(value, str) else json.dumps(value)


def _health_inputs_conditions_text(conditions: tuple[ReleaseCondition, ...]) -> str:
    count = f"{len(conditions)} {'condition' if len(conditions) == 1 else 'conditions'}"
    overrides = [
        f"set {number} overrides to {condition.variant}"
        for number, condition in enumerate(conditions, start=1)
        if condition.variant
    ]
    return ", ".join([count, *overrides])


def _health_inputs_flag_change(change: FlagChange) -> dict[str, Any]:
    """A change as the staff view lists it, with its values as text, so the view needs no code per kind."""
    match change:
        case SplitChange():
            return {
                "kind": ExperimentHealthFlagChangeKind.SPLIT,
                "changed": "Split",
                "before": _health_inputs_split_text(change.before),
                "after": _health_inputs_split_text(change.after),
            }
        case BucketingChange():
            return {
                "kind": ExperimentHealthFlagChangeKind.BUCKETING,
                "changed": _SETTING_LABELS[change.setting],
                "before": _health_inputs_bucketing_value(change.before),
                "after": _health_inputs_bucketing_value(change.after),
            }
        case ConditionsChange():
            return {
                "kind": ExperimentHealthFlagChangeKind.RELEASE_CONDITIONS,
                "changed": "Release conditions",
                "before": _health_inputs_conditions_text(change.before),
                "after": _health_inputs_conditions_text(change.after),
            }


def _health_inputs_flag_history(history: FlagHistory | FlagHistoryNotChecked) -> dict[str, Any]:
    if isinstance(history, FlagHistory):
        counted_since: datetime | None = history.counted_since
        reason = None
        exposed_before_first = history.exposed_before_first
        exposed_between = history.exposed_between
    else:
        counted_since, reason, exposed_before_first, exposed_between = None, history.reason.value, None, {}

    changes = [
        {
            **_health_inputs_flag_change(change),
            "changed_at": change.changed_at,
            "counted": counted_since is not None and change.changed_at >= counted_since,
        }
        for change in history.changes
    ]
    counted_kinds = {change["kind"] for change in changes if change["counted"]}
    return {
        "checked": reason is None,
        "not_checked_reason": reason,
        "launched_at": history.launched_at,
        "team_timezone": history.team_timezone,
        "changes": changes,
        "exposed_before_first": exposed_before_first,
        "exposed_between": [
            {
                "kind": kind,
                "question": f"Exposed between the first and last {kind.label.lower()} change",
                "exposed": exposed_between.get(kind),
            }
            for kind in ExperimentHealthFlagChangeKind
            if kind in counted_kinds
        ],
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
        "people_assigned_outside": traffic.people_assigned_outside,
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


def _health_inputs_metric_compiles(compiles: MetricCompiles) -> dict[str, Any]:
    return {
        "metric_count": compiles.metric_count,
        "unknown_count": compiles.unknown_count,
        "no_access_count": compiles.no_access_count,
        "exposure_query_fails": compiles.exposure_query_fails,
        "failures": [
            {"name": failure.name, "role": failure.role, "kind": failure.kind.value, "message": failure.message}
            for failure in compiles.failures
        ],
    }


def _health_inputs_latest_calculation(calculation: LatestCalculation) -> dict[str, Any]:
    return {
        "finished_at": calculation.finished_at,
        "failures": [
            {
                "name": failure.name,
                "role": failure.role,
                "error_type": failure.error_type,
                "step": failure.step,
                "retriable": failure.retriable,
                "message": None if failure.can_quote_evaluation_rules else failure.message,
            }
            for failure in calculation.failures
        ],
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
        "flag_last_called_at": inputs.flag_last_called_at,
        "flag_called": ctx.flag_called,
        "flag_called_during_run": ctx.flag_called_during_run,
        "flag_called_after_end": ctx.flag_called_after_end,
        "exposure_events": {
            "custom_event": ctx.exposure_events.custom_event,
            "required_flag_key": ctx.exposure_events.required_flag_key,
            "variant_property": ctx.exposure_events.variant_property,
            "activation": ctx.exposure_events.activation,
        }
        if ctx.exposure_events
        else None,
        "events_received": dict(ctx.events_received),
        "metric_compiles": _health_inputs_metric_compiles(ctx.metric_compiles) if ctx.metric_compiles else None,
        "latest_calculation": _health_inputs_latest_calculation(ctx.latest_calculation)
        if ctx.latest_calculation
        else None,
        "flag_history": _health_inputs_flag_history(ctx.flag_history) if ctx.flag_history else None,
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
