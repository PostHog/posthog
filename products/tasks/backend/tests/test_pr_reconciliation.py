from itertools import product

from unittest.mock import MagicMock, patch

from django.db import transaction
from django.test import TestCase

from celery.exceptions import Retry
from parameterized import parameterized
from requests.exceptions import (
    ConnectionError as RequestsConnectionError,
    Timeout as RequestsTimeout,
)

from posthog.egress.github.transport import GitHubEgressBudgetExhausted, GitHubRateLimitError
from posthog.models import Organization, OrganizationMembership, Team, User
from posthog.models.github_integration_base import GitHubIntegrationError
from posthog.models.integration import Integration
from posthog.models.user_integration import UserIntegration

from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportPullRequest
from products.tasks.backend.facade.api import set_task_run_output, update_task_run
from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.tasks.tasks import reconcile_task_run_pull_request
from products.tasks.backend.webhooks import handle_pull_request_event


class TestPullRequestReconciliation(TestCase):
    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Example organization")
        self.team = Team.objects.create(organization=self.organization)
        self.user = User.objects.create(email="developer@example.com")
        OrganizationMembership.objects.create(user=self.user, organization=self.organization)
        self.integration = Integration.objects.create(team=self.team, kind="github", integration_id="707070")
        self.report = SignalReport.objects.create(team=self.team, title="Improve widget navigation", status="ready")
        self.task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="Improve widget navigation",
            repository="example/widgets",
            github_integration=self.integration,
            signal_report=self.report,
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
        )
        SignalReportArtefact.objects.create(
            team=self.team, report=self.report, task=self.task, type="task_run", content="{}"
        )
        self.task_run = TaskRun.objects.create(team=self.team, task=self.task, branch="feature/navigation", output={})
        self.url = "https://github.com/example/widgets/pull/17"
        self.snapshot: dict[str, object] = {
            "success": True,
            "url": self.url,
            "head_branch": self.task_run.branch,
            "head_repository": self.task.repository,
            "state": "open",
            "draft": False,
            "merged": False,
        }
        self.fetch = self._patch("posthog.models.github_integration_base.GitHubIntegrationBase.get_pull_request")
        self.fetch.return_value = self.snapshot
        self.enqueue = self._patch("products.tasks.backend.tasks.tasks.reconcile_task_run_pull_request.delay")
        self.link = self._patch("products.signals.backend.tasks.link_report_tracker_issues.delay")
        self.analytics = self._patch("posthog.github.pull_request_events.posthoganalytics.capture")
        self._patch("products.tasks.backend.facade.api.posthoganalytics.feature_enabled").return_value = False
        self._patch("products.tasks.backend.models.TaskRun.publish_stream_state_event")
        self._patch("products.tasks.backend.models.TaskRun.publish_stream_event")
        self._patch("products.tasks.backend.models.TaskRun.emit_progress_event")
        self._patch("products.signals.backend.tasks.refresh_pull_request_review_decision.delay")

    def _patch(self, target: str) -> MagicMock:
        patcher = patch(target)
        mocked = patcher.start()
        self.addCleanup(patcher.stop)
        return mocked

    def _write(self, writer: str = "patch", *, secondary: bool = False) -> None:
        output = (
            {"pr_url": "https://github.com/example/widgets/pull/16", "pr_urls": [self.url]}
            if secondary
            else {"pr_url": self.url}
        )
        with self.captureOnCommitCallbacks(execute=True):
            if writer == "patch":
                update_task_run(self.task_run.id, self.task.id, self.team.id, validated_data={"output": output})
            else:
                set_task_run_output(self.task_run.id, self.task.id, self.team.id, output=output)

    def _reconcile(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            reconcile_task_run_pull_request.run(team_id=self.team.id, run_id=str(self.task_run.id), pr_url=self.url)

    def _webhook(self, *, merged: bool = False) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            handle_pull_request_event(
                {
                    "action": "closed" if merged else "opened",
                    "installation": {"id": 707070},
                    "repository": {"full_name": "example/widgets"},
                    "pull_request": {
                        "number": 17,
                        "html_url": self.url,
                        "state": "closed" if merged else "open",
                        "merged": merged,
                        "head": {"ref": "feature/navigation", "repo": {"full_name": "example/widgets"}},
                    },
                }
            )

    @parameterized.expand(list(product(("patch", "set_output"), (False, True), (False, True))))
    def test_arrival_orders_restore_report_linking(self, writer: str, webhook_first: bool, secondary: bool) -> None:
        if webhook_first:
            self._webhook()
        self._write(writer, secondary=secondary)
        self.link.reset_mock()
        if not webhook_first:
            self._webhook()
        captures = self.analytics.call_count
        self._reconcile()
        self.task_run.refresh_from_db()
        assert isinstance(self.task_run.output, dict)
        self.assertIn(self.url, self.task_run.state["verified_pr_urls"])
        self.assertTrue(SignalReportArtefact.objects.filter(report=self.report, type="pull_request").exists())
        self.link.assert_any_call(team_id=self.team.id, task_id=str(self.task.id), pr_url=self.url)
        self.assertEqual(self.analytics.call_count, captures)
        self.assertEqual(
            self.task_run.output["pr_url"], self.url if not secondary else "https://github.com/example/widgets/pull/16"
        )
        calls = self.link.call_count
        self._reconcile()
        self.assertEqual(self.link.call_count, calls)

    @parameterized.expand(list(product(("open", "draft", "closed", "merged"), (False, True))))
    def test_reconciles_current_status(self, state: str, secondary: bool) -> None:
        self._write(secondary=secondary)
        self.snapshot.update(
            state="closed" if state in {"closed", "merged"} else "open",
            draft=state == "draft",
            merged=state == "merged",
        )
        self._reconcile()
        self.task_run.refresh_from_db()
        assert isinstance(self.task_run.output, dict)
        if secondary:
            self.assertNotIn("pr_state", self.task_run.output)
            self.assertNotIn("pr_merged", self.task_run.output)
        else:
            self.assertEqual(self.task_run.output["pr_state"], state)
            self.assertEqual(self.task_run.output["pr_merged"], state == "merged")
        pr = SignalReportPullRequest.objects.for_team(self.team.id).get(number=17)
        self.assertEqual(pr.state, state)

    @parameterized.expand(
        [
            ("fork",),
            ("branch",),
            ("url",),
            ("repository",),
            ("reviewhog",),
            ("deleted",),
            ("removed_url",),
            ("missing_integration",),
            ("stronger_match",),
        ]
    )
    def test_rejects_ineligible_attachment(self, reason: str) -> None:
        self._write()
        if reason == "fork":
            self.snapshot["head_repository"] = "another/widgets"
        elif reason == "branch":
            self.snapshot["head_branch"] = "another-branch"
        elif reason == "url":
            self.snapshot["url"] = "https://github.com/example/widgets/pull/18"
        elif reason == "repository":
            Task.objects.filter(id=self.task.id).update(repository="example/other")
        elif reason == "reviewhog":
            Task.objects.filter(id=self.task.id).update(origin_product=Task.OriginProduct.REVIEW_HOG)
        elif reason == "deleted":
            Task.objects.filter(id=self.task.id).update(deleted=True)
        elif reason == "removed_url":
            TaskRun.objects.filter(id=self.task_run.id).update(output={})
        elif reason == "missing_integration":
            Task.objects.filter(id=self.task.id).update(github_integration=None)
        elif reason == "stronger_match":
            TaskRun.objects.create(team=self.team, task=self.task, state={"verified_pr_urls": [self.url]})
        self.link.reset_mock()
        self._reconcile()
        self.task_run.refresh_from_db()
        assert isinstance(self.task_run.output, dict)
        self.assertNotIn(self.url, (self.task_run.state or {}).get("verified_pr_urls", []))
        self.link.assert_not_called()

    def test_webhook_wins_while_fetch_is_in_flight(self) -> None:
        self._write()

        def fetch(repository: str, number: int) -> dict[str, object]:
            self._webhook(merged=True)
            return self.snapshot

        self.fetch.side_effect = fetch
        self._reconcile()
        self.task_run.refresh_from_db()
        assert isinstance(self.task_run.output, dict)
        self.assertEqual(self.task_run.output["pr_state"], "merged")
        self.assertTrue(self.task_run.output["pr_merged"])

    def test_rechecks_branch_after_fetch(self) -> None:
        self._write()

        def fetch(repository: str, number: int) -> dict[str, object]:
            TaskRun.objects.filter(id=self.task_run.id).update(branch="another-branch")
            return self.snapshot

        self.fetch.side_effect = fetch
        self._reconcile()
        self.task_run.refresh_from_db()
        assert isinstance(self.task_run.output, dict)
        self.assertNotIn("verified_pr_urls", self.task_run.state)

    def test_branch_arriving_after_url_schedules_reconciliation(self) -> None:
        TaskRun.objects.filter(id=self.task_run.id).update(branch=None)
        self._write()
        self._reconcile()
        self.enqueue.reset_mock()
        with self.captureOnCommitCallbacks(execute=True):
            update_task_run(
                self.task_run.id, self.task.id, self.team.id, validated_data={"branch": "feature/navigation"}
            )
        self.enqueue.assert_called_once_with(team_id=self.team.id, run_id=str(self.task_run.id), pr_url=self.url)
        self._reconcile()
        self.task_run.refresh_from_db()
        assert isinstance(self.task_run.output, dict)
        self.assertIn(self.url, self.task_run.state["verified_pr_urls"])

    def test_rollback_does_not_enqueue(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            with transaction.atomic():
                update_task_run(
                    self.task_run.id, self.task.id, self.team.id, validated_data={"output": {"pr_url": self.url}}
                )
                transaction.set_rollback(True)
        self.enqueue.assert_not_called()

    def test_personal_integration(self) -> None:
        personal = UserIntegration.objects.create(user=self.user, kind="github", integration_id="808080")
        Task.objects.filter(id=self.task.id).update(github_integration=None, github_user_integration=personal)
        self._write()
        self._reconcile()
        self.task_run.refresh_from_db()
        assert isinstance(self.task_run.output, dict)
        self.assertIn(self.url, self.task_run.state["verified_pr_urls"])

    def _attempt(self, retries: int) -> None:
        reconcile_task_run_pull_request.push_request(
            retries=retries,
            called_directly=False,
            is_eager=False,
            args=(),
            kwargs={"team_id": self.team.id, "run_id": str(self.task_run.id), "pr_url": self.url},
        )
        try:
            self._reconcile()
        finally:
            reconcile_task_run_pull_request.pop_request()

    @parameterized.expand(
        [
            ("server", GitHubIntegrationError("server unavailable"), 0),
            ("rate_limit", GitHubRateLimitError("rate limited", retry_after=1200), 1200),
            ("budget", GitHubEgressBudgetExhausted("budget exhausted"), 0),
            ("connection", RequestsConnectionError("connection unavailable"), 0),
            ("timeout", RequestsTimeout("request timed out"), 0),
        ]
    )
    def test_retries_transient_errors(self, _name: str, error: Exception, retry_after: int) -> None:
        self._write()
        self.fetch.side_effect = error
        with patch.object(reconcile_task_run_pull_request, "apply_async") as publish:
            for attempt, delay in enumerate([60, 120, 240, 480, 900]):
                with self.assertRaises(Retry):
                    self._attempt(attempt)
                self.assertEqual(publish.call_count, attempt + 1)
                self.assertEqual(publish.call_args.kwargs["countdown"], max(delay, retry_after))
                self.assertEqual(publish.call_args.kwargs["retries"], attempt + 1)
            with self.assertRaises(type(error)):
                self._attempt(5)
            self.assertEqual(publish.call_count, 5)
        self.assertEqual(self.fetch.call_count, 6)
        self.task_run.refresh_from_db()
        assert isinstance(self.task_run.output, dict)
        self.assertNotIn("verified_pr_urls", self.task_run.state)

    def test_retry_recovers_after_transient_failure(self) -> None:
        self._write()
        self.fetch.side_effect = [
            {"success": False, "status_code": 503},
            GitHubRateLimitError("rate limited", retry_after=180),
            self.snapshot,
        ]
        self.link.reset_mock()
        with patch.object(reconcile_task_run_pull_request, "apply_async") as publish:
            for attempt, delay in enumerate([60, 180]):
                with self.assertRaises(Retry):
                    self._attempt(attempt)
                self.assertEqual(publish.call_args.kwargs["countdown"], delay)
            self._attempt(2)
            self.assertEqual(publish.call_count, 2)
        self.task_run.refresh_from_db()
        self.assertIn(self.url, self.task_run.state["verified_pr_urls"])
        self.link.assert_called_once_with(team_id=self.team.id, task_id=str(self.task.id), pr_url=self.url)

    @parameterized.expand(
        [
            ("programming_error", TypeError("invalid snapshot")),
            ("missing_row", TaskRun.DoesNotExist()),
            ("bad_request", GitHubIntegrationError("bad request", status_code=400)),
        ]
    )
    def test_deterministic_errors_do_not_retry(self, _name: str, error: Exception) -> None:
        self._write()
        if _name == "bad_request":
            self.fetch.return_value = {"success": False, "status_code": 400}
        else:
            self.fetch.side_effect = error
        with patch.object(reconcile_task_run_pull_request, "apply_async") as publish:
            with self.assertRaises(type(error)):
                self._attempt(0)
            publish.assert_not_called()
        self.fetch.assert_called_once()

    def test_repeated_output_does_not_enqueue(self) -> None:
        self._write()
        self.enqueue.reset_mock()
        self._write()
        self.enqueue.assert_not_called()

    def test_reconciled_merge_leaves_wizard_completion_to_webhook(self) -> None:
        TaskRun.objects.filter(id=self.task_run.id).update(
            state={"wizard_config": {}}, status=TaskRun.Status.IN_PROGRESS
        )
        self._write()
        self.snapshot.update(state="closed", merged=True)
        with patch("products.tasks.backend.webhooks.signal_workflow_completion") as signal:
            self._reconcile()
            signal.assert_not_called()
            self._webhook(merged=True)
            self._webhook(merged=True)
        signal.assert_called_once_with(self.task_run.id, TaskRun.Status.COMPLETED, None)
        self.task_run.refresh_from_db()
        assert isinstance(self.task_run.output, dict)
        self.assertNotIn("reconciled_pr_merge_url", self.task_run.state)

    @parameterized.expand([("invalid_url",), ("inaccessible",), ("other_team",), ("foreign_personal_integration",)])
    def test_does_not_use_unavailable_pr_access(self, reason: str) -> None:
        self._write()
        if reason == "invalid_url":
            self.url = "https://example.com/example/widgets/pull/17"
        elif reason == "inaccessible":
            self.fetch.return_value = {"success": False, "status_code": 404}
        elif reason == "other_team":
            self.team = Team.objects.create(organization=self.organization)
        else:
            other_user = User.objects.create(email="other@example.com")
            personal = UserIntegration.objects.create(user=other_user, kind="github", integration_id="808080")
            Task.objects.filter(id=self.task.id).update(github_integration=None, github_user_integration=personal)
        self._reconcile()
        self.task_run.refresh_from_db()
        assert isinstance(self.task_run.output, dict)
        self.assertNotIn("verified_pr_urls", self.task_run.state)
        if reason != "inaccessible":
            self.fetch.assert_not_called()

    def test_failed_enqueue_preserves_output_write(self) -> None:
        self.enqueue.side_effect = ConnectionError("queue unavailable")
        self._write()
        self.task_run.refresh_from_db()
        assert isinstance(self.task_run.output, dict)
        self.assertEqual(self.task_run.output["pr_url"], self.url)

    def test_output_cannot_forge_reconciliation_state(self) -> None:
        with self.captureOnCommitCallbacks(execute=True):
            update_task_run(
                self.task_run.id,
                self.task.id,
                self.team.id,
                validated_data={"state": {"reconciled_pr_merge_url": self.url, "verified_pr_urls": [self.url]}},
            )
        self.task_run.refresh_from_db()
        assert isinstance(self.task_run.output, dict)
        self.assertNotIn("reconciled_pr_merge_url", self.task_run.state)
        self.assertNotIn("verified_pr_urls", self.task_run.state)
