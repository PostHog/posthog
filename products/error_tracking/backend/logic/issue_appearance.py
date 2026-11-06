"""New and reopened issues, as appearance alerts on the alerts platform.

Error tracking's lifecycle workflows record each new and reopened issue in the platform's occurrence
registry, through `record_issue_occurrence`. This module words those alerts and checks their settings.
"""

from typing import Final

from posthog.utils import absolute_uri

from products.alerts_platform.backend.facade.appearance import appearance_source_config
from products.alerts_platform.backend.facade.contracts import (
    APPEARANCE_DETAIL_KEY,
    AnnouncedTransition,
    MessageDetail,
    MessageLink,
    OccurrenceKind,
    SourceConfigSpec,
    SourceDescription,
)
from products.error_tracking.backend.logic import build_issue_permalink_path

FILTER_KEYS: Final = ("severity", "assignee", "name")
ROLLOUT_FLAG: Final = "platform-alerts-source-error-tracking"
ISSUE_CREATED_EVENT: Final = "$error_tracking_issue_created"


def issue_created_destination_warning(team_id: int) -> str | None:
    """Error tracking's own destinations and a platform alert are separate, so both post about each new issue."""
    # Imported here, because this module loads in `ready()` and the destinations layer must stay off that path.
    from products.cdp.backend.facade.api import has_enabled_destination_for_internal_event  # noqa: PLC0415

    if not has_enabled_destination_for_internal_event(team_id=team_id, event=ISSUE_CREATED_EVENT):
        return None
    return (
        "This project already has an error tracking destination for new issues. "
        "It keeps posting, so each new issue is announced by both."
    )


def load_issue_appearance_source_config() -> SourceConfigSpec:
    return appearance_source_config(
        name="ErrorTrackingIssueAppearance",
        filter_keys=FILTER_KEYS,
        rollout_flag=ROLLOUT_FLAG,
        create_warning=issue_created_destination_warning,
    )


def describe_issue_appearance(*, project_id: int, transition: AnnouncedTransition) -> SourceDescription:
    labels = transition.labels
    name = labels.get("name") or "Unnamed issue"
    back = transition.source_detail.get(APPEARANCE_DETAIL_KEY) == OccurrenceKind.REAPPEARED.value
    details = [MessageDetail(label="Issue", value=name)]
    if labels.get("severity"):
        details.append(MessageDetail(label="Severity", value=labels["severity"]))
    if first_seen := transition.source_detail.get("first_seen_at"):
        details.append(MessageDetail(label="First seen", value=str(first_seen)))
    issue_id = transition.source_detail.get("issue_id", "")
    return SourceDescription(
        headline=f"{'Resolved issue is back' if back else 'New issue'}: {name}",
        details=tuple(details),
        # A link by fingerprint survives a merge, and an issue's thread outlives many of them.
        data_link=MessageLink(
            label="View issue",
            url=absolute_uri(
                build_issue_permalink_path(
                    project_id=project_id,
                    issue_id=issue_id,
                    fingerprint=transition.source_detail.get("fingerprint"),
                )
            ),
        ),
    )
