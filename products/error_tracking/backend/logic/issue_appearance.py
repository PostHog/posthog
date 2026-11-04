"""New and reopened issues, as appearance alerts on the alerts platform.

Error tracking already decides when an issue is new or back, and records it in the issue change
outbox in the transaction that changes the issue. So this store reads the outbox, and the platform
keeps no registry for error tracking.
"""

import datetime as dt
from collections.abc import Mapping
from typing import Any, Final

from django.db.models import Q

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
from products.error_tracking.backend.logic import get_issue_permalink_by_fingerprint
from products.error_tracking.backend.logic.issue_changes import AssigneeRef
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueChange

# An outbox row's `created_at` is set before its transaction commits, so a row can become visible
# after a read past its time. Reading only up to this long ago leaves the transaction time to commit.
COMMIT_ALLOWANCE: Final = dt.timedelta(seconds=30)
# Only an exception reopening a resolved issue counts as a reappearance. A person reopening an
# issue, or one coming out of suppression, is not the error coming back.
REAPPEARS_FROM: Final = frozenset({ErrorTrackingIssue.Status.RESOLVED, ErrorTrackingIssue.Status.PENDING_RELEASE})
FILTER_KEYS: Final = ("severity", "assignee", "name")
ROLLOUT_FLAG: Final = "platform-alerts-source-error-tracking"
ISSUE_CREATED_EVENT: Final = "$error_tracking_issue_created"


class IssueOccurrenceStore:
    def ready_until(self, *, team_id: int, now: dt.datetime) -> dt.datetime:
        return now - COMMIT_ALLOWANCE

    def appeared(self, *, team_id: int, since: dt.datetime, until: dt.datetime, limit: int) -> OccurrenceWindow:
        reappeared = Q(
            kind=ErrorTrackingIssueChange.Kind.STATUS_CHANGED,
            actor_type=ErrorTrackingIssueChange.ActorType.INGESTION,
            snapshot__status=ErrorTrackingIssue.Status.ACTIVE,
            data__previous__in=list(REAPPEARS_FROM),
        )
        rows = list(
            ErrorTrackingIssueChange.objects.for_team(team_id)
            .filter(created_at__gte=since, created_at__lt=until)
            .filter(Q(kind=ErrorTrackingIssueChange.Kind.CREATED) | reappeared)
            .order_by("created_at", "id")
            .values("issue_id", "kind", "snapshot", "created_at")[: limit + 1]
        )
        return OccurrenceWindow(
            occurrences=tuple(_occurrence(row) for row in rows[:limit]), truncated=len(rows) > limit
        )


def _occurrence(row: Mapping[str, Any]) -> Occurrence:
    snapshot = row["snapshot"]
    assignee = AssigneeRef.from_json(snapshot.get("assignee"))
    issue_id = str(row["issue_id"])
    return Occurrence(
        identity_key=issue_id,
        kind=OccurrenceKind.NEW if row["kind"] == ErrorTrackingIssueChange.Kind.CREATED else OccurrenceKind.REAPPEARED,
        first_seen_at=dt.datetime.fromisoformat(snapshot["first_seen"]),
        occurred_at=row["created_at"],
        labels={
            "severity": snapshot.get("severity") or "",
            "assignee": f"{assignee.type}:{assignee.id}" if assignee else "",
            "name": snapshot.get("name") or "",
        },
        detail={"issue_id": issue_id},
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
        data_link=MessageLink(label="View issue", url=get_issue_permalink_by_fingerprint(project_id, issue_id)),
    )
