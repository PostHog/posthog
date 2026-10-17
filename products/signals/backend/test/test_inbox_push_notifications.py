import json
from datetime import UTC, datetime

from posthog.test.base import BaseTest
from unittest.mock import call, patch

from parameterized import parameterized

from posthog.models import User

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportPullRequest
from products.signals.backend.pull_requests import (
    PullRequestStateSource,
    link_pull_request,
    update_pull_request_review_decision,
    update_pull_request_state,
)
from products.signals.backend.report_assignments import PullRequestDetails, create_claim

# Task ORM model needed for a task-claim fixture; the tasks facade exposes DTOs only.
from products.tasks.backend.models import Task

PR_URL = "https://github.com/posthog/posthog/pull/123"
VISIBLE_AT = datetime(2026, 1, 1, tzinfo=UTC)


class TestInboxPushNotifications(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.reviewer = User.objects.create_and_join(self.organization, "reviewer@example.com", None)
        send_patch = patch("products.signals.backend.inbox_push_notifications.send_user_push.delay")
        flag_patch = patch(
            "products.signals.backend.inbox_push_notifications.posthoganalytics.feature_enabled", return_value=True
        )
        self.send_push = send_patch.start()
        self.flag = flag_patch.start()
        self.addCleanup(send_patch.stop)
        self.addCleanup(flag_patch.stop)

    def _report(self, status: SignalReport.Status, **fields: object) -> SignalReport:
        return SignalReport.objects.create(
            team=self.team, status=status, title="Checkout fails", summary="Summary", **fields
        )

    def _add_reviewers(self, report: SignalReport, *users: User) -> None:
        SignalReportArtefact.objects.create(
            team=self.team,
            report=report,
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
            content=json.dumps([{"user_uuid": str(user.uuid)} for user in users]),
        )

    def _make_visible(self, report: SignalReport) -> None:
        report.save(update_fields=report.transition_to(SignalReport.Status.READY, title="Checkout fails", summary="S"))

    @parameterized.expand([("transition_to_ready",), ("born_visible",)])
    def test_first_visibility_pushes_to_suggested_reviewers(self, path: str) -> None:
        if path == "transition_to_ready":
            report = self._report(SignalReport.Status.IN_PROGRESS)
            self._add_reviewers(report, self.reviewer)
            with self.captureOnCommitCallbacks(execute=True):
                self._make_visible(report)
        else:
            # The scout path writes reviewers after the report row, inside the same transaction.
            with self.captureOnCommitCallbacks(execute=True):
                report = self._report(SignalReport.Status.READY, first_visible_at=VISIBLE_AT)
                self._add_reviewers(report, self.reviewer)

        assert self.send_push.call_args_list == [
            call(
                self.reviewer.id,
                "New report for you",
                "Checkout fails",
                {
                    "type": "report",
                    "report_id": str(report.id),
                    "project_id": self.team.id,
                    "notificationKind": "report_visible",
                    "url": f"posthog://inbox/{report.id}",
                },
            )
        ]

    @parameterized.expand(
        [
            ("no_reviewers", False, True, False),
            ("flag_off", True, False, False),
            ("visible_before", True, True, True),
        ]
    )
    def test_report_visibility_pushes_nothing(
        self, _name: str, has_reviewers: bool, flag_enabled: bool, visible_before: bool
    ) -> None:
        self.flag.return_value = flag_enabled
        report = self._report(SignalReport.Status.IN_PROGRESS, first_visible_at=VISIBLE_AT if visible_before else None)
        if has_reviewers:
            self._add_reviewers(report, self.reviewer)

        with self.captureOnCommitCallbacks(execute=True):
            self._make_visible(report)

        self.send_push.assert_not_called()

    @parameterized.expand(
        [
            ("user_claim_by_a_reviewer", "user", SignalReportPullRequest.State.DRAFT, None, True),
            ("task_claim", "task", SignalReportPullRequest.State.DRAFT, None, True),
            ("already_open", "user", SignalReportPullRequest.State.OPEN, None, False),
            (
                "approved",
                "user",
                SignalReportPullRequest.State.DRAFT,
                SignalReportPullRequest.ReviewDecision.APPROVED,
                False,
            ),
        ]
    )
    def test_pull_request_ready_pushes_claimant_and_reviewers_once(
        self, _name: str, claim_kind: str, initial_state: str, review_decision: str | None, expect_push: bool
    ) -> None:
        report = self._report(SignalReport.Status.READY)
        if claim_kind == "user":
            self._add_reviewers(report, self.user, self.reviewer)
            create_claim(report, ArtefactAttribution.from_user(self.user.id))
        else:
            self._add_reviewers(report, self.reviewer)
            task = Task.objects.create(
                team=self.team,
                title="Fix checkout",
                description="d",
                origin_product=Task.OriginProduct.USER_CREATED,
                created_by=self.user,
            )
            create_claim(report, ArtefactAttribution.from_task(str(task.id)))
        link_pull_request(
            report=report,
            details=PullRequestDetails(
                url=PR_URL, repository="posthog/posthog", number=123, state=initial_state, merged=False
            ),
            actor=ArtefactAttribution.from_user(self.user.id),
            claim_id=None,
            state_source=PullRequestStateSource.GITHUB,
            notify_reviewers=False,
        )
        update_pull_request_review_decision(
            team_id=self.team.id, repository="posthog/posthog", number=123, review_decision=review_decision
        )

        with self.captureOnCommitCallbacks(execute=True):
            update_pull_request_state(team_id=self.team.id, repository="posthog/posthog", number=123, state="open")

        pushed = sorted((args[0], args[1]) for args, _ in self.send_push.call_args_list)
        expected = sorted([(self.user.id, "PR ready to review"), (self.reviewer.id, "PR ready to review")])
        assert pushed == (expected if expect_push else [])
        for push in self.send_push.call_args_list:
            assert push.args[3]["url"] == f"posthog://inbox/{report.id}"
