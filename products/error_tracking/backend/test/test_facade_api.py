from datetime import timedelta

from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils.timezone import now

from parameterized import parameterized

from posthog.models import Team
from posthog.models.integration import Integration

from products.error_tracking.backend.facade import (
    api,
    types as contracts,
)
from products.error_tracking.backend.models import (
    ErrorTrackingExternalReference,
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
            ("linear", {"id": "LIN-1"}, "https://linear.app/ph/issue/LIN-1"),
            ("github", {"repository": "posthog", "number": 42}, "https://github.com/posthog-org/posthog/issues/42"),
            ("gitlab", {"issue_id": 7}, "https://gitlab.com/posthog/posthog/issues/7"),
            ("jira", {"key": "ET-9"}, "https://posthog.atlassian.net/browse/ET-9"),
        ]
    )
    def test_create_external_reference_persists_when_integration_returns_required_keys(
        self, kind: str, external_context: dict, expected_url: str
    ):
        issue = self._create_issue(team=self.team, name="External reference persists")
        integration = Integration.objects.create(
            team=self.team,
            kind=kind,
            config={
                "data": {"viewer": {"organization": {"urlKey": "ph"}}},  # linear
                "path_with_namespace": "posthog/posthog",  # gitlab
                "hostname": "https://gitlab.com",  # gitlab
                "site_url": "https://posthog.atlassian.net",  # jira
                "account": {"name": "posthog-org"},  # github org fallback
            },
        )

        patch_targets = {
            "linear": "posthog.models.integration.LinearIntegration.create_issue",
            "github": "posthog.models.integration.GitHubIntegration.create_issue",
            "gitlab": "posthog.models.integration.GitLabIntegration.create_issue",
            "jira": "posthog.models.integration.JiraIntegration.create_issue",
        }

        with (
            patch(patch_targets[kind], return_value=external_context),
            patch("posthog.models.integration.GitHubIntegration.organization", return_value="posthog-org"),
            patch("products.error_tracking.backend.facade.api.posthoganalytics.capture"),
        ):
            result = api.create_external_reference(
                team_id=self.team.id,
                issue_id=issue.id,
                integration_id=integration.id,
                config={},
            )

        assert isinstance(result, contracts.ErrorTrackingExternalReference)
        assert result.external_url == expected_url
        assert ErrorTrackingExternalReference.objects.filter(issue=issue).count() == 1

    @parameterized.expand(
        [
            ("linear", {}),
            ("linear", {"id": ""}),
            ("github", {"repository": "posthog"}),
            ("github", {"number": 42}),
            ("gitlab", {}),
            ("jira", {}),
        ]
    )
    def test_create_external_reference_rejects_incomplete_external_context(self, kind: str, external_context: dict):
        issue = self._create_issue(team=self.team, name="Incomplete context")
        integration = Integration.objects.create(team=self.team, kind=kind, config={})

        patch_targets = {
            "linear": "posthog.models.integration.LinearIntegration.create_issue",
            "github": "posthog.models.integration.GitHubIntegration.create_issue",
            "gitlab": "posthog.models.integration.GitLabIntegration.create_issue",
            "jira": "posthog.models.integration.JiraIntegration.create_issue",
        }

        with patch(patch_targets[kind], return_value=external_context):
            with self.assertRaises(api.ExternalReferenceValidationError):
                api.create_external_reference(
                    team_id=self.team.id,
                    issue_id=issue.id,
                    integration_id=integration.id,
                    config={},
                )

        # The reference row must not have been persisted.
        assert ErrorTrackingExternalReference.objects.filter(issue=issue).count() == 0

    def test_list_external_references_tolerates_orphaned_rows(self):
        # Simulates a pre-existing orphaned row from before validation was added —
        # the row must still serialize so the UI can list it without raising a 400.
        issue = self._create_issue(team=self.team, name="Orphaned reference")
        integration = Integration.objects.create(team=self.team, kind="linear", config={})
        ErrorTrackingExternalReference.objects.create(
            issue=issue,
            integration=integration,
            external_context={},
        )

        references = api.list_external_references(team_id=self.team.id)

        assert len(references) == 1
        assert references[0].external_url == ""

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
