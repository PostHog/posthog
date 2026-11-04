import uuid
from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest

from parameterized import parameterized

from products.alerts_platform.backend.facade.contracts import OccurrenceKind
from products.cdp.backend.models.hog_functions import HogFunction
from products.error_tracking.backend.logic.issue_appearance import (
    ISSUE_CREATED_EVENT,
    ISSUE_OCCURRENCE_STORE,
    issue_created_destination_warning,
)
from products.error_tracking.backend.models import ErrorTrackingIssueChange

FIRST_SEEN = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)


class TestIssueOccurrenceStore(BaseTest):
    def _change(self, issue_id: uuid.UUID, kind: str, *, previous: str = "", actor: str = "ingestion") -> None:
        ErrorTrackingIssueChange.objects.for_team(self.team.id).create(
            team_id=self.team.id,
            issue_id=issue_id,
            kind=kind,
            data={"previous": previous} if previous else {},
            snapshot={
                "status": "active",
                "severity": "high",
                "name": "TypeError",
                "assignee": None,
                "first_seen": FIRST_SEEN.isoformat(),
            },
            operation_id=uuid.uuid4(),
            actor_type=actor,
            actor_user_id=self.user.id if actor == "user" else None,
        )

    def test_reads_new_issues_and_exceptions_that_reopen_resolved_ones(self) -> None:
        created, reopened, unsuppressed, reopened_by_hand = (uuid.uuid4() for _ in range(4))
        self._change(created, ErrorTrackingIssueChange.Kind.CREATED)
        self._change(reopened, ErrorTrackingIssueChange.Kind.STATUS_CHANGED, previous="resolved")
        self._change(unsuppressed, ErrorTrackingIssueChange.Kind.STATUS_CHANGED, previous="suppressed")
        self._change(reopened_by_hand, ErrorTrackingIssueChange.Kind.STATUS_CHANGED, previous="resolved", actor="user")
        now = datetime.now(UTC)

        window = ISSUE_OCCURRENCE_STORE.appeared(
            team_id=self.team.id, since=now - timedelta(minutes=5), until=now + timedelta(minutes=5), limit=10
        )

        assert [(o.identity_key, o.kind) for o in window.occurrences] == [
            (str(created), OccurrenceKind.NEW),
            (str(reopened), OccurrenceKind.REAPPEARED),
        ]
        # A reopen threads under the issue's first sighting, not under the reopen.
        assert {o.first_seen_at for o in window.occurrences} == {FIRST_SEEN}
        assert window.occurrences[0].labels == {"severity": "high", "assignee": "", "name": "TypeError"}

    @parameterized.expand([("none", None, False), ("enabled", True, True), ("disabled", False, False)])
    def test_warns_when_a_destination_already_posts_new_issues(
        self, _name: str, enabled: bool | None, warned: bool
    ) -> None:
        if enabled is not None:
            HogFunction.objects.create(
                team=self.team,
                name="New issues to Slack",
                type="internal_destination",
                enabled=enabled,
                filters={"events": [{"id": ISSUE_CREATED_EVENT, "type": "events"}]},
            )

        assert (issue_created_destination_warning(self.team.id) is not None) == warned
