"""New issues, as appearance alerts on the alerts platform.

Ingestion creates an issue row the moment it sees a new exception, so this store reads the issue table,
and the platform keeps no registry for error tracking.
"""

import datetime as dt
from collections.abc import Sequence
from typing import Any, Final

from posthog.utils import absolute_uri

from products.alerts_platform.backend.facade.appearance import appearance_source_config
from products.alerts_platform.backend.facade.contracts import (
    APPEARANCE_DETAIL_KEY,
    AnnouncedTransition,
    MessageDetail,
    MessageLink,
    Occurrence,
    OccurrenceKind,
    OccurrenceWindow,
    SourceConfigSpec,
    SourceDescription,
)
from products.error_tracking.backend.logic import build_issue_permalink_path
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueFingerprintV2,
)

# An issue row's `created_at` is set before its transaction commits, so a row can become visible
# after a read past its time. Reading only up to this long ago leaves the transaction time to commit.
COMMIT_ALLOWANCE: Final = dt.timedelta(seconds=30)
FILTER_KEYS: Final = ("severity", "assignee", "name")
ROLLOUT_FLAG: Final = "platform-alerts-source-error-tracking"
ISSUE_CREATED_EVENT: Final = "$error_tracking_issue_created"


class IssueOccurrenceStore:
    def ready_until(self, *, team_id: int, now: dt.datetime) -> dt.datetime:
        return now - COMMIT_ALLOWANCE

    def appeared(self, *, team_id: int, since: dt.datetime, until: dt.datetime, limit: int) -> OccurrenceWindow:
        # Active, because ingestion creates an issue active, and the per-team created index covers only those.
        # An issue resolved within a check of its creation is not announced.
        issues = list(
            ErrorTrackingIssue.objects.with_first_seen()
            .filter(
                team_id=team_id, status=ErrorTrackingIssue.Status.ACTIVE, created_at__gte=since, created_at__lt=until
            )
            .order_by("created_at", "id")
            .values("id", "name", "severity", "created_at", "first_seen")[: limit + 1]
        )
        shown = issues[:limit]
        ids = [issue["id"] for issue in shown]
        assignees = {
            assignment.issue_id: f"user:{assignment.user_id}" if assignment.user_id else f"role:{assignment.role_id}"
            for assignment in ErrorTrackingIssueAssignment.objects.filter(issue_id__in=ids)
        }
        fingerprints = _first_fingerprints(ids)
        return OccurrenceWindow(
            occurrences=tuple(_occurrence(issue, assignees, fingerprints) for issue in shown),
            truncated=len(issues) > limit,
        )


def _first_fingerprints(issue_ids: Sequence[Any]) -> dict[Any, str]:
    """Each issue's oldest fingerprint, which a merge keeps, so a link by it outlives the issue row."""
    rows = (
        ErrorTrackingIssueFingerprintV2.objects.filter(issue_id__in=issue_ids)
        .order_by("issue_id", "created_at")
        .distinct("issue_id")
        .values_list("issue_id", "fingerprint")
    )
    return dict(rows)


def _occurrence(issue: dict[str, Any], assignees: dict[Any, str], fingerprints: dict[Any, str]) -> Occurrence:
    issue_id = str(issue["id"])
    detail: dict[str, Any] = {"issue_id": issue_id}
    if fingerprint := fingerprints.get(issue["id"]):
        detail["fingerprint"] = fingerprint
    return Occurrence(
        identity_key=issue_id,
        kind=OccurrenceKind.NEW,
        first_seen_at=issue["first_seen"] or issue["created_at"],
        occurred_at=issue["created_at"],
        labels={
            "severity": issue["severity"] or "",
            "assignee": assignees.get(issue["id"], ""),
            "name": issue["name"] or "",
        },
        detail=detail,
    )


ISSUE_OCCURRENCE_STORE: Final = IssueOccurrenceStore()


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
