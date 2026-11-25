from posthog.test.base import BaseTest
from unittest.mock import call, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.models import Organization, Team
from posthog.models.integration import Integration

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.facade.github import (
    PULL_REQUEST_STATE_REREAD_DELAY_SECONDS,
    link_reports_from_pull_request_description,
    refresh_pull_request_review_decisions,
    update_pull_request_assignments,
)
from products.signals.backend.models import SignalReport, SignalReportPullRequest
from products.signals.backend.pull_requests import link_pull_request
from products.signals.backend.report_assignments import PullRequestDetails


class TestRefreshPullRequestReviewDecisions(SimpleTestCase):
    @patch("products.signals.backend.tasks.refresh_pull_request_review_decision.delay")
    @patch("products.signals.backend.facade.github.installation_team_ids", return_value=[1, 2])
    def test_enqueues_remaining_teams_after_one_failure(self, _team_ids, enqueue) -> None:
        enqueue.side_effect = [RuntimeError("queue unavailable"), None]

        refresh_pull_request_review_decisions(
            {
                "repository": {"full_name": "example/app"},
                "pull_request": {"number": 42},
            }
        )

        assert enqueue.call_args_list == [
            call(team_id=1, repository="example/app", pr_number=42),
            call(team_id=2, repository="example/app", pr_number=42),
        ]


class TestUpdatePullRequestAssignments(BaseTest):
    @patch("products.signals.backend.tasks.refresh_linked_pull_request_state.apply_async")
    def test_state_webhook_rereads_github_for_teams_that_store_the_pull_request(self, reread) -> None:
        url = "https://github.com/example/app/pull/42"
        SignalReportPullRequest.objects.for_team(self.team.id).create(
            team=self.team, repository="example/app", number=42, url=url, state="draft"
        )
        other_team = Team.objects.create(organization=self.organization)

        with (
            patch(
                "products.signals.backend.facade.github.installation_team_ids",
                return_value=[self.team.id, other_team.id],
            ),
            self.captureOnCommitCallbacks(execute=True),
        ):
            update_pull_request_assignments(
                {
                    "repository": {"full_name": "Example/App"},
                    "pull_request": {"number": 42, "html_url": url},
                },
                "draft",
            )

        reread.assert_called_once_with(args=(self.team.id, url), countdown=PULL_REQUEST_STATE_REREAD_DELAY_SECONDS)


class TestLinkReportsFromPullRequestDescription(BaseTest):
    pr_url = "https://github.com/example/app/pull/7"

    def setUp(self) -> None:
        super().setUp()
        Integration.objects.create(team=self.team, kind="github", integration_id="31337", config={})
        self.report = self._report()

    def _report(self, *, team: Team | None = None, status: str = SignalReport.Status.READY) -> SignalReport:
        return SignalReport.objects.create(team=team or self.team, status=status, title="Checkout fails", summary="")

    def _payload(self, body: str, *, action: str = "edited", state: str = "open", author: dict | None = None) -> dict:
        return {
            "action": action,
            "installation": {"id": 31337},
            "repository": {"full_name": "example/app"},
            "pull_request": {
                "html_url": self.pr_url,
                "number": 7,
                "state": state,
                "body": body,
                "user": author or {"login": "avery-dev", "id": 7001, "type": "User"},
            },
        }

    def _queued(self, payload: dict, *, flag_enabled: bool = True) -> list[tuple]:
        with (
            patch("products.signals.backend.tasks.link_pull_request_description_reports.delay") as delay,
            patch("products.signals.backend.report_content_gates.feature_enabled_or_false", return_value=flag_enabled),
            self.captureOnCommitCallbacks(execute=True),
        ):
            link_reports_from_pull_request_description(payload)
        return [queued.args for queued in delay.call_args_list]

    @parameterized.expand(
        [
            ("mcp_url_on_open", "opened", "Fixes https://us.example.com/project/{team}/inbox/{report}?link_source=mcp"),
            (
                "web_url_on_edit",
                "edited",
                "See [report](https://example.com/project/{team}/inbox/reports/{report}#log)",
            ),
            ("relative_path_on_ready", "ready_for_review", "Inbox: /project/{team}/inbox/{report}/"),
        ]
    )
    def test_queues_the_report_the_description_names(self, _name: str, action: str, body: str) -> None:
        payload = self._payload(body.format(team=self.team.id, report=str(self.report.id).upper()), action=action)

        assert self._queued(payload) == [(self.team.id, self.pr_url, "avery-dev", 7001, [str(self.report.id)])]

    def test_queues_at_most_five_reports_in_description_order(self) -> None:
        reports = [self._report() for _ in range(6)]
        body = "\n".join(f"- https://example.com/project/{self.team.id}/inbox/{report.id}" for report in reports)

        assert self._queued(self._payload(body)) == [
            (self.team.id, self.pr_url, "avery-dev", 7001, [str(report.id) for report in reports[:5]])
        ]

    @parameterized.expand(
        [
            ("unrelated_action", {"action": "synchronize"}),
            ("closed_pull_request", {"state": "closed"}),
            ("bot_author", {"author": {"login": "posthog[bot]", "id": 41898282, "type": "Bot"}}),
            ("app_user_login", {"author": {"login": "deploy-helper[bot]", "id": 41898283, "type": "User"}}),
            ("team_outside_installation", {}),
            ("scout_finding_path", {}),
            ("resolved_report", {}),
            ("already_linked", {}),
            ("flag_off", {}),
        ]
    )
    def test_queues_nothing(self, name: str, payload_overrides: dict) -> None:
        team_id, report = self.team.id, self.report
        path = "inbox/{report}"
        if name == "team_outside_installation":
            outsider = Team.objects.create(organization=Organization.objects.create(name="Elsewhere"))
            team_id, report = outsider.id, self._report(team=outsider)
        elif name == "scout_finding_path":
            path = "inbox/scouts/checkout-scout/{report}"
        elif name == "resolved_report":
            report.status = SignalReport.Status.RESOLVED
            report.save(update_fields=["status"])
        elif name == "already_linked":
            link_pull_request(
                report=report,
                details=PullRequestDetails(
                    url=self.pr_url, repository="example/app", number=7, state="open", merged=False
                ),
                actor=ArtefactAttribution.system(),
                claim_id=None,
            )
        body = f"Fixes https://example.com/project/{team_id}/{path.format(report=report.id)}"

        assert self._queued(self._payload(body, **payload_overrides), flag_enabled=name != "flag_off") == []
