from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from products.error_tracking.backend.facade.issues import assign_issue_to_user_from_slack, resolve_issue_from_slack
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueAssignment


class TestSlackIssueActions(BaseTest):
    def setUp(self):
        super().setUp()
        self.integration = Integration.objects.create(team=self.team, kind="slack", integration_id="T123")
        self.issue = ErrorTrackingIssue.objects.create(team=self.team, name="TypeError")
        # Delivery side effects are exercised elsewhere; here only the mutation outcome matters.
        dispatch = patch("products.error_tracking.backend.temporal.alerts.dispatch.start_alert_delivery_workflow")
        dispatch.start()
        self.addCleanup(dispatch.stop)

    def test_resolve_from_slack_resolves_once_and_reports_repeats(self):
        assert resolve_issue_from_slack(self.issue.id, integration=self.integration, user=self.user) == "ok"
        self.issue.refresh_from_db()
        assert self.issue.status == ErrorTrackingIssue.Status.RESOLVED

        assert resolve_issue_from_slack(self.issue.id, integration=self.integration, user=self.user) == "already"

    def test_assign_to_me_from_slack(self):
        assert assign_issue_to_user_from_slack(self.issue.id, integration=self.integration, user=self.user) == "ok"
        assert ErrorTrackingIssueAssignment.objects.filter(issue=self.issue, user=self.user).exists()
        assert assign_issue_to_user_from_slack(self.issue.id, integration=self.integration, user=self.user) == "already"

    def test_workspace_from_another_project_cannot_touch_the_issue(self):
        # A button value can name any issue id; the workspace must be connected to its project.
        other_team = Team.objects.create(organization=self.organization, name="Other project")
        other_integration = Integration.objects.create(team=other_team, kind="slack", integration_id="T999")

        assert resolve_issue_from_slack(self.issue.id, integration=other_integration, user=self.user) == "not_found"
        self.issue.refresh_from_db()
        assert self.issue.status == ErrorTrackingIssue.Status.ACTIVE

    def test_user_without_project_access_is_refused(self):
        outsider_org = Organization.objects.create(name="Elsewhere")
        outsider = User.objects.create(email="outsider@example.com", distinct_id="outsider")
        OrganizationMembership.objects.create(user=outsider, organization=outsider_org)

        assert resolve_issue_from_slack(self.issue.id, integration=self.integration, user=outsider) == "no_access"
        self.issue.refresh_from_db()
        assert self.issue.status == ErrorTrackingIssue.Status.ACTIVE
