"""How a traces alert reads in a platform notification.

A describer runs on the send path and does no I/O, so everything a message names travels on the
transition: the group's labels are its service and operation.

Imported from `ready()`, so it stays light: no models, no query layer.
"""

from collections.abc import Mapping
from typing import Any, Final
from uuid import UUID

from posthog.utils import absolute_uri

from products.alerts_platform.backend.facade.contracts import (
    AnnouncedTransition,
    MessageDetail,
    MessageLink,
    SourceDescription,
)

GROUP_LABELS: Final[dict[str, str]] = {"service_name": "Service", "name": "Operation"}
_COUNT_MEASURES: Final[dict[str, str]] = {"request_count": "Requests", "error_count": "Errors"}


def tracing_url(team_id: int) -> str:
    return absolute_uri(f"/project/{team_id}/tracing")


def alert_url(team_id: int, _configuration_id: UUID) -> str:
    """Where a traces alert's messages link. The alert has no page of its own yet."""
    return tracing_url(team_id)


def measure_label(condition: Mapping[str, Any]) -> str:
    measure = str(condition.get("measure", ""))
    if measure == "latency":
        return f"p{condition.get('percentile')} latency"
    if measure == "error_rate":
        return "Error rate"
    return _COUNT_MEASURES.get(measure, measure)


def format_measured(condition: Mapping[str, Any], value: float) -> str:
    """A value in the measure's own unit: milliseconds, a percentage, or a count."""
    measure = condition.get("measure")
    if measure == "latency":
        return f"{value:g} ms"
    if measure == "error_rate":
        return f"{value * 100:g}%"
    return f"{value:g}"


def describe_transition(*, project_id: int, transition: AnnouncedTransition) -> SourceDescription:
    condition = transition.condition
    details = [MessageDetail(label="Measure", value=measure_label(condition))]
    if transition.value is not None:
        details.append(MessageDetail(label="Value", value=format_measured(condition, transition.value)))
    if "threshold" in condition:
        details.append(
            MessageDetail(
                label="Threshold",
                value=f"{condition.get('threshold_operator')} {format_measured(condition, float(condition['threshold']))}",
            )
        )
    if "window_minutes" in condition:
        details.append(MessageDetail(label="Window", value=f"{condition['window_minutes']} minutes"))
    context = tuple(f"{GROUP_LABELS.get(key, key)}: {value}" for key, value in sorted(transition.labels.items()))
    return SourceDescription(
        details=tuple(details),
        context=context,
        data_link=MessageLink(label="View traces", url=tracing_url(project_id)),
    )
