from typing import Literal

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.db import DatabaseError
from django.db.models import QuerySet

from parameterized import parameterized
from prometheus_client import REGISTRY

from posthog.models.activity_logging.activity_log import ActivityLog
from posthog.models.organization import OrganizationMembership
from posthog.models.team import Team
from posthog.tasks.email import send_error_tracking_issue_assigned

from products.access_control.backend.facade.testing import create_role
from products.error_tracking.backend.logic import ErrorTrackingIssueNotFoundError
from products.error_tracking.backend.logic.auto_assignment.base import Candidate, Decision, HistoryEvidence
from products.error_tracking.backend.logic.issue_changes import AssigneeRef
from products.error_tracking.backend.logic.issue_mutations import (
    AUTO_ASSIGNMENT_AUTOMATION_ID,
    AUTO_ASSIGNMENT_TRIGGER_JOB_TYPE,
    AutoAssignmentOutcome,
    assign_issue_automatically,
)
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueChange,
)

Who = Literal["nobody", "member", "other_member", "former_member", "role"]

REASON = "Assigned on 3 of the 3 most similar past issues"


def _outcome_count(outcome: AutoAssignmentOutcome) -> float:
    return REGISTRY.get_sample_value("error_tracking_issue_auto_assignment_total", {"outcome": outcome}) or 0.0


class TestAssignIssueAutomatically(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.enterContext(
            patch("products.error_tracking.backend.logic.issue_changes.issue_change_log_enabled", return_value=True)
        )
        self.capture = self.enterContext(
            patch("products.error_tracking.backend.logic.issue_mutations.ph_background_capture")
        ).return_value
        self.sync = self.enterContext(
            patch("products.error_tracking.backend.logic.issue_mutations.sync_issues_to_clickhouse")
        )
        self.email = self.enterContext(patch.object(send_error_tracking_issue_assigned, "delay"))
        self.in_app = self.enterContext(patch("products.error_tracking.backend.notifications.create_notification"))
        self.lifecycle = self.enterContext(
            patch("products.error_tracking.backend.logic.lifecycle_events.produce_internal_event")
        )
        self.issue = ErrorTrackingIssue.objects.create(team=self.team, name="Checkout failed")
        self.other_member = self._create_user("other@example.com")
        self.former_member = self._create_user("former@example.com")
        OrganizationMembership.objects.filter(user=self.former_member, organization=self.organization).delete()
        self.role_id = create_role(organization_id=self.organization.id, name="Backend")

    def _ref(self, who: Who) -> AssigneeRef | None:
        match who:
            case "nobody":
                return None
            case "role":
                return AssigneeRef(type="role", id=str(self.role_id))
            case "member":
                return AssigneeRef(type="user", id=str(self.user.id))
            case "other_member":
                return AssigneeRef(type="user", id=str(self.other_member.id))
            case "former_member":
                return AssigneeRef(type="user", id=str(self.former_member.id))

    def _decision(self, who: Who) -> Decision:
        assignee = self._ref(who)
        assert assignee is not None
        return Decision(
            candidate=Candidate(
                assignee=assignee,
                confidence=1.0,
                source="history",
                reason=REASON,
                evidence=HistoryEvidence(similar_issue_ids=("similar-1", "similar-2"), nearest_distance=0.05),
            ),
            threshold=0.66,
        )

    def _activity(self) -> QuerySet[ActivityLog]:
        return ActivityLog.objects.filter(team_id=self.team.id, scope="ErrorTrackingIssue", item_id=str(self.issue.id))

    @parameterized.expand(
        [
            ("unassigned", "nobody", True, "member", AutoAssignmentOutcome.ASSIGNED, True),
            ("assigned_by_a_person", "other_member", True, "member", AutoAssignmentOutcome.KEPT_EXISTING, False),
            ("assigned_to_a_role", "role", True, "member", AutoAssignmentOutcome.KEPT_EXISTING, False),
            ("assigned_by_rule_no_team", "other_member", False, "member", AutoAssignmentOutcome.KEPT_EXISTING, False),
            ("assigned_on_an_earlier_attempt", "member", True, "member", AutoAssignmentOutcome.KEPT_EXISTING, True),
            ("left_after_write", "former_member", True, "former_member", AutoAssignmentOutcome.KEPT_EXISTING, True),
            ("role_candidate", "nobody", True, "role", AutoAssignmentOutcome.ROLE_SKIPPED, False),
            ("former_member_candidate", "nobody", True, "former_member", AutoAssignmentOutcome.NOT_MEMBER, False),
        ]
    )
    def test_writes_only_a_member_to_an_unassigned_issue(
        self,
        _name: str,
        existing: Who,
        existing_has_team: bool,
        proposed: Who,
        outcome: AutoAssignmentOutcome,
        synced: bool,
    ) -> None:
        existing_ref = self._ref(existing)
        if existing_ref is not None:
            ErrorTrackingIssueAssignment.objects.create(
                issue=self.issue,
                team=self.team if existing_has_team else None,
                user_id=int(existing_ref.id) if existing_ref.type == "user" else None,
                role_id=existing_ref.id if existing_ref.type == "role" else None,
            )
        count_before = _outcome_count(outcome)

        with self.captureOnCommitCallbacks(execute=True):
            result = assign_issue_automatically(self.team.id, self.issue.id, self._decision(proposed))

        assert result == outcome
        assert _outcome_count(outcome) == count_before + 1
        stored = ErrorTrackingIssueAssignment.objects.filter(issue=self.issue).first()
        written = outcome == AutoAssignmentOutcome.ASSIGNED
        assert AssigneeRef.from_assignment(stored) == (self._ref(proposed) if written else existing_ref)
        self.issue.refresh_from_db()
        assert (self.issue.state_updated_at is not None) is written
        assert self._activity().count() == int(written)
        assert ErrorTrackingIssueChange.objects.for_team(self.team.id).count() == int(written)
        assert self.capture.call_count == int(written)
        assert self.sync.called is synced
        self.email.assert_not_called()
        self.in_app.assert_not_called()
        self.lifecycle.assert_not_called()

    def test_records_the_reason_and_the_automation_on_a_write(self) -> None:
        assign_issue_automatically(self.team.id, str(self.issue.id), self._decision("member"))

        activity = self._activity().get()
        assert (activity.user, activity.activity) == (None, "assigned")
        assert activity.detail is not None
        assert activity.detail["trigger"] == {
            "job_type": AUTO_ASSIGNMENT_TRIGGER_JOB_TYPE,
            "job_id": "history",
            "payload": {
                "reason": REASON,
                "confidence": 1.0,
                "threshold": 0.66,
                "similar_issue_ids": ["similar-1", "similar-2"],
            },
        }
        change = ErrorTrackingIssueChange.objects.for_team(self.team.id).get()
        assert (change.kind, change.data, change.snapshot["assignee"]) == (
            "assignee_changed",
            {"previous": None},
            {"type": "user", "id": str(self.user.id)},
        )
        assert (change.actor_type, change.actor_automation_id) == ("automation", AUTO_ASSIGNMENT_AUTOMATION_ID)
        self.capture.assert_called_once()
        assert self.capture.call_args.kwargs["distinct_id"] == str(self.team.uuid)
        assert self.capture.call_args.kwargs["event"] == "error_tracking_issue_auto_assigned"
        assert self.capture.call_args.kwargs["properties"] == {
            "issue_id": str(self.issue.id),
            "assignee_type": "user",
            "source": "history",
            "confidence": 1.0,
            "threshold": 0.66,
        }

    def test_writes_nothing_to_an_issue_in_another_team(self) -> None:
        other_team = Team.objects.create(organization=self.organization)

        with self.assertRaises(ErrorTrackingIssueNotFoundError):
            assign_issue_automatically(other_team.id, self.issue.id, self._decision("member"))

        assert not ErrorTrackingIssueAssignment.objects.filter(issue=self.issue).exists()

    def test_rolls_the_assignment_back_when_its_reason_cannot_be_recorded(self) -> None:
        # Test settings raise every activity write failure at once, so strict and deferred writes look the same.
        # Production settings defer a non-strict write to the commit, so this fails if the write stops being strict.
        with (
            self.settings(TEST=False, ACTIVITY_LOG_TRANSACTION_MANAGEMENT=True),
            patch.object(ActivityLog.objects, "create", side_effect=DatabaseError),
            self.assertRaises(DatabaseError),
        ):
            assign_issue_automatically(self.team.id, self.issue.id, self._decision("member"))

        assert not ErrorTrackingIssueAssignment.objects.filter(issue=self.issue).exists()
        assert not ErrorTrackingIssueChange.objects.for_team(self.team.id).exists()
