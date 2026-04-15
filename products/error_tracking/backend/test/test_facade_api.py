from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.models import Team

from products.error_tracking.backend.facade import (
    api,
    types as contracts,
)
from products.error_tracking.backend.models import (
    ErrorTrackingIssue,
    ErrorTrackingIssueAssignment,
    ErrorTrackingIssueFingerprintV2,
)


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
