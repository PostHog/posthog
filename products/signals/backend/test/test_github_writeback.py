import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.egress.limiter.policies import Priority

from products.signals.backend.github_writeback import CLAIM_LEASE, MAX_COMMENT_PAGES, post_report_link_to_github_issues
from products.signals.backend.models import SignalReport, SignalReportGithubComment, SignalTeamConfig

WRITEBACK_MODULE_PATH = "products.signals.backend.github_writeback"


def _signal(**extra):
    return {
        "source_product": "github",
        "source_type": "issue",
        "source_id": "2001",
        "content": "exports time out on large date ranges",
        "extra": {
            "html_url": "https://github.com/acme/widgets/issues/42",
            "number": 42,
            "state": "open",
            "locked": False,
            **extra,
        },
    }


@pytest.mark.django_db
class TestPostReportLinkToGithubIssues(BaseTest):
    def setUp(self):
        super().setUp()
        SignalTeamConfig.objects.update_or_create(team=self.team, defaults={"github_issue_writeback_enabled": True})
        self.report = SignalReport.objects.create(
            team=self.team,
            status=SignalReport.Status.READY,
            title="fix(exports): page the date range",
            summary="The exporter loads the whole range into memory.",
        )
        self.signal = _signal()

    def _post(self, signals, *, issue=None):
        with patch(f"{WRITEBACK_MODULE_PATH}.GitHubIntegration") as integration:
            github = integration.first_for_team_repository.return_value
            github.api_request.return_value.json.return_value = (
                issue if issue is not None else {"state": "open", "locked": False}
            )
            comment = github.comment_on_issue
            comment.return_value = {"success": True}
            posted = post_report_link_to_github_issues(self.team, str(self.report.id), signals)
        return posted, comment

    def test_comments_a_link_to_the_report_on_the_issue(self):
        posted, comment = self._post([self.signal])

        assert posted == 1
        comment.assert_called_once()
        repository, number, body = comment.call_args.args
        assert (repository, number) == ("acme/widgets", 42)
        assert f"/project/{self.team.pk}/inbox/reports/{self.report.id}" in body

    def test_comment_carries_no_report_content(self):
        # The comment is public on the issue thread while the report is behind the project's access
        # check, so it must not publish the research itself.
        _, comment = self._post([self.signal])

        body = comment.call_args.args[2]
        assert self.report.title not in body
        assert "into memory" not in body

    @parameterized.expand(
        [
            ("the same url", "https://github.com/acme/widgets/issues/42"),
            ("the repository renamed to another case", "https://github.com/Acme/Widgets/issues/42"),
        ]
    )
    def test_is_idempotent_across_retries(self, _name, later_html_url):
        first, _ = self._post([self.signal])
        second, comment = self._post([_signal(html_url=later_html_url)])

        assert (first, second) == (1, 0)
        assert comment.call_count == 0
        assert SignalReportGithubComment.objects.for_team(self.team.pk).count() == 1

    def test_does_nothing_until_the_team_opts_in(self):
        SignalTeamConfig.objects.filter(team=self.team).update(github_issue_writeback_enabled=False)

        posted, comment = self._post([self.signal])

        assert posted == 0
        assert comment.call_count == 0

    @parameterized.expand(
        [
            ("another product", {"source_product": "error_tracking", "source_type": "issue", "extra": {}}),
            ("another source type", {"source_product": "github", "source_type": "issue_created", "extra": {}}),
            ("closed issue", _signal(state="closed")),
            ("locked issue", _signal(locked=True)),
            ("pull request url", _signal(html_url="https://github.com/acme/widgets/pull/42")),
            ("foreign host", _signal(html_url="https://evil.example.com/acme/widgets/issues/42")),
            ("no issue number", _signal(html_url="https://github.com/acme/widgets/issues/new")),
        ]
    )
    def test_leaves_everything_that_is_not_an_open_github_issue_alone(self, _name, signal):
        posted, comment = self._post([signal])

        assert posted == 0
        assert comment.call_count == 0

    def test_resolves_the_repository_once_for_two_issues_in_it(self):
        other_issue = _signal(html_url="https://github.com/acme/widgets/issues/43", number=43)

        with patch(f"{WRITEBACK_MODULE_PATH}.GitHubIntegration") as integration:
            integration.first_for_team_repository.return_value.api_request.return_value.json.return_value = {
                "state": "open",
                "locked": False,
            }
            integration.first_for_team_repository.return_value.comment_on_issue.return_value = {"success": True}
            posted = post_report_link_to_github_issues(self.team, str(self.report.id), [self.signal, other_issue])

        assert posted == 2
        # Resolving an integration costs an authenticated GitHub call per integration the team has.
        assert integration.first_for_team_repository.call_count == 1

    def test_asks_for_the_lane_the_limiter_sheds_first(self):
        with patch(f"{WRITEBACK_MODULE_PATH}.GitHubIntegration") as integration:
            integration.first_for_team_repository.return_value.comment_on_issue.return_value = {"success": True}
            post_report_link_to_github_issues(self.team, str(self.report.id), [self.signal])

        assert integration.first_for_team_repository.call_args.kwargs["priority"] == Priority.BATCH

    def test_comments_once_when_two_signals_name_the_same_issue(self):
        posted, comment = self._post([self.signal, _signal()])

        assert posted == 1
        assert comment.call_count == 1

    @parameterized.expand(
        [
            ("closed", {"state": "closed", "locked": False}),
            ("locked", {"state": "open", "locked": True}),
            ("pull request", {"state": "open", "locked": False, "pull_request": {}}),
        ]
    )
    def test_rechecks_the_current_issue_before_posting(self, _name, issue):
        posted, comment = self._post([self.signal], issue=issue)
        assert posted == 0
        comment.assert_not_called()

    @parameterized.expand([("accepted", True, 0), ("not accepted", False, 1)])
    def test_reconciles_an_uncertain_post_after_the_lease_expires(self, _name, accepted, expected_posts):
        with patch(f"{WRITEBACK_MODULE_PATH}.GitHubIntegration") as integration:
            github = integration.first_for_team_repository.return_value
            github.api_request.return_value.json.return_value = {"state": "open", "locked": False}
            github.comment_on_issue.return_value = {
                "success": False,
                "error": "Failed to comment on issue",
            }
            failed = post_report_link_to_github_issues(self.team, str(self.report.id), [self.signal])
            body = github.comment_on_issue.call_args.args[2]

        assert failed == 0
        claim = SignalReportGithubComment.objects.for_team(self.team.pk).get()
        assert claim.commented_at is None
        immediate, comment = self._post([self.signal])
        assert immediate == 0
        comment.assert_not_called()

        SignalReportGithubComment.objects.for_team(self.team.pk).filter(pk=claim.pk).update(
            updated_at=timezone.now() - CLAIM_LEASE
        )
        with patch(f"{WRITEBACK_MODULE_PATH}.GitHubIntegration") as integration:
            github = integration.first_for_team_repository.return_value
            github.api_request.side_effect = [
                MagicMock(json=lambda: [{"body": "unrelated"}] * 100),
                MagicMock(json=lambda: [{"body": body}] if accepted else []),
                MagicMock(json=lambda: {"state": "open", "locked": False}),
            ]
            github.comment_on_issue.return_value = {"success": True}
            retried = post_report_link_to_github_issues(self.team, str(self.report.id), [self.signal])
        assert retried == expected_posts
        assert github.comment_on_issue.call_count == expected_posts
        claim.refresh_from_db()
        assert claim.commented_at is not None

    @parameterized.expand([("incomplete", [{"body": "unrelated"}] * 100), ("invalid", {})])
    def test_does_not_retry_when_the_comment_read_is_incomplete(self, _name, comments):
        claim = SignalReportGithubComment.objects.for_team(self.team.pk).create(
            team=self.team, report=self.report, repository="acme/widgets", number=42
        )
        SignalReportGithubComment.objects.for_team(self.team.pk).filter(pk=claim.pk).update(
            updated_at=timezone.now() - CLAIM_LEASE
        )
        with patch(f"{WRITEBACK_MODULE_PATH}.GitHubIntegration") as integration:
            github = integration.first_for_team_repository.return_value
            github.api_request.return_value.json.return_value = comments
            assert post_report_link_to_github_issues(self.team, str(self.report.id), [self.signal]) == 0
        github.comment_on_issue.assert_not_called()
        assert github.api_request.call_count <= MAX_COMMENT_PAGES
        claim.refresh_from_db()
        assert claim.commented_at is None

    def test_skips_a_repository_no_integration_can_reach(self):
        with patch(f"{WRITEBACK_MODULE_PATH}.GitHubIntegration") as integration:
            integration.first_for_team_repository.return_value = None
            posted = post_report_link_to_github_issues(self.team, str(self.report.id), [self.signal])

        assert posted == 0
        assert SignalReportGithubComment.objects.for_team(self.team.pk).get().commented_at is None
