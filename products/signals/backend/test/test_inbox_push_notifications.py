import json
from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest
from unittest.mock import call, patch

from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from parameterized import parameterized
from social_django.models import UserSocialAuth

from posthog.constants import AvailableFeature
from posthog.models import Team, User
from posthog.models.user_push_token import UserPushToken
from posthog.tasks.push_notifications import send_user_push

from products.access_control.backend.models.access_control import AccessControl
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.inbox_push_notifications import _push_report, notify_pull_request_ready
from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalReportPullRequest,
    SignalScoutConfig,
    SignalScoutRun,
)
from products.signals.backend.pull_requests import (
    PullRequestStateSource,
    link_pull_request,
    update_pull_request_review_decision,
    update_pull_request_state,
)
from products.signals.backend.report_assignments import PullRequestDetails, create_claim
from products.signals.backend.task_run_artefacts import append_task_run_artefact
from products.tasks.backend.facade.testing import (
    create_task_presence,
    notify_task_pull_request_outcome,
    notify_task_run_awaiting_input,
    notify_task_run_cancelled,
    notify_task_run_completed,
    notify_task_run_failed,
    notify_task_run_turn_completed,
    tasks_cache,
)

# Task ORM model needed for a task-claim fixture; the tasks facade exposes DTOs only.
from products.tasks.backend.models import Task, TaskRun

PR_URL = "https://github.com/posthog/posthog/pull/123"
VISIBLE_AT = datetime(2026, 1, 1, tzinfo=UTC)


class TestInboxPushNotifications(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        tasks_cache().clear()
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

    @parameterized.expand([("project_access", True), ("no_project_access", False)])
    def test_pull_request_ready_batches_reviewer_queries(self, _name: str, has_project_access: bool) -> None:
        if not has_project_access:
            self.organization.available_product_features = [
                {"key": AvailableFeature.ACCESS_CONTROL, "name": AvailableFeature.ACCESS_CONTROL}
            ]
            self.organization.save()
            AccessControl.objects.create(
                team=self.team, resource="project", resource_id=str(self.team.id), access_level="none"
            )
        login_reviewer = User.objects.create_and_join(self.organization, "login-reviewer@example.com", None)
        old_reviewer = User.objects.create_and_join(self.organization, "old-reviewer@example.com", None)
        UserSocialAuth.objects.create(
            user=login_reviewer, provider="github", uid="login-reviewer", extra_data={"login": "login-reviewer"}
        )
        pull_request = SignalReportPullRequest.objects.for_team(self.team.id).create(
            team=self.team, repository="posthog/posthog", number=123, url=PR_URL, state="open"
        )

        def add_linked_report(index: int = 0) -> SignalReport:
            report = self._report(SignalReport.Status.READY)
            SignalReport.objects.filter(team_id=self.team.id, id=report.id).update(
                created_at=VISIBLE_AT + timedelta(days=index)
            )
            self._add_reviewers(report, old_reviewer)
            report.artefacts.filter(type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS).update(
                created_at=VISIBLE_AT
            )
            reviewers = SignalReportArtefact.objects.create(
                team=self.team,
                report=report,
                type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
                content=json.dumps([{"user_uuid": str(self.reviewer.uuid)}, {"github_login": "login-reviewer"}]),
            )
            SignalReportArtefact.objects.filter(team_id=self.team.id, id=reviewers.id).update(
                created_at=VISIBLE_AT + timedelta(hours=1)
            )
            create_claim(report, ArtefactAttribution.from_user(self.user.id))
            SignalReportArtefact.objects.create(
                team=self.team,
                report=report,
                type=SignalReportArtefact.ArtefactType.PULL_REQUEST,
                pull_request=pull_request,
                content=json.dumps({"url": PR_URL}),
            )
            return report

        oldest_report = add_linked_report()
        with CaptureQueriesContext(connection) as one_report_queries:
            first_pushed = notify_pull_request_ready(team_id=self.team.id, pull_request_id=str(pull_request.id))
        expected_users = sorted([self.user.id, self.reviewer.id, login_reviewer.id]) if has_project_access else []
        assert first_pushed == expected_users
        self.send_push.reset_mock()
        tasks_cache().clear()

        for index in range(1, 5):
            add_linked_report(index)
        other_team = Team.objects.create(organization=self.organization)
        cross_team_reviewers = SignalReportArtefact.objects.create(
            team=other_team,
            report=oldest_report,
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
            content=json.dumps([{"user_uuid": str(old_reviewer.uuid)}]),
        )
        SignalReportArtefact.objects.filter(team_id=other_team.id, id=cross_team_reviewers.id).update(
            created_at=VISIBLE_AT + timedelta(hours=2)
        )
        with CaptureQueriesContext(connection) as many_report_queries:
            pushed = notify_pull_request_ready(team_id=self.team.id, pull_request_id=str(pull_request.id))

        assert pushed == expected_users
        assert [push.args[0] for push in self.send_push.call_args_list] == expected_users
        assert all(push.args[3]["report_id"] == str(oldest_report.id) for push in self.send_push.call_args_list)
        assert len(many_report_queries) == len(one_report_queries)

    @parameterized.expand(
        [
            ("web_implementation", "implementation", False, True, notify_task_run_completed),
            ("cross_team_implementation", "implementation", False, False, notify_task_run_completed),
            ("slack_implementation", "implementation", False, True, notify_task_run_failed),
            ("web_research", "research", False, True, notify_task_run_awaiting_input),
            ("web_discussion", "discussion", False, False, notify_task_run_cancelled),
            ("mobile_discussion", "discussion", True, True, notify_task_run_turn_completed),
            ("cancelled_implementation", "implementation", False, True, notify_task_run_cancelled),
            ("turn_implementation", "implementation", False, True, notify_task_run_turn_completed),
            ("picked_up_implementation", "implementation", False, True, notify_task_run_completed),
        ]
    )
    def test_report_work_and_discussions_use_their_own_channels(self, name, relationship, mobile, expect_push, notify):
        report = self._report(SignalReport.Status.READY, first_visible_at=VISIBLE_AT)
        self._add_reviewers(report, self.user)
        task = Task.objects.create(
            team=self.team,
            title="Internal task",
            created_by=self.user,
            origin_product=Task.OriginProduct.SLACK if name.startswith("slack") else Task.OriginProduct.SIGNAL_REPORT,
            signal_report=None if name == "cross_team_implementation" else report,
            state={"created_on_mobile": mobile},
        )
        if name == "picked_up_implementation":
            picked = User.objects.create_and_join(self.organization, "picked@example.com", None)
            task.state = {**(task.state or {}), "mobile_push_user_ids": [picked.id]}
            task.save(update_fields=["state"])
        run = TaskRun.objects.create(task=task, team=self.team)
        artefact = append_task_run_artefact(
            team_id=self.team.id,
            report_id=str(report.id),
            product="signals",
            type=relationship,
            task_id=str(task.id),
            run_id=str(run.id),
        )
        if name == "cross_team_implementation":
            other_team = Team.objects.create(organization=self.organization)
            SignalReportArtefact.objects.filter(team_id=self.team.id, id=artefact.id).update(team_id=other_team.id)
        with (
            self.captureOnCommitCallbacks(execute=True),
            patch("posthog.push_notifications.posthoganalytics.feature_enabled", return_value=True),
        ):
            notify(task_run_id=str(run.id), team_id=run.team_id)
            notify(task_run_id=str(run.id), team_id=run.team_id)
        self.assertEqual(self.send_push.call_count, 2 if name == "picked_up_implementation" else int(expect_push))
        if expect_push and relationship != "discussion":
            self.assertEqual(self.send_push.call_args.args[3]["type"], "report")
            self.assertEqual(self.send_push.call_args.args[3]["taskRunId"], str(run.id))
            self.assertIn(report.title, self.send_push.call_args.args[2])
            self.assertNotIn(task.title, self.send_push.call_args.args[2])

    @parameterized.expand(
        [
            ("active", "implementation", notify_task_run_completed),
            ("expired", "research", notify_task_run_awaiting_input),
            ("other_task", "implementation", notify_task_run_turn_completed),
        ]
    )
    def test_report_work_respects_task_presence(self, presence, relationship, notify) -> None:
        report = self._report(SignalReport.Status.READY, first_visible_at=VISIBLE_AT)
        self._add_reviewers(report, self.user, self.reviewer)
        task = Task.objects.create(team=self.team, created_by=self.user, signal_report=report)
        run = TaskRun.objects.create(task=task, team=self.team)
        append_task_run_artefact(
            team_id=self.team.id,
            report_id=str(report.id),
            product="signals",
            type=relationship,
            task_id=str(task.id),
            run_id=str(run.id),
        )
        tokens = [
            UserPushToken.objects.create(user=self.user, token=f"ExponentPushToken[device-{index}]", platform="ios")
            for index in range(2)
        ]
        watched_task = Task.objects.create(team=self.team, created_by=self.user) if presence == "other_task" else task
        create_task_presence(
            team_id=self.team.id,
            task_id=watched_task.id,
            user_id=self.user.id,
            push_token_id=tokens[0].id,
            expires_at=timezone.now() + timedelta(minutes=-1 if presence == "expired" else 1),
        )
        with self.captureOnCommitCallbacks(execute=True):
            notify(task_run_id=str(run.id), team_id=run.team_id)
        pushes = {push.args[0]: push.args for push in self.send_push.call_args_list}
        self.assertEqual(set(pushes), {self.user.id, self.reviewer.id})
        self.assertEqual(pushes[self.user.id][3]["type"], "report")
        self.assertCountEqual(
            pushes[self.user.id][4], [str(token.id) for token in tokens] if presence == "active" else []
        )
        self.assertEqual(pushes[self.reviewer.id][4], [])

    @parameterized.expand(
        [
            (outcome, merged, failure)
            for outcome, merged in [("merged", True), ("closed", False)]
            for failure in (None, "redis", "broker", "rollback")
        ]
    )
    def test_report_pr_outcomes_use_report_preferences_and_pr_identity(self, outcome, merged, failure):
        self.user.partial_notification_settings = {"mobile_push_tasks_enabled": False}
        self.user.save(update_fields=["partial_notification_settings"])
        report = self._report(SignalReport.Status.READY, first_visible_at=VISIBLE_AT)
        task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Internal work",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
            signal_report=report,
        )
        run = TaskRun.objects.create(task=task, team=self.team)
        append_task_run_artefact(
            team_id=self.team.id,
            report_id=str(report.id),
            product="signals",
            type="implementation",
            task_id=str(task.id),
            run_id=str(run.id),
        )
        if failure is not None:

            def notify() -> None:
                notify_task_pull_request_outcome(
                    task_id=str(task.id),
                    run_id=str(run.id),
                    team_id=self.team.id,
                    pr_url="https://github.com/example/project/pull/1",
                    merged=merged,
                )

            if failure == "rollback":
                with self.captureOnCommitCallbacks(execute=True):
                    with self.assertRaises(RuntimeError), transaction.atomic():
                        notify()
                        raise RuntimeError("rollback")
            else:
                boundary = (
                    patch.object(tasks_cache(), "add", side_effect=RuntimeError("redis unavailable"))
                    if failure == "redis"
                    else patch.object(self.send_push, "side_effect", RuntimeError("broker unavailable"))
                )
                with boundary, self.captureOnCommitCallbacks(execute=True):
                    notify()
            task.refresh_from_db()
            self.assertEqual((task.state or {}).get("mobile_push_pr_outcomes", []), [])
            self.send_push.reset_mock(side_effect=True)
        for number in (1, 1, 2):
            if number == 2 or self.send_push.call_count:
                tasks_cache().clear()
            with self.captureOnCommitCallbacks(execute=True):
                notify_task_pull_request_outcome(
                    task_id=str(task.id),
                    run_id=str(run.id),
                    team_id=self.team.id,
                    pr_url=f"https://github.com/example/project/pull/{number}",
                    merged=merged,
                )
        self.assertEqual(self.send_push.call_count, 2)
        args = self.send_push.call_args.args
        self.assertEqual(args[1:3], ("Report update", f'"{report.title}" pull request was {outcome}'))
        self.assertEqual(args[3]["type"], "report")
        self.assertEqual(args[3]["notificationKind"], f"report_pr_{outcome}")
        self.assertEqual(args[3]["pullRequestUrl"], "https://github.com/example/project/pull/2")

    @parameterized.expand([("unpublished",), ("hidden",), ("preferences",), ("lost_access",)])
    def test_report_work_suppresses_unavailable_updates(self, reason):
        report = self._report(
            SignalReport.Status.SUPPRESSED if reason == "hidden" else SignalReport.Status.READY,
            first_visible_at=None if reason == "unpublished" else VISIBLE_AT,
        )
        self._add_reviewers(report, self.user)
        task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Internal work",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
            signal_report=report,
        )
        run = TaskRun.objects.create(task=task, team=self.team)
        append_task_run_artefact(
            team_id=self.team.id,
            report_id=str(report.id),
            product="signals",
            type="implementation",
            task_id=str(task.id),
            run_id=str(run.id),
        )
        if reason == "preferences":
            self.user.partial_notification_settings = {"mobile_push_report_updates_enabled": False}
            self.user.save(update_fields=["partial_notification_settings"])
        if reason == "lost_access":
            self.organization.members.remove(self.user)
        with self.captureOnCommitCallbacks(execute=True):
            notify_task_run_completed(task_run_id=str(run.id), team_id=run.team_id)
        self.send_push.assert_not_called()

    @parameterized.expand(
        [
            ("mobile_push_enabled", "report_visible", False),
            ("mobile_push_reports_enabled", "report_visible", False),
            ("mobile_push_report_updates_enabled", "report_completed", False),
            ("mobile_push_tasks_enabled", "report_completed", True),
            ("mobile_push_reports_enabled", "report_completed", True),
            ("mobile_push_report_updates_enabled", "report_visible", True),
        ]
    )
    @patch("posthog.tasks.push_notifications.send_push_to_user", return_value=1)
    def test_report_preferences_select_category_at_delivery(self, key, kind, allowed, mock_send):
        report = self._report(SignalReport.Status.READY, first_visible_at=VISIBLE_AT)
        self.user.partial_notification_settings = {key: False}
        self.user.save(update_fields=["partial_notification_settings"])
        send_user_push(
            self.user.id,
            "Report",
            "Update",
            {"type": "report", "project_id": self.team.id, "report_id": str(report.id), "notificationKind": kind},
        )
        self.assertEqual(mock_send.call_count, int(allowed))

    @parameterized.expand(
        [
            ("report_visible", False, False, False),
            ("pull_request_ready", False, False, False),
            ("report_completed", False, False, False),
            ("report_pr_merged", False, False, False),
            ("report_completed", None, False, True),
            ("report_completed", True, False, True),
            ("report_completed", False, True, True),
        ]
    )
    @patch("posthog.tasks.push_notifications.send_push_to_user", return_value=1)
    def test_report_inbox_destination_gates_producer_and_queued_delivery(
        self, kind: str, inbox: bool | None, editor_only: bool, allowed: bool, mock_send
    ) -> None:
        report = self._report(SignalReport.Status.READY, first_visible_at=VISIBLE_AT)
        config = SignalScoutConfig.objects.for_team(self.team.id).create(
            team=self.team,
            skill_name="signals-scout-example",
            output_destinations={} if inbox is None else {"inbox": inbox},
        )
        task = Task.objects.create(team=self.team, created_by=self.user)
        run = TaskRun.objects.create(task=task, team=self.team)
        SignalScoutRun.objects.for_team(self.team.id).create(
            team=self.team,
            task_run=run,
            scout_config=config,
            skill_name=config.skill_name,
            skill_version=1,
            emitted_report_ids=[] if editor_only else [str(report.id)],
            edited_report_ids=[str(report.id)] if editor_only else [],
        )
        with self.captureOnCommitCallbacks(execute=True):
            _push_report(report, [self.user], kind=kind, title="Report update", body="Updated")
        self.assertEqual(self.send_push.call_count, int(allowed))
        if kind == "report_completed" and not allowed:
            task.state = {"created_on_mobile": True}
            task.signal_report = report
            task.save(update_fields=["state", "signal_report"])
            append_task_run_artefact(
                team_id=self.team.id,
                report_id=str(report.id),
                product="signals",
                type="implementation",
                task_id=str(task.id),
                run_id=str(run.id),
            )
            with self.captureOnCommitCallbacks(execute=True):
                notify_task_run_completed(task_run_id=str(run.id), team_id=run.team_id)
            self.send_push.assert_not_called()
        send_user_push(
            self.user.id,
            "Report update",
            "Updated",
            {
                "type": "report",
                "project_id": self.team.id,
                "report_id": str(report.id),
                "notificationKind": kind,
            },
        )
        self.assertEqual(mock_send.call_count, int(allowed))
        if allowed and not editor_only:
            config.output_destinations = {"inbox": False}
            config.save(update_fields=["output_destinations"])
            queued_user_id, queued_title, queued_body, queued_data = self.send_push.call_args.args
            send_user_push(queued_user_id, queued_title, queued_body, queued_data)
            self.assertEqual(mock_send.call_count, 1)
