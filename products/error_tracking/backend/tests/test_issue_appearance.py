from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models.scoping import team_scope

from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.contracts import APPEARANCE_GROUPING, SourceKind
from products.cdp.backend.models.hog_functions import HogFunction
from products.error_tracking.backend.logic.issue_appearance import (
    ISSUE_CREATED_EVENT,
    issue_created_destination_warning,
)
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueFingerprintV2
from products.error_tracking.backend.temporal.lifecycle.issue_reopened.types import IssueReopenedWorkflowInputs
from products.error_tracking.backend.temporal.lifecycle.side_effects import record_issue_occurrence
from products.error_tracking.backend.temporal.lifecycle.types import LifecycleIssueSnapshot

FIRST_SEEN = datetime(2026, 11, 4, 9, 0, tzinfo=UTC)
REOPENED = datetime(2026, 11, 4, 10, 0, tzinfo=UTC)


class TestIssueOccurrence(BaseTest):
    def _inputs(self, issue: ErrorTrackingIssue, at: datetime) -> IssueReopenedWorkflowInputs:
        return IssueReopenedWorkflowInputs(
            notification_id="notification-1",
            team_id=self.team.id,
            issue_id=str(issue.id),
            issue=LifecycleIssueSnapshot(
                name="TypeError",
                description=None,
                status="active",
                created_at=issue.created_at.isoformat(),
                severity="high",
            ),
            fingerprint="fp-1",
            event_uuid="event-1",
            event_timestamp=at.isoformat(),
        )

    def test_a_reopen_records_once_at_the_exception_time_threaded_on_first_sight(self) -> None:
        with team_scope(self.team.id):
            platform_testing.create_configuration(
                team_id=self.team.id,
                name="Issues back",
                source_kind=SourceKind.ERROR_TRACKING.value,
                alert_kind="appearance",
                grouping=APPEARANCE_GROUPING.to_stored(),
                check_interval_minutes=1,
                owner="platform",
            )
        issue = ErrorTrackingIssue.objects.create(team=self.team, name="TypeError")
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint="fp-1")
        # `first_seen` is set on insert, so it is dated afterwards.
        ErrorTrackingIssueFingerprintV2.objects.filter(issue=issue).update(first_seen=FIRST_SEEN)

        # A retried activity records the same fact twice, and an older reopen arriving late changes nothing.
        for at in (REOPENED, REOPENED, REOPENED - timedelta(minutes=30)):
            assert record_issue_occurrence(self._inputs(issue, at), reopened=True)

        (row,) = platform_testing.occurrences(self.team.id, SourceKind.ERROR_TRACKING)
        assert (row.identity_key, row.first_seen_at, row.reappeared_at) == (str(issue.id), FIRST_SEEN, REOPENED)
        assert row.detail["fingerprint"] == "fp-1"

    def test_a_project_without_an_appearance_alert_records_nothing(self) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team, name="TypeError")

        assert not record_issue_occurrence(self._inputs(issue, REOPENED), reopened=False)
        assert platform_testing.occurrences(self.team.id, SourceKind.ERROR_TRACKING) == []

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
