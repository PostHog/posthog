from posthog.test.base import BaseTest
from unittest.mock import patch

from posthog.models.integration import Integration
from posthog.models.organization import Organization, OrganizationMembership
from posthog.models.team.team import Team
from posthog.models.user import User

from products.error_tracking.backend.facade.issues import assign_issue_to_user_from_slack, resolve_issue_from_slack
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueFingerprintV2,
)


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

    def test_fingerprint_lands_on_the_surviving_issue_after_a_merge(self):
        # The Slack root outlives a merged-away source issue; its buttons carry the fingerprint.
        survivor = ErrorTrackingIssue.objects.create(team=self.team, name="Survivor")
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=survivor, fingerprint="fp-1")
        gone_issue_id = self.issue.id
        self.issue.delete()

        # The same fingerprint in a sibling environment must not be picked instead.
        sibling = Team.objects.create(organization=self.organization, project=self.team.project, name="Staging")
        sibling_issue = ErrorTrackingIssue.objects.create(team=sibling, name="Staging twin")
        ErrorTrackingIssueFingerprintV2.objects.create(team=sibling, issue=sibling_issue, fingerprint="fp-1")

        outcome = resolve_issue_from_slack(
            gone_issue_id, fingerprint="fp-1", team_id=self.team.id, integration=self.integration, user=self.user
        )

        assert outcome == "ok_moved"
        survivor.refresh_from_db()
        assert survivor.status == ErrorTrackingIssue.Status.RESOLVED
        sibling_issue.refresh_from_db()
        assert sibling_issue.status == ErrorTrackingIssue.Status.ACTIVE

    def test_member_without_error_tracking_editor_access_is_refused(self):
        with patch(
            "products.error_tracking.backend.logic.slack_actions.UserAccessControl.check_access_level_for_resource",
            return_value=False,
        ):
            outcome = resolve_issue_from_slack(self.issue.id, integration=self.integration, user=self.user)

        assert outcome == "no_access"
        self.issue.refresh_from_db()
        assert self.issue.status == ErrorTrackingIssue.Status.ACTIVE

    def test_member_outside_enforced_verified_domains_is_refused(self):
        with patch(
            "products.error_tracking.backend.logic.slack_actions.OrganizationDomain.objects.is_email_blocked_by_domain_enforcement",
            return_value=True,
        ):
            outcome = resolve_issue_from_slack(self.issue.id, integration=self.integration, user=self.user)

        assert outcome == "no_access"
        self.issue.refresh_from_db()
        assert self.issue.status == ErrorTrackingIssue.Status.ACTIVE

    def test_buttons_act_on_the_threads_own_issue_while_it_exists(self):
        # After a split the fingerprint moves but the thread still belongs to the old issue.
        new_issue = ErrorTrackingIssue.objects.create(team=self.team, name="Split out")
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=new_issue, fingerprint="fp-split")

        outcome = resolve_issue_from_slack(
            self.issue.id, fingerprint="fp-split", team_id=self.team.id, integration=self.integration, user=self.user
        )

        assert outcome == "ok"
        self.issue.refresh_from_db()
        new_issue.refresh_from_db()
        assert self.issue.status == ErrorTrackingIssue.Status.RESOLVED
        assert new_issue.status == ErrorTrackingIssue.Status.ACTIVE

    def test_second_click_inside_the_claim_window_is_reported_as_already(self):
        # The status re-read can miss a concurrent click; the claim catches it.
        with patch("products.error_tracking.backend.logic.slack_actions._claim_click", return_value=False):
            outcome = resolve_issue_from_slack(self.issue.id, integration=self.integration, user=self.user)

        assert outcome == "already"
        self.issue.refresh_from_db()
        assert self.issue.status == ErrorTrackingIssue.Status.ACTIVE
