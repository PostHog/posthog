import pytest
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.utils import timezone

from parameterized import parameterized

from posthog.egress.limiter.policies import Priority

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import SourceIssue
from products.signals.backend.github_writeback import (
    CLAIM_LEASE,
    MAX_COMMENT_PAGES,
    STATUS_LINES,
    post_report_link_to_github_issues,
)
from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalReportGithubComment,
    SignalTeamConfig,
)
from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource

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

    def _post(self, signals, *, issue=None, connected=True):
        with patch(f"{WRITEBACK_MODULE_PATH}.GitHubIntegration") as integration:
            github = integration.first_for_team_repository.return_value
            if not connected:
                integration.first_for_team_repository.return_value = None
            github.api_request.return_value.json.return_value = (
                issue if issue is not None else {"state": "open", "locked": False}
            )
            comment = github.comment_on_issue
            comment.return_value = {"success": True}
            posted = post_report_link_to_github_issues(self.team, str(self.report.id), signals)
        return posted, comment

    @parameterized.expand(
        [
            ("ready", SignalReport.Status.READY),
            ("pending input", SignalReport.Status.PENDING_INPUT),
            ("failed", SignalReport.Status.FAILED),
        ]
    )
    def test_comments_a_link_to_a_visible_report_on_the_issue(self, _name, status):
        SignalReport.objects.filter(pk=self.report.pk).update(status=status)

        posted, comment = self._post([self.signal])

        assert posted == 1
        comment.assert_called_once()
        repository, number, body = comment.call_args.args
        assert (repository, number) == ("acme/widgets", 42)
        assert f"/project/{self.team.pk}/inbox/reports/{self.report.id}?link_source=github_comment" in body
        assert STATUS_LINES[status] in body

    @parameterized.expand(
        [
            ("in progress", SignalReport.Status.IN_PROGRESS),
            ("resolved", SignalReport.Status.RESOLVED),
            ("suppressed", SignalReport.Status.SUPPRESSED),
        ]
    )
    def test_does_not_post_a_first_comment_for_a_report_the_inbox_does_not_list(self, _name, status):
        SignalReport.objects.filter(pk=self.report.pk).update(status=status)

        posted, comment = self._post([self.signal])

        assert posted == 0
        comment.assert_not_called()

    @parameterized.expand(
        [
            ("needs input to ready", SignalReport.Status.READY, True),
            ("needs input to resolved", SignalReport.Status.RESOLVED, True),
            ("status without a line", SignalReport.Status.CANDIDATE, False),
        ]
    )
    def test_a_status_change_edits_the_posted_comment_instead_of_posting_again(self, _name, later_status, edits):
        SignalReport.objects.filter(pk=self.report.pk).update(status=SignalReport.Status.PENDING_INPUT)
        _, first = self._post([self.signal])
        first_body = first.call_args.args[2]
        SignalReport.objects.filter(pk=self.report.pk).update(status=later_status)

        with patch(f"{WRITEBACK_MODULE_PATH}.GitHubIntegration") as integration:
            github = integration.first_for_team_repository.return_value
            github.api_request.side_effect = [
                MagicMock(json=lambda: [{"id": 7, "body": "unrelated"}, {"id": 9, "body": first_body}]),
                MagicMock(),
            ]
            posted = post_report_link_to_github_issues(self.team, str(self.report.id), [self.signal])

        assert posted == 0
        github.comment_on_issue.assert_not_called()
        patches = [call for call in github.api_request.call_args_list if call.args[0] == "PATCH"]
        if not edits:
            assert patches == []
            return
        assert [call.args[1] for call in patches] == ["/repos/acme/widgets/issues/comments/9"]
        new_body = patches[0].kwargs["json_body"]["body"]
        assert STATUS_LINES[later_status] in new_body
        assert STATUS_LINES[SignalReport.Status.PENDING_INPUT] not in new_body
        assert f"<!-- posthog:signal-report:{self.report.id} -->" in new_body

    def test_does_not_edit_a_comment_that_already_shows_the_status(self):
        _, first = self._post([self.signal])
        body = first.call_args.args[2]

        with patch(f"{WRITEBACK_MODULE_PATH}.GitHubIntegration") as integration:
            github = integration.first_for_team_repository.return_value
            github.api_request.return_value.json.return_value = [{"id": 9, "body": body}]
            post_report_link_to_github_issues(self.team, str(self.report.id), [self.signal])

        assert [call.args[0] for call in github.api_request.call_args_list] == ["GET"]

    @parameterized.expand(
        [
            ("to a visible status", SignalReport.Status.PENDING_INPUT, SignalReport.Status.READY, False, True, 1),
            (
                "while the team has not opted in",
                SignalReport.Status.PENDING_INPUT,
                SignalReport.Status.READY,
                False,
                False,
                0,
            ),
            (
                "to a closed status with no comment",
                SignalReport.Status.READY,
                SignalReport.Status.SUPPRESSED,
                False,
                True,
                0,
            ),
            (
                "to a closed status after a comment",
                SignalReport.Status.READY,
                SignalReport.Status.SUPPRESSED,
                True,
                True,
                1,
            ),
        ]
    )
    def test_a_status_transition_schedules_the_writeback(
        self, _name, from_status, to_status, commented, opted_in, expected
    ):
        SignalReport.objects.filter(pk=self.report.pk).update(status=from_status)
        SignalTeamConfig.objects.filter(team=self.team).update(github_issue_writeback_enabled=opted_in)
        if commented:
            SignalReportGithubComment.objects.for_team(self.team.pk).create(
                team=self.team, report=self.report, repository="acme/widgets", number=42, commented_at=timezone.now()
            )
        self.report.refresh_from_db()

        with (
            patch("products.signals.backend.github_writeback_tasks.post_source_issue_links") as writeback,
            self.captureOnCommitCallbacks(execute=True),
        ):
            self.report.status = to_status
            self.report.save(update_fields=["status", "updated_at"])

        assert writeback.delay.call_count == expected

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

    def _sync_issues(self, schema_name):
        source = ExternalDataSource.objects.create(
            team=self.team, source_type="Github", status="Running", prefix="gh_", job_inputs={}
        )
        ExternalDataSchema.objects.create(team=self.team, source=source, name=schema_name, should_sync=True)

    @parameterized.expand(
        [
            ("a synced repository", "acme/widgets.issues", True, False, 1),
            ("another synced repository the installation also reaches", "acme/other.issues", True, False, 0),
            ("a synced repository no team integration covers", "acme/widgets.issues", False, False, 0),
            ("the same issue from a signal and a source issue", "acme/other.issues", True, True, 1),
        ]
    )
    def test_comments_on_a_source_issue_in_a_synced_repository_before_its_signal_is_ingested(
        self, _name, schema_name, connected, with_signal, expected
    ):
        self._sync_issues(schema_name)
        self._name_source_issue()

        posted, comment = self._post([self.signal] if with_signal else [], connected=connected)

        assert posted == expected
        assert [call.args[:2] for call in comment.call_args_list] == [("acme/widgets", 42)] * expected

    def test_posts_no_second_comment_when_the_issue_signal_joins_later(self):
        self._sync_issues("acme/widgets.issues")
        self._name_source_issue()

        first, _ = self._post([])
        joined, comment = self._post([self.signal])

        assert (first, joined) == (1, 0)
        comment.assert_not_called()

    def _name_source_issue(self):
        SignalReportArtefact.add_log(
            team_id=self.team.pk,
            report_id=str(self.report.id),
            content=SourceIssue.github("Acme/Widgets", 42),
            attribution=ArtefactAttribution.system(),
        )

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
