"""How a warehouse sync alert reads in a platform notification.

A describer runs on the send path and does no I/O, so everything a message names travels on the
transition: the evaluation puts the names and the error in the group's labels.

Imported from `ready()`, so it stays light: no models, no query layer.
"""

from typing import Any, Final, Literal
from uuid import UUID

from posthog.utils import absolute_uri

from products.alerts_platform.backend.facade.contracts import (
    AnnouncedTransition,
    MessageDetail,
    MessageLink,
    SourceDescription,
)

GroupBy = Literal["schema", "source"]
GROUP_BY_KEY: Final = "group_by"
DEFAULT_GROUP_BY: Final[GroupBy] = "source"

# The result label each `group_by` keys its groups on, which the alert's grouping must name.
SCHEMA_ID_KEY: Final = "schema_id"
SOURCE_ID_KEY: Final = "source_id"
DESTINATION_ID_KEY: Final = "destination_id"
GROUPING_KEY_BY_GROUP_BY: Final[dict[GroupBy, str]] = {"schema": SCHEMA_ID_KEY, "source": SOURCE_ID_KEY}

# The platform keeps at most four labels per group, so each kind uses exactly four.
SOURCE_LABEL: Final = "source"
SCHEMA_LABEL: Final = "schema"
REASON_LABEL: Final = "reason"
DESTINATION_LABEL: Final = "destination"
DESTINATION_TYPE_LABEL: Final = "destination_type"
STATUS_LABEL: Final = "status"


def sources_url(team_id: int) -> str:
    return absolute_uri(f"/project/{team_id}/data-management/sources")


def source_url(team_id: int, source_id: str) -> str:
    return absolute_uri(f"/project/{team_id}/data-management/sources/managed-{source_id}/syncs")


def destinations_url(team_id: int) -> str:
    return absolute_uri(f"/project/{team_id}/data-management/warehouse-destinations")


def destination_url(team_id: int, destination_id: str) -> str:
    return absolute_uri(f"/project/{team_id}/data-management/warehouse-destinations?destination={destination_id}")


def source_alerts_url(team_id: int, _configuration_id: UUID) -> str:
    """Where a warehouse sync alert's messages link. The alert has no page of its own yet."""
    return sources_url(team_id)


def destination_alerts_url(team_id: int, _configuration_id: UUID) -> str:
    return destinations_url(team_id)


def group_by_of(source_config: dict[str, Any]) -> GroupBy:
    return "schema" if source_config.get(GROUP_BY_KEY) == "schema" else DEFAULT_GROUP_BY


def describe_source_transition(*, project_id: int, transition: AnnouncedTransition) -> SourceDescription:
    labels = transition.labels
    per_source = group_by_of(transition.source_config) == "source"
    details = [
        MessageDetail(label=label, value=labels[key])
        for label, key in (
            ("Source", SOURCE_LABEL),
            ("Failing tables" if per_source else "Table", SCHEMA_LABEL),
            ("Error", REASON_LABEL),
        )
        if labels.get(key)
    ]
    source_id = labels.get(SOURCE_ID_KEY)
    link = (
        MessageLink(label="View source", url=source_url(project_id, source_id))
        if source_id
        else MessageLink(label="View sources", url=sources_url(project_id))
    )
    return SourceDescription(details=tuple(details), data_link=link)


def describe_destination_transition(*, project_id: int, transition: AnnouncedTransition) -> SourceDescription:
    labels = transition.labels
    details = [
        MessageDetail(label=label, value=labels[key])
        for label, key in (
            ("Destination", DESTINATION_LABEL),
            ("Type", DESTINATION_TYPE_LABEL),
            ("Status", STATUS_LABEL),
            ("Error", REASON_LABEL),
        )
        if labels.get(key)
    ]
    link = (
        MessageLink(label="View destination", url=destination_url(project_id, transition.grouping_key))
        if transition.grouping_key
        else MessageLink(label="View destinations", url=destinations_url(project_id))
    )
    return SourceDescription(details=tuple(details), data_link=link)
