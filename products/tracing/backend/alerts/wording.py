"""How a traces alert reads in a platform notification.

A describer runs on the send path and does no I/O, so everything a message names travels on the
transition: the group's labels are its service and operation.

Imported from `ready()`, so it stays light: no models, no query layer.
"""

from collections.abc import Callable, Mapping
from typing import Any, Final
from uuid import UUID

from posthog.utils import absolute_uri

from products.alerts_platform.backend.facade.contracts import (
    AnnouncedTransition,
    MessageDetail,
    MessageLink,
    SourceDescription,
)
from products.tracing.backend.alerts.group_columns import GROUP_COLUMNS

# Each measure's name, and how a value in its unit reads: a count, a share, or milliseconds.
_MEASURES: Final[dict[str, tuple[str, Callable[[float], str]]]] = {
    "request_count": ("Requests", lambda value: f"{value:g}"),
    "error_count": ("Errors", lambda value: f"{value:g}"),
    "error_rate": ("Error rate", lambda value: f"{value * 100:g}%"),
    "latency": ("latency", lambda value: f"{value:g} ms"),
}


def tracing_url(team_id: int) -> str:
    return absolute_uri(f"/project/{team_id}/tracing")


def alert_url(team_id: int, _configuration_id: UUID) -> str:
    """Where a traces alert's messages link. The alert has no page of its own yet."""
    return tracing_url(team_id)


def measure_label(condition: Mapping[str, Any]) -> str:
    measure = str(condition.get("measure", ""))
    label = _MEASURES[measure][0] if measure in _MEASURES else measure
    return f"p{condition.get('percentile')} {label}" if measure == "latency" else label


def format_measured(condition: Mapping[str, Any], value: float) -> str:
    measure = str(condition.get("measure", ""))
    return _MEASURES[measure][1](value) if measure in _MEASURES else f"{value:g}"


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
    context = tuple(f"{GROUP_COLUMNS.get(key, key)}: {value}" for key, value in sorted(transition.labels.items()))
    return SourceDescription(
        details=tuple(details),
        context=context,
        data_link=MessageLink(label="View traces", url=tracing_url(project_id)),
    )
