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
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueFingerprintV2

FIRST_SEEN = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)


class TestIssueOccurrenceStore(BaseTest):
    def test_reads_new_active_issues_at_their_first_sighting_with_a_durable_fingerprint(self) -> None:
        new = ErrorTrackingIssue.objects.create(team=self.team, name="TypeError", severity="high")
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=new, fingerprint="fp-1")
        # `first_seen` is set on insert, so it is dated afterwards.
        ErrorTrackingIssueFingerprintV2.objects.filter(issue=new).update(first_seen=FIRST_SEEN)
        ErrorTrackingIssue.objects.create(team=self.team, name="Resolved at once", status="resolved")
        now = datetime.now(UTC)

        window = ISSUE_OCCURRENCE_STORE.appeared(
            team_id=self.team.id, since=now - timedelta(minutes=5), until=now + timedelta(minutes=5), limit=10
        )

        (occurrence,) = window.occurrences
        assert (occurrence.identity_key, occurrence.kind, occurrence.first_seen_at) == (
            str(new.id),
            OccurrenceKind.NEW,
            FIRST_SEEN,
        )
        assert occurrence.labels == {"severity": "high", "assignee": "", "name": "TypeError"}
        assert occurrence.detail["fingerprint"] == "fp-1"

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
