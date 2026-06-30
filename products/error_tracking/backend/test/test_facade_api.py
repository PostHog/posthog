from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils.timezone import now

from parameterized import parameterized

from posthog.models import Team
from posthog.models.integration import Integration

from products.error_tracking.backend.facade import api, contracts
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueFingerprintV2,
    ErrorTrackingSymbolSet,
)

from ee.models.rbac.role import Role


class TestErrorTrackingFacadeAPI(BaseTest):
    def _create_issue(self, *, team, name: str, description: str | None = None) -> ErrorTrackingIssue:
        issue = ErrorTrackingIssue.objects.create(team=team, name=name, description=description)
        ErrorTrackingIssueFingerprintV2.objects.create(team=team, issue=issue, fingerprint=f"fp-{issue.id}")
        return issue

    def test_list_issues_returns_contracts_scoped_by_team(self):
        issue = self._create_issue(team=self.team, name="Checkout failed", description="Payment intent error")
        ErrorTrackingIssueAssignment.objects.create(issue=issue, team=self.team, user=self.user)

        other_team = Team.objects.create(organization=self.organization, name="Other team")
        self._create_issue(team=other_team, name="Other team issue")

        issues = api.list_issues(team_id=self.team.id)

        assert len(issues) == 1
        assert isinstance(issues[0], contracts.ErrorTrackingIssuePreview)
        assert issues[0].id == issue.id
        assert issues[0].assignee is not None
        assert issues[0].assignee.id == self.user.id
        assert issues[0].assignee.type == "user"

    def test_get_issue_returns_contract(self):
        issue = self._create_issue(team=self.team, name="Unhandled TypeError")

        result = api.get_issue(issue_id=issue.id, team_id=self.team.id)

        assert isinstance(result, contracts.ErrorTrackingIssue)
        assert result.id == issue.id
        assert result.name == "Unhandled TypeError"
        assert result.external_issues == []
        assert result.cohort is None

    def test_get_issue_raises_for_other_team(self):
        issue = self._create_issue(team=self.team, name="Scoped issue")
        other_team = Team.objects.create(organization=self.organization, name="Other team")

        with self.assertRaises(api.IssueNotFoundError):
            api.get_issue(issue_id=issue.id, team_id=other_team.id)

    @patch("products.error_tracking.backend.logic.LinearIntegration.list_teams")
    def test_create_external_reference_rejects_invalid_linear_team_id(self, mock_list_teams):
        mock_list_teams.return_value = [{"id": "linear-team-id", "name": "Engineering"}]
        issue = self._create_issue(team=self.team, name="Checkout TypeError")
        integration = Integration.objects.create(
            team=self.team,
            kind=Integration.IntegrationKind.LINEAR.value,
            config={"data": {"viewer": {"organization": {"urlKey": "acme"}}}},
            sensitive_config={"access_token": "access-token"},
        )

        with self.assertRaises(api.ExternalReferenceValidationError) as context:
            api.create_external_reference(
                team_id=self.team.id,
                issue_id=issue.id,
                integration_id=integration.id,
                config={"team_id": "other-team-id", "title": "Checkout TypeError", "description": ""},
            )

        assert str(context.exception) == (
            "Invalid Linear team_id. Use integrations-linear-teams-retrieve to choose a team from this integration."
        )
        mock_list_teams.assert_called_once_with()

    def test_issue_exists(self):
        assert api.issue_exists(team_id=self.team.id) is False

        self._create_issue(team=self.team, name="Any issue")

        assert api.issue_exists(team_id=self.team.id) is True

    def test_get_issue_id_for_fingerprint(self):
        issue = ErrorTrackingIssue.objects.create(team=self.team, name="Fingerprint lookup")
        fingerprint = "fingerprint-lookup"
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint=fingerprint)

        result = api.get_issue_id_for_fingerprint(team_id=self.team.id, fingerprint=fingerprint)

        assert result == issue.id

    @parameterized.expand(
        [
            ["name", "name", "checkout", ["Checkout timeout", "Checkout type error"]],
            ["issue_description", "issue_description", "timeout", ["A timeout during payment"]],
            ["missing_key", None, "timeout", []],
            ["missing_value", "name", None, []],
            ["unknown_key", "unknown", "checkout", []],
        ]
    )
    def test_get_issue_values(self, _name: str, key: str | None, value: str | None, expected: list[str]):
        self._create_issue(team=self.team, name="Checkout timeout", description="A timeout during payment")
        self._create_issue(team=self.team, name="Checkout type error", description="Type mismatch in checkout")

        values = api.get_issue_values(team_id=self.team.id, key=key, value=value)

        assert sorted(values) == sorted(expected)

    def test_count_issues_created_since(self):
        self._create_issue(team=self.team, name="New issue")
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        self._create_issue(team=other_team, name="Other team issue")

        issue_count = api.count_issues_created_since(team_id=self.team.id, since=now() - timedelta(minutes=1))

        assert issue_count == 1

    def test_get_issue_and_symbol_set_counts_by_team(self):
        other_team = Team.objects.create(organization=self.organization, name="Other team")

        self._create_issue(team=self.team, name="Issue one")
        self._create_issue(team=self.team, name="Issue two")
        self._create_issue(team=other_team, name="Issue three")

        ErrorTrackingSymbolSet.objects.create(team=self.team, ref="symbolset-1", storage_ptr="s3://symbolset-1")
        ErrorTrackingSymbolSet.objects.create(team=self.team, ref="symbolset-2")
        ErrorTrackingSymbolSet.objects.create(team=other_team, ref="symbolset-3", storage_ptr="s3://symbolset-3")

        issue_counts = dict(api.get_issue_counts_by_team())
        symbol_set_counts = dict(api.get_symbol_set_counts_by_team())
        resolved_symbol_set_counts = dict(api.get_symbol_set_counts_by_team(resolved_only=True))

        assert issue_counts[self.team.id] == 2
        assert issue_counts[other_team.id] == 1
        assert symbol_set_counts[self.team.id] == 2
        assert symbol_set_counts[other_team.id] == 1
        assert resolved_symbol_set_counts[self.team.id] == 1
        assert resolved_symbol_set_counts[other_team.id] == 1

    @parameterized.expand(
        [
            ["user_assignment"],
            ["role_assignment_with_member"],
            ["role_assignment_without_member"],
        ]
    )
    def test_get_issue_assignment_for_notification(self, assignment_kind: str):
        issue = self._create_issue(team=self.team, name="Assigned issue", description="Assigned description")

        expected_user_id: int | None
        expected_role_id = None
        expected_role_member_user_ids: list[int] = []

        if assignment_kind == "user_assignment":
            assignment = ErrorTrackingIssueAssignment.objects.create(issue=issue, team=self.team, user=self.user)
            expected_user_id = self.user.id
        else:
            role = Role.objects.create(name=f"Role for {assignment_kind}", organization=self.organization)
            if assignment_kind == "role_assignment_with_member":
                role.members.add(self.user)
                expected_role_member_user_ids = [self.user.id]

            assignment = ErrorTrackingIssueAssignment.objects.create(issue=issue, team=self.team, role=role)
            expected_user_id = None
            expected_role_id = role.id

        result = api.get_issue_assignment_for_notification(assignment_id=assignment.id)

        assert isinstance(result, contracts.ErrorTrackingIssueAssignmentNotification)
        assert result.id == assignment.id
        assert result.assigned_user_id == expected_user_id
        assert result.role_id == expected_role_id
        assert sorted(result.role_member_user_ids) == sorted(expected_role_member_user_ids)
        assert result.issue.id == issue.id
        assert result.issue.team_id == self.team.id
        assert result.issue.name == "Assigned issue"

    def test_get_settings_creates_defaults(self):
        settings = api.get_settings(self.team.id)

        assert isinstance(settings, contracts.ErrorTrackingSettings)
        assert settings.project_rate_limit_value is None
        assert settings.per_issue_rate_limit_value is None

    def test_update_settings_persists_and_is_partial(self):
        api.update_settings(
            self.team.id,
            {"project_rate_limit_value": 100, "project_rate_limit_bucket_size_minutes": 5},
        )
        updated = api.update_settings(self.team.id, {"per_issue_rate_limit_value": 7})

        assert updated.project_rate_limit_value == 100
        assert updated.project_rate_limit_bucket_size_minutes == 5
        assert updated.per_issue_rate_limit_value == 7
        # a fresh read reflects the same persisted state, scoped to the team
        assert api.get_settings(self.team.id) == updated

    def test_update_settings_scoped_by_team(self):
        other_team = Team.objects.create(organization=self.organization, name="Other team")
        api.update_settings(self.team.id, {"project_rate_limit_value": 42})

        assert api.get_settings(other_team.id).project_rate_limit_value is None

    def test_spike_detection_config_get_and_update(self):
        config = api.get_spike_detection_config(self.team.id)
        assert isinstance(config, contracts.ErrorTrackingSpikeDetectionConfig)

        updated = api.update_spike_detection_config(self.team.id, {"multiplier": 9, "threshold": 50})

        assert updated.multiplier == 9
        assert updated.threshold == 50
        assert api.get_spike_detection_config(self.team.id) == updated
