from uuid import UUID

import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import User
from posthog.models.instance_setting import set_instance_setting
from posthog.tasks.email import send_error_tracking_issue_assigned
from posthog.tasks.test.utils_email_tests import mock_email_messages

from products.access_control.backend.facade.testing import add_role_member, create_role
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueAssignment
from products.error_tracking.backend.notifications import (
    AssignmentActor,
    _AssignerExcludingResolver,
    dispatch_issue_assigned_realtime,
)
from products.notifications.backend.facade.enums import TargetType


class _AssignmentTestBase(BaseTest):
    def setUp(self):
        super().setUp()
        self.assigner = self.user
        self.assignee = User.objects.create_and_join(self.organization, "assignee@test.com", "password")
        self.issue = ErrorTrackingIssue.objects.create(team=self.team, name="Some Error", description="boom")

    def _create_assignment(self, assignee_type: str) -> tuple[ErrorTrackingIssueAssignment, int | UUID]:
        if assignee_type == "user":
            assignment = ErrorTrackingIssueAssignment.objects.create(
                team=self.team, issue=self.issue, user=self.assignee
            )
            return assignment, self.assignee.id
        role_id = create_role(organization_id=self.organization.id, name="Devs")
        add_role_member(role_id=role_id, user_id=self.assigner.id)
        add_role_member(role_id=role_id, user_id=self.assignee.id)
        return ErrorTrackingIssueAssignment.objects.create(team=self.team, issue=self.issue, role_id=role_id), role_id


class TestDispatchIssueAssignedRealtime(_AssignmentTestBase):
    @patch("products.error_tracking.backend.notifications.create_notification")
    def test_user_assignment_dispatches_to_assignee(self, mock_create_notification):
        assignment = ErrorTrackingIssueAssignment.objects.create(team=self.team, issue=self.issue, user=self.assignee)
        dispatch_issue_assigned_realtime(
            assignment=assignment,
            assignee={"type": "user", "id": self.assignee.id},
            actor=AssignmentActor.from_user(self.assigner),
        )
        mock_create_notification.assert_called_once()
        data = mock_create_notification.call_args.args[0]
        assert data.target_type == TargetType.USER
        assert data.target_id == str(self.assignee.id)
        assert data.resource_type == "error_tracking"
        assert data.resource_id == str(self.issue.id)
        assert data.title == f"{self.assigner.email} assigned an issue to you"
        assert data.metadata == {"trigger": "manual"}

    @patch("products.error_tracking.backend.notifications.create_notification")
    def test_user_self_assignment_does_not_dispatch(self, mock_create_notification):
        assignment = ErrorTrackingIssueAssignment.objects.create(team=self.team, issue=self.issue, user=self.assigner)
        dispatch_issue_assigned_realtime(
            assignment=assignment,
            assignee={"type": "user", "id": self.assigner.id},
            actor=AssignmentActor.from_user(self.assigner),
        )
        mock_create_notification.assert_not_called()

    @patch("products.error_tracking.backend.notifications.create_notification")
    def test_role_assignment_uses_role_target_with_assigner_excluding_resolver(self, mock_create_notification):
        role_id = create_role(organization_id=self.organization.id, name="Devs")
        assignment = ErrorTrackingIssueAssignment.objects.create(team=self.team, issue=self.issue, role_id=role_id)
        dispatch_issue_assigned_realtime(
            assignment=assignment,
            assignee={"type": "role", "id": role_id},
            actor=AssignmentActor.from_user(self.assigner),
        )
        mock_create_notification.assert_called_once()
        data = mock_create_notification.call_args.args[0]
        assert data.target_type == TargetType.ROLE
        assert data.target_id == str(role_id)
        assert isinstance(data.resolver, _AssignerExcludingResolver)
        assert data.resolver._assigner_id == self.assigner.id

    @parameterized.expand([("user",), ("role",)])
    @patch("products.error_tracking.backend.notifications.create_notification")
    def test_automatic_assignment_dispatches_without_assigner(self, assignee_type, mock_create_notification):
        assignment, assignee_id = self._create_assignment(assignee_type)
        # Cymbal writes rule assignments without team_id.
        ErrorTrackingIssueAssignment.objects.filter(id=assignment.id).update(team=None)
        assignment.refresh_from_db()
        dispatch_issue_assigned_realtime(
            assignment=assignment,
            assignee={"type": assignee_type, "id": assignee_id},
            actor=AssignmentActor.automatic("An assignment rule"),
        )
        mock_create_notification.assert_called_once()
        data = mock_create_notification.call_args.args[0]
        assert data.team_id == self.team.id
        assert data.target_id == str(assignee_id)
        assert data.title == "An assignment rule assigned an issue to you"
        assert data.metadata == {"trigger": "automatic"}
        assert data.resolver is None

    @patch("products.error_tracking.backend.notifications.create_notification", side_effect=RuntimeError("boom"))
    def test_dispatch_failure_is_swallowed(self, _mock_create_notification):
        assignment = ErrorTrackingIssueAssignment.objects.create(team=self.team, issue=self.issue, user=self.assignee)
        dispatch_issue_assigned_realtime(
            assignment=assignment,
            assignee={"type": "user", "id": self.assignee.id},
            actor=AssignmentActor.from_user(self.assigner),
        )


class TestAssignmentActor(SimpleTestCase):
    def test_rejects_empty_label(self):
        with pytest.raises(ValueError):
            AssignmentActor.automatic("")


class TestAssignerExcludingResolver(SimpleTestCase):
    @parameterized.expand(
        [
            ("excludes_assigner_present", [10, 20, 30], 20, [10, 30]),
            ("noop_when_assigner_absent", [10, 30], 20, [10, 30]),
            ("removes_only_matching_id", [20, 20, 30], 20, [30]),
        ]
    )
    @patch("products.notifications.backend.resolvers.RecipientsResolver.resolve")
    def test_resolver_filters_assigner(self, _name, resolved_ids, assigner_id, expected, mock_super_resolve):
        mock_super_resolve.return_value = resolved_ids
        resolver = _AssignerExcludingResolver(assigner_id=assigner_id)
        result = resolver.resolve(TargetType.ROLE, "1", team_id=1)
        assert result == expected


@patch("posthog.tasks.email.EmailMessage")
class TestSendIssueAssignedEmail(_AssignmentTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        set_instance_setting("EMAIL_HOST", "fake_host")
        set_instance_setting("EMAIL_ENABLED", True)

    def setUp(self):
        super().setUp()
        self.assigner.first_name = "Alice"
        self.assigner.save()

    @parameterized.expand(
        [
            ("manual_user", "user", False, ["assignee"]),
            ("automatic_user", "user", True, ["assignee"]),
            ("manual_role_excludes_assigner", "role", False, ["assignee"]),
            ("automatic_role_excludes_nobody", "role", True, ["assignee", "assigner"]),
        ]
    )
    def test_sends_to_assignee(self, MockEmailMessage: MagicMock, _name, assignee_type, automatic, expected_recipients):
        mocked_email_messages = mock_email_messages(MockEmailMessage)
        assignment, _ = self._create_assignment(assignee_type)

        if automatic:
            send_error_tracking_issue_assigned(assignment.id, None, assigned_by="An assignment rule")
        else:
            send_error_tracking_issue_assigned(assignment.id, self.assigner.id)

        assert len(mocked_email_messages) == 1
        message = mocked_email_messages[0]
        emails = {"assignee": self.assignee.email, "assigner": self.assigner.email}
        assert sorted(to["raw_email"] for to in message.to) == sorted(emails[key] for key in expected_recipients)
        if automatic:
            assert "An assignment rule assigned you" in message.html_body
            assert message.campaign_key.startswith(f"error_tracking_issue_assigned_automatic_{assignment.id}_")
        else:
            assert "Alice</b> has assigned you" in message.html_body
            assert message.campaign_key.startswith(f"error_tracking_issue_assigned_{assignment.id}_")

    def test_rejects_missing_assigner_and_label(self, MockEmailMessage: MagicMock):
        assignment, _ = self._create_assignment("user")

        with pytest.raises(ValueError):
            send_error_tracking_issue_assigned(assignment.id, None)

        MockEmailMessage.assert_not_called()
