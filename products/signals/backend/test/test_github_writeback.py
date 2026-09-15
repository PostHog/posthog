import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.signals.backend.github_writeback import post_report_link_to_github_issues
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

    def _post(self, signals):
        with patch(f"{WRITEBACK_MODULE_PATH}.GitHubIntegration") as integration:
            comment = integration.first_for_team_repository.return_value.comment_on_issue
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

    def test_is_idempotent_across_retries(self):
        first, _ = self._post([self.signal])
        second, comment = self._post([self.signal])

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
            integration.first_for_team_repository.return_value.comment_on_issue.return_value = {"success": True}
            posted = post_report_link_to_github_issues(self.team, str(self.report.id), [self.signal, other_issue])

        assert posted == 2
        # Resolving an integration costs an authenticated GitHub call per integration the team has.
        assert integration.first_for_team_repository.call_count == 1

    def test_comments_once_when_two_signals_name_the_same_issue(self):
        posted, comment = self._post([self.signal, _signal()])

        assert posted == 1
        assert comment.call_count == 1

    def test_a_failed_call_leaves_the_issue_eligible_for_a_retry(self):
        with patch(f"{WRITEBACK_MODULE_PATH}.GitHubIntegration") as integration:
            integration.first_for_team_repository.return_value.comment_on_issue.return_value = {
                "success": False,
                "error": "Failed to comment on issue",
            }
            failed = post_report_link_to_github_issues(self.team, str(self.report.id), [self.signal])

        assert failed == 0
        assert not SignalReportGithubComment.objects.for_team(self.team.pk).exists()

        retried, _ = self._post([self.signal])
        assert retried == 1

    def test_skips_a_repository_no_integration_can_reach(self):
        with patch(f"{WRITEBACK_MODULE_PATH}.GitHubIntegration") as integration:
            integration.first_for_team_repository.return_value = None
            posted = post_report_link_to_github_issues(self.team, str(self.report.id), [self.signal])

        assert posted == 0
        assert not SignalReportGithubComment.objects.for_team(self.team.pk).exists()
