"""How an error tracking alert reads in a platform notification.

A describer runs on the send path and does no I/O, so everything a message names travels on the
transition: the group's labels name the issue and the change, and its source detail carries the
fingerprint the link uses.

Imported from `ready()`, so it stays light: no models, no query layer.
"""

from typing import Final
from urllib.parse import quote
from uuid import UUID

from posthog.utils import absolute_uri

from products.alerts_platform.backend.facade.contracts import (
    AnnouncedTransition,
    MessageDetail,
    MessageLink,
    SourceDescription,
)

# The labels an evaluation puts on each group. The issue id is the grouping key.
ISSUE_ID_LABEL: Final = "issue_id"
ISSUE_NAME_LABEL: Final = "issue_name"
TRIGGER_LABEL: Final = "trigger"
# In the group's source detail, because a fingerprint is not something an alert filters or groups on.
FINGERPRINT_DETAIL: Final = "fingerprint"

_TRIGGER_WORDS: Final[dict[str, str]] = {
    "issue_created": "New issue",
    "issue_reopened": "Reopened",
    "issue_assigned": "Assigned",
}


def error_tracking_url(team_id: int) -> str:
    return absolute_uri(f"/project/{team_id}/error-tracking")


def alert_url(team_id: int, _configuration_id: UUID) -> str:
    """Where an error tracking alert's messages link. The alert has no page of its own yet."""
    return error_tracking_url(team_id)


def issue_url(project_id: int, issue_id: str, fingerprint: str | None) -> str:
    # A link by fingerprint survives a merge, which a link by issue id does not.
    if fingerprint:
        return absolute_uri(f"/project/{project_id}/error-tracking/fingerprint/{quote(fingerprint, safe='')}")
    return absolute_uri(f"/project/{project_id}/error-tracking/{issue_id}")


def describe_transition(*, project_id: int, transition: AnnouncedTransition) -> SourceDescription:
    labels = transition.labels
    details = [MessageDetail(label="Issue", value=labels.get(ISSUE_NAME_LABEL) or "Unnamed issue")]
    trigger = labels.get(TRIGGER_LABEL)
    if trigger:
        details.append(MessageDetail(label="Change", value=_TRIGGER_WORDS.get(trigger, trigger)))
    issue_id = labels.get(ISSUE_ID_LABEL) or transition.grouping_key
    if not issue_id:
        return SourceDescription(
            details=tuple(details),
            data_link=MessageLink(label="View issues", url=error_tracking_url(project_id)),
        )
    fingerprint = transition.source_detail.get(FINGERPRINT_DETAIL)
    return SourceDescription(
        details=tuple(details),
        data_link=MessageLink(
            label="View issue",
            url=issue_url(project_id, issue_id, fingerprint if isinstance(fingerprint, str) else None),
        ),
    )
