"""How a logs alert reads in a native platform notification.

The platform words a message generically ("Value: 11"). This gives it the logs wording the legacy
messages use: a count of logs in a window, the filters the alert watches, and a link to the logs.

Imported from `ready()`, so it stays light: no models, no query layer.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import NAMESPACE_URL, uuid5

from posthog.utils import absolute_uri

from products.alerts_platform.backend.facade.contracts import (
    AlertEventKind,
    AnnouncedTransition,
    MessageDetail,
    MessageLink,
    SourceDescription,
)
from products.logs.backend.alert_evaluation_key import window_end_of
from products.logs.backend.alert_group_columns import GROUP_COLUMNS
from products.logs.backend.logs_url_params import build_logs_url_params, has_filter_values
from products.logs.backend.platform_source_config import filters_of, logs_alert_url

# A resolve reports the count that ended the firing, so it is not a breach. A held check, which
# only moves a paging incident, can be either, so it gets a neutral label.
_LABELS = {
    AlertEventKind.FIRING: "Threshold breached",
    AlertEventKind.RESOLVED: "Current count",
}


def describe_logs_transition(*, project_id: int, transition: AnnouncedTransition) -> SourceDescription:
    return SourceDescription(
        details=_details(transition),
        context=_context(filters_of(transition.source_config)),
        data_link=MessageLink(label="View logs", url=_logs_url(project_id, transition)),
    )


def _details(transition: AnnouncedTransition) -> tuple[MessageDetail, ...]:
    if transition.value is None:
        return ()
    condition = transition.condition
    # A count of logs is a whole number, and `:g` would print a million as "1e+06".
    value = transition.value
    count = f"{value:,.0f}" if value.is_integer() else f"{value:g}"
    noun = "log" if count == "1" else "logs"
    summary = (
        f"{count} {noun} in {condition['window_minutes']}m "
        f"(threshold: {condition['threshold_operator']} {condition['threshold_count']})"
    )
    # A grouped alert sends one message per group, so each one names the group it is about.
    group = tuple(
        MessageDetail(label=group_column.label, value=transition.labels[column])
        for column, group_column in GROUP_COLUMNS.items()
        if column in transition.labels
    )
    return (*group, MessageDetail(label=_LABELS.get(transition.kind, "Count"), value=summary))


def _context(filters: dict[str, Any]) -> tuple[str, ...]:
    lines: list[str] = []
    severity_levels = filters.get("severityLevels") or []
    service_names = filters.get("serviceNames") or []
    filter_group = filters.get("filterGroup")
    if severity_levels:
        lines.append("Severity: " + ", ".join(severity_levels))
    if service_names:
        lines.append("Services: " + ", ".join(service_names))
    if filter_group and has_filter_values(filter_group):
        lines.append("Property filters applied")
    return tuple(lines) or ("All log levels and services",)


def _logs_url(project_id: int, transition: AnnouncedTransition) -> str:
    params = _window_params(transition)
    return absolute_uri(f"/project/{project_id}/logs" + (f"?{params}" if params else ""))


def in_utc(transition: AnnouncedTransition) -> AnnouncedTransition:
    # History rows come back from ClickHouse without a zone. A link or a body with zoneless times
    # reads them in whatever zone the reader is in.
    if transition.occurred_at.tzinfo is not None:
        return transition
    return replace(transition, occurred_at=transition.occurred_at.replace(tzinfo=UTC))


def check_window_end(transition: AnnouncedTransition) -> datetime:
    """The end of the window the check counted, so a link opens on the logs that decided it.

    The window end can sit before the record time, because the check clamps it to the ingestion checkpoint.
    """
    window_end = window_end_of(transition.evaluation_key)
    return in_utc(replace(transition, occurred_at=window_end) if window_end else transition).occurred_at


def _window_params(transition: AnnouncedTransition) -> str:
    date_to = check_window_end(transition)
    date_from = date_to - timedelta(minutes=transition.condition["window_minutes"])
    return build_logs_url_params(_group_filters(transition), date_from=date_from, date_to=date_to)


def _group_filters(transition: AnnouncedTransition) -> dict[str, Any]:
    """The alert's filters narrowed to the group a transition is about, so a link opens its logs only.

    The group's value replaces any list the alert has for that column, in its own field and in each
    `filterGroup` selection of the column. An alert with a list counted only logs inside it, so the
    group's value is one of them and the link narrows, never widens.
    """
    filters = dict(filters_of(transition.source_config))
    selected: dict[str, str] = {}
    for column, group_column in GROUP_COLUMNS.items():
        if column in transition.labels:
            filters[group_column.filter_key] = [transition.labels[column]]
            selected[group_column.filter_group_key] = transition.labels[column]
    if selected and isinstance(filters.get("filterGroup"), dict):
        # The logs scene ignores the field when `filterGroup` selects the same column.
        filters["filterGroup"] = _narrowed(filters["filterGroup"], selected)
    return filters


def _narrowed(node: Any, selected: dict[str, str]) -> Any:
    """A copy of a filter group whose include selections of the `selected` columns hold only their value."""
    if not isinstance(node, dict):
        return node
    if isinstance(node.get("values"), list):
        return {**node, "values": [_narrowed(child, selected) for child in node["values"]]}
    if node.get("type") == "log" and node.get("operator") == "exact" and node.get("key") in selected:
        return {**node, "value": [selected[node["key"]]]}
    return node


_LEGACY_WEBHOOK_TYPES: Final = {
    AlertEventKind.FIRING: "logs_alert.firing",
    AlertEventKind.RESOLVED: "logs_alert.resolved",
    AlertEventKind.ERRORED: "logs_alert.errored",
    AlertEventKind.BROKEN: "logs_alert.auto_disabled",
}


def legacy_logs_webhook_body(
    *,
    project_id: int,
    alert_id: str,
    alert_name: str,
    consecutive_failures: int,
    transition: AnnouncedTransition,
) -> dict[str, Any]:
    """The body the logs alert webhook HogFunction sent, field for field.

    Its template rendered a lone placeholder as the value's own type, so counts stay numbers and
    filter lists stay lists here too.
    """
    transition = in_utc(transition)
    occurred_at = transition.occurred_at
    filters = filters_of(transition.source_config)
    alert_url = logs_alert_url(project_id, alert_id)
    data: dict[str, Any] = {
        "alert_id": alert_id,
        "alert_name": alert_name,
        "service_names": filters.get("serviceNames", []),
        "severity_levels": filters.get("severityLevels", []),
    }
    if transition.kind in (AlertEventKind.FIRING, AlertEventKind.RESOLVED):
        condition = transition.condition
        data |= {
            "result_count": int(transition.value) if transition.value is not None else None,
            "threshold_count": condition["threshold_count"],
            "threshold_operator": condition["threshold_operator"],
            "window_minutes": condition["window_minutes"],
            # The legacy template always added the "?", even with no parameters.
            "logs_url": absolute_uri(f"/project/{project_id}/logs?{_window_params(transition)}"),
        }
    else:
        error_key = "last_error_message" if transition.kind == AlertEventKind.BROKEN else "error_message"
        data |= {"consecutive_failures": consecutive_failures, error_key: transition.error_message or ""}
    data["alert_url"] = alert_url
    return {
        # The HogFunction path sent its event's id. A stable id per transition lets a receiver
        # drop a retried send.
        "id": str(
            uuid5(NAMESPACE_URL, f"{alert_id}|{transition.grouping_key}|{transition.kind}|{occurred_at.isoformat()}")
        ),
        "type": _LEGACY_WEBHOOK_TYPES[transition.kind],
        "timestamp": occurred_at.isoformat(),
        "data": data,
    }
