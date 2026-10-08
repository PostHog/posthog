"""How a logs alert reads in a native platform notification.

The platform words a message generically ("Value: 11"). This gives it the logs wording the legacy
messages use: a count of logs in a window, the filters the alert watches, and a link to the logs.

Imported from `ready()`, so it stays light: no models, no query layer.
"""

from datetime import timedelta
from typing import Any

from posthog.utils import absolute_uri

from products.alerts_platform.backend.facade.contracts import (
    AlertEventKind,
    AnnouncedTransition,
    MessageDetail,
    MessageLink,
    SourceDescription,
)
from products.logs.backend.logs_url_params import build_logs_url_params

# Where the platform keeps the bound inside `source_config`. Every other key is a logs filter.
_CONDITION_KEY = "condition"

# A resolve reports the count that ended the firing, so it is not a breach. A held check, which
# only moves a paging incident, can be either, so it gets a neutral label.
_LABELS = {
    AlertEventKind.FIRING: "Threshold breached",
    AlertEventKind.RESOLVED: "Current count",
}


def describe_logs_transition(*, project_id: int, transition: AnnouncedTransition) -> SourceDescription:
    filters = {key: value for key, value in transition.source_config.items() if key != _CONDITION_KEY}
    window_minutes: int = transition.condition["window_minutes"]
    return SourceDescription(
        details=_details(transition, window_minutes),
        context=_context(filters),
        data_link=MessageLink(label="View logs", url=_logs_url(project_id, filters, transition, window_minutes)),
    )


def _details(transition: AnnouncedTransition, window_minutes: int) -> tuple[MessageDetail, ...]:
    if transition.value is None:
        return ()
    condition = transition.condition
    count = f"{transition.value:g}"
    noun = "log" if count == "1" else "logs"
    summary = (
        f"{count} {noun} in {window_minutes}m "
        f"(threshold: {condition['threshold_operator']} {condition['threshold_count']})"
    )
    return (MessageDetail(label=_LABELS.get(transition.kind, "Count"), value=summary),)


def _context(filters: dict[str, Any]) -> tuple[str, ...]:
    lines: list[str] = []
    severity_levels = filters.get("severityLevels") or []
    service_names = filters.get("serviceNames") or []
    if severity_levels:
        lines.append("Severity: " + ", ".join(severity_levels))
    if service_names:
        lines.append("Services: " + ", ".join(service_names))
    return tuple(lines) or ("All log levels and services",)


def _logs_url(project_id: int, filters: dict[str, Any], transition: AnnouncedTransition, window_minutes: int) -> str:
    # The window the check counted, so the link opens on the logs that decided it.
    date_to = transition.occurred_at
    date_from = date_to - timedelta(minutes=window_minutes)
    params = build_logs_url_params(filters, date_from=date_from, date_to=date_to)
    return absolute_uri(f"/project/{project_id}/logs" + (f"?{params}" if params else ""))
