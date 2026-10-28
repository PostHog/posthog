"""How a metrics alert reads in a platform notification.

A describer runs on the send path and does no I/O, so everything a message names travels on the
transition: the series labels are the group's labels.

Imported from `ready()`, so it stays light: no models, no query layer.
"""

from typing import Final
from uuid import UUID

from posthog.utils import absolute_uri

from products.alerts_platform.backend.facade.contracts import (
    AnnouncedTransition,
    MessageDetail,
    MessageLink,
    SourceDescription,
)

OPERATOR_SYMBOLS: Final[dict[str, str]] = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "eq": "==", "ne": "!="}


def metrics_url(team_id: int) -> str:
    return absolute_uri(f"/project/{team_id}/metrics")


def alert_url(team_id: int, _configuration_id: UUID) -> str:
    """Where a metrics alert's messages link. The alert has no page of its own yet."""
    return metrics_url(team_id)


def describe_transition(*, project_id: int, transition: AnnouncedTransition) -> SourceDescription:
    details = [MessageDetail(label="Query", value=str(transition.source_config.get("query", "")))]
    if transition.value is not None:
        details.append(MessageDetail(label="Value", value=f"{transition.value:g}"))
    condition = transition.condition
    if condition.get("kind", "threshold") == "threshold" and "threshold" in condition:
        details.append(
            MessageDetail(
                label="Threshold",
                value=f"{OPERATOR_SYMBOLS.get(str(condition.get('operator')), condition.get('operator'))} {condition['threshold']:g}",
            )
        )
    context = (
        (", ".join(f"{key}={value}" for key, value in sorted(transition.labels.items())),) if transition.labels else ()
    )
    return SourceDescription(
        details=tuple(details),
        context=context,
        data_link=MessageLink(label="View metrics", url=metrics_url(project_id)),
    )
