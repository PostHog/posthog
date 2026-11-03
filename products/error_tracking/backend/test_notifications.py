from uuid import UUID

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import User
from posthog.models.instance_setting import set_instance_setting
from posthog.tasks.email import send_error_tracking_issue_assigned
from posthog.tasks.test.utils_email_tests import mock_email_messages

from products.access_control.backend.facade.testing import create_role
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueAssignment
from products.error_tracking.backend.notifications import _AssignerExcludingResolver, dispatch_issue_assigned_realtime
from products.notifications.backend.facade.enums import TargetType


class TestDispatchIssueAssignedRealtime(BaseTest):
    def setUp(self):
        super().setUp()
        self.assigner = self.user
        self.assignee = User.objects.create_and_join(self.organization, "assignee@test.com", "password")
        self.issue = ErrorTrackingIssue.objects.create(team=self.team, name="Some Error", description="boom")

    @patch("products.error_tracking.backend.notifications.create_notification")
    def test_user_assignment_dispatches_to_assignee(self, mock_create_notification):
        assignment = ErrorTrackingIssueAssignment.objects.create(team=self.team, issue=self.issue, user=self.assignee)
        dispatch_issue_assigned_realtime(
            assignment=assignment,
            assignee={"type": "user", "id": self.assignee.id},
            assigner=self.assigner,
        )
        mock_create_notification.assert_called_once()
        data = mock_create_notification.call_args.args[0]
        assert data.target_type == TargetType.USER
        assert data.target_id == str(self.assignee.id)
        assert data.resource_type == "error_tracking"
        assert data.resource_id == str(self.issue.id)
        assert data.metadata == {"trigger": "manual"}

    @patch("products.error_tracking.backend.notifications.create_notification")
    def test_user_self_assignment_does_not_dispatch(self, mock_create_notification):
        assignment = ErrorTrackingIssueAssignment.objects.create(team=self.team, issue=self.issue, user=self.assigner)
        dispatch_issue_assigned_realtime(
            assignment=assignment,
            assignee={"type": "user", "id": self.assigner.id},
            assigner=self.assigner,
        )
        mock_create_notification.assert_not_called()

    @patch("products.error_tracking.backend.notifications.create_notification")
    def test_role_assignment_uses_role_target_with_assigner_excluding_resolver(self, mock_create_notification):
        role_id = create_role(organization_id=self.organization.id, name="Devs")
        assignment = ErrorTrackingIssueAssignment.objects.create(team=self.team, issue=self.issue, role_id=role_id)
        dispatch_issue_assigned_realtime(
            assignment=assignment,
            assignee={"type": "role", "id": role_id},
            assigner=self.assigner,
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
        assignee_id: int | UUID
        if assignee_type == "user":
            assignee_id = self.assignee.id
            assignment = ErrorTrackingIssueAssignment.objects.create(
                team=self.team, issue=self.issue, user=self.assignee
            )
        else:
            role_id = create_role(organization_id=self.organization.id, name="Devs")
            assignee_id = role_id
            assignment = ErrorTrackingIssueAssignment.objects.create(team=self.team, issue=self.issue, role_id=role_id)
        dispatch_issue_assigned_realtime(
            assignment=assignment,
            assignee={"type": assignee_type, "id": assignee_id},
            assigner=None,
            assigned_by="An assignment rule",
        )
        mock_create_notification.assert_called_once()
        data = mock_create_notification.call_args.args[0]
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
            assigner=self.assigner,
        )


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
class TestSendIssueAssignedEmail(BaseTest):
    def setUp(self):
        super().setUp()
        set_instance_setting("EMAIL_HOST", "fake_host")
        set_instance_setting("EMAIL_ENABLED", True)
        self.user.first_name = "Alice"
        self.user.save()
        self.assignee = User.objects.create_and_join(self.organization, "assignee@test.com", "password")
        issue = ErrorTrackingIssue.objects.create(team=self.team, name="Some Error")
        self.assignment = ErrorTrackingIssueAssignment.objects.create(team=self.team, issue=issue, user=self.assignee)

    @parameterized.expand(
        [
            ("manual", True, None, "Alice</b> has assigned you", "error_tracking_issue_assigned_"),
            (
                "automatic",
                False,
                "An assignment rule",
                "An assignment rule assigned you",
                "error_tracking_issue_assigned_automatic_",
            ),
        ]
    )
    def test_sends_to_assignee(
        self, MockEmailMessage: MagicMock, _name, with_assigner, assigned_by, expected_text, expected_key_prefix
    ):
        mocked_email_messages = mock_email_messages(MockEmailMessage)

        send_error_tracking_issue_assigned(
            self.assignment.id, self.user.id if with_assigner else None, assigned_by=assigned_by
        )

        assert len(mocked_email_messages) == 1
        message = mocked_email_messages[0]
        assert [to["raw_email"] for to in message.to] == ["assignee@test.com"]
        assert expected_text in message.html_body
        assert message.campaign_key.startswith(f"{expected_key_prefix}{self.assignment.id}_")
