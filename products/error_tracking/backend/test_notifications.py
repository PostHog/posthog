from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models import User

from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueAssignment
from products.error_tracking.backend.notifications import _AssignerExcludingResolver, dispatch_issue_assigned_realtime
from products.notifications.backend.facade.enums import TargetType

from ee.models.rbac.role import Role


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
        role = Role.objects.create(name="Devs", organization=self.organization)
        assignment = ErrorTrackingIssueAssignment.objects.create(team=self.team, issue=self.issue, role=role)
        dispatch_issue_assigned_realtime(
            assignment=assignment,
            assignee={"type": "role", "id": role.id},
            assigner=self.assigner,
        )
        mock_create_notification.assert_called_once()
        data = mock_create_notification.call_args.args[0]
        assert data.target_type == TargetType.ROLE
        assert data.target_id == str(role.id)
        assert isinstance(data.resolver, _AssignerExcludingResolver)
        assert data.resolver._assigner_id == self.assigner.id

    @patch("products.error_tracking.backend.notifications.create_notification", side_effect=RuntimeError("boom"))
    def test_dispatch_failure_is_swallowed(self, _mock_create_notification):
        assignment = ErrorTrackingIssueAssignment.objects.create(team=self.team, issue=self.issue, user=self.assignee)
        dispatch_issue_assigned_realtime(
            assignment=assignment,
            assignee={"type": "user", "id": self.assignee.id},
            assigner=self.assigner,
        )


class TestAssignerExcludingResolver(BaseTest):
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
