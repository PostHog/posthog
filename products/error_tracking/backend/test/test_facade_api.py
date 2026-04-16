from datetime import timedelta

from posthog.test.base import BaseTest

from django.utils.timezone import now

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
    ErrorTrackingSymbolSet,
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
