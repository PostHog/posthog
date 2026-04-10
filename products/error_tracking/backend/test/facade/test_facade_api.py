from datetime import timedelta

from posthog.test.base import BaseTest

from django.utils import timezone

from posthog.models.team.team import Team

from products.error_tracking.backend.facade.api import (
    count_issues_created_since,
    delete_issue_fingerprints,
    get_issue,
    get_issue_fingerprint,
    has_resolved_issues,
    iter_issue_fingerprints_created_between,
    publish_issue_fingerprint_override,
    update_issue_fingerprint_first_seen_and_version,
)
from products.error_tracking.backend.models import ErrorTrackingIssue, ErrorTrackingIssueFingerprintV2


class TestErrorTrackingFacadeAPI(BaseTest):
    def test_get_issue_summary_returns_contract(self) -> None:
        issue = ErrorTrackingIssue.objects.create(
            team=self.team,
            status=ErrorTrackingIssue.Status.RESOLVED,
            name="TypeError",
            description="Cannot read properties of undefined",
        )

        summary = get_issue(str(issue.id), self.team)

        assert summary is not None
        assert summary.id == str(issue.id)
        assert summary.team_id == self.team.id
        assert summary.status == ErrorTrackingIssue.Status.RESOLVED
        assert summary.name == "TypeError"
        assert summary.description == "Cannot read properties of undefined"

    def test_get_issue_summary_returns_none_for_missing_or_wrong_team(self) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        other_team = Team.objects.create(organization=self.organization, name="other")

        assert get_issue("00000000-0000-0000-0000-000000000000", self.team) is None
        assert get_issue(str(issue.id), other_team) is None

    def test_count_issues_created_since_filters_by_team_and_time(self) -> None:
        recent_issue = ErrorTrackingIssue.objects.create(team=self.team)
        old_issue = ErrorTrackingIssue.objects.create(team=self.team)
        ErrorTrackingIssue.objects.filter(id=old_issue.id).update(created_at=timezone.now() - timedelta(days=14))

        other_team = Team.objects.create(organization=self.organization, name="other")
        ErrorTrackingIssue.objects.create(team=other_team)

        count = count_issues_created_since(self.team, timezone.now() - timedelta(days=7))

        assert count == 1
        assert recent_issue.id != old_issue.id

    def test_has_resolved_issues_checks_resolved_status_only(self) -> None:
        ErrorTrackingIssue.objects.create(team=self.team, status=ErrorTrackingIssue.Status.ACTIVE)
        assert has_resolved_issues(self.team) is False

        ErrorTrackingIssue.objects.create(team=self.team, status=ErrorTrackingIssue.Status.RESOLVED)
        assert has_resolved_issues(self.team) is True

    def test_issue_fingerprint_facade_helpers(self) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        fingerprint = ErrorTrackingIssueFingerprintV2.objects.create(
            team=self.team,
            issue=issue,
            fingerprint="fingerprint-1",
            version=2,
        )

        fetched = get_issue_fingerprint(self.team.id, "fingerprint-1")

        assert fetched is not None
        assert fetched.id == str(fingerprint.id)
        assert fetched.issue_id == str(issue.id)
        assert fetched.version == 2

        iterated = iter_issue_fingerprints_created_between(
            self.team.id,
            (timezone.now() - timedelta(days=1)).isoformat(),
            (timezone.now() + timedelta(days=1)).isoformat(),
        )
        assert [contract.fingerprint for contract in iterated] == ["fingerprint-1"]

        updated = update_issue_fingerprint_first_seen_and_version(
            team_id=self.team.id,
            fingerprint="fingerprint-1",
            first_seen=timezone.now() - timedelta(hours=1),
            version=3,
        )
        assert updated is not None
        assert updated.version == 3

    def test_delete_issue_fingerprints_deletes_matching_rows(self) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team)
        ErrorTrackingIssueFingerprintV2.objects.create(team=self.team, issue=issue, fingerprint="fingerprint-1")

        deleted_count = delete_issue_fingerprints([self.team.id])

        assert deleted_count == 1
        assert ErrorTrackingIssueFingerprintV2.objects.filter(team=self.team).count() == 0

    def test_publish_issue_fingerprint_override_delegates_to_model_helper(self) -> None:
        issue = ErrorTrackingIssue.objects.create(team=self.team)

        with self.captureOnCommitCallbacks(execute=True):
            publish_issue_fingerprint_override(
                team_id=self.team.id,
                issue_id=str(issue.id),
                fingerprint="fingerprint-1",
                version=1,
            )
