from types import SimpleNamespace
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from products.signals.backend.github_mention import process
from products.signals.backend.github_mention.identity import MentionIdentity, MentionIdentityStatus
from products.signals.backend.models import GitHubPendingMention
from products.tasks.backend.facade import api as tasks_facade

PR_URL = "https://github.com/acme/app/pull/7"
REPO = "acme/app"


class TestProcessGitHubMention(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.report_id = str(uuid4())
        self.context = SimpleNamespace(
            team_id=self.team.id,
            signal_report_id=self.report_id,
            github_integration_id=1,
            head_branch="posthog/instrumentation-abc",
        )
        patch.object(tasks_facade, "resolve_signal_pr_mention_context", return_value=self.context).start()
        patch.object(tasks_facade, "is_task_run_terminal", return_value=True).start()

        self.github = MagicMock()
        self.github.get_pull_request.return_value = {"success": True, "body": "Please rename the helper"}
        self.github.list_pull_request_comments.return_value = {"success": True, "comments": []}
        patch.object(process.GitHubIntegration, "first_for_team_repository", return_value=self.github).start()

        self.created = SimpleNamespace(task_id=uuid4(), latest_run=SimpleNamespace(id=uuid4()))
        self.create_task = patch.object(tasks_facade, "create_and_run_task", return_value=self.created).start()
        self.record = patch.object(process, "record_implementation_task").start()
        self.mapping_create = patch.object(process.GitHubMentionTaskMapping.objects, "create").start()
        self.addCleanup(patch.stopall)

    def _run(self) -> None:
        process.process_github_mention.apply(
            kwargs={
                "team_id": self.team.id,
                "pr_url": PR_URL,
                "repository": REPO,
                "comment_id": 55,
                "commenter_account_id": 999,
                "commenter_login": "octo",
                "installation_id": "42",
            },
            throw=True,
        )

    def _identity(self, status: MentionIdentityStatus, user=None) -> MentionIdentity:
        return MentionIdentity(status=status, user=user, user_github_integration=MagicMock() if user else None)

    def test_eligible_launches_mention_run_with_expected_config(self) -> None:
        with patch.object(
            process,
            "resolve_commenter_identity",
            return_value=self._identity(MentionIdentityStatus.ELIGIBLE, self.user),
        ):
            self._run()

        self.create_task.assert_called_once()
        kwargs = self.create_task.call_args.kwargs
        self.assertEqual(kwargs["origin_product"], tasks_facade.TaskOriginProduct.GITHUB_MENTION)
        self.assertFalse(kwargs["create_pr"])
        self.assertEqual(kwargs["branch"], "posthog/instrumentation-abc")
        self.assertEqual(kwargs["user_id"], self.user.id)
        self.assertEqual(kwargs["signal_report_id"], self.report_id)
        self.assertEqual(kwargs["interaction_origin"], "github")
        self.github.add_reaction_to_comment.assert_called_once_with(REPO, 55, "eyes")

    def test_eligible_records_report_run_as_billing_exempt(self) -> None:
        with patch.object(
            process,
            "resolve_commenter_identity",
            return_value=self._identity(MentionIdentityStatus.ELIGIBLE, self.user),
        ):
            self._run()

        self.record.assert_called_once()
        self.assertEqual(self.record.call_args.kwargs["billing_exempt_reason"], "github_mention_followup")

    def test_needs_connect_gates_with_link_and_pending_row(self) -> None:
        self.context.signal_report_id = None  # avoid the report FK; this case tests gating, not linkage
        with patch.object(
            process, "resolve_commenter_identity", return_value=self._identity(MentionIdentityStatus.NEEDS_CONNECT)
        ):
            self._run()

        self.create_task.assert_not_called()
        self.github.comment_on_pull_request.assert_called_once()
        self.assertIn("connect", self.github.comment_on_pull_request.call_args.args[2].lower())
        self.assertEqual(GitHubPendingMention.objects.for_team(self.team.id).count(), 1)

    def test_not_member_rejects_without_launch_or_pending_row(self) -> None:
        with patch.object(
            process, "resolve_commenter_identity", return_value=self._identity(MentionIdentityStatus.NOT_MEMBER)
        ):
            self._run()

        self.create_task.assert_not_called()
        self.github.comment_on_pull_request.assert_called_once()
        self.assertEqual(GitHubPendingMention.objects.for_team(self.team.id).count(), 0)

    def test_eligible_forwards_into_active_run_instead_of_starting_a_new_one(self) -> None:
        # One shared run per PR: a comment arriving while a run is active is fed into that run.
        run_id, task_id = uuid4(), uuid4()
        with (
            patch.object(process, "_active_mention_run", return_value=(run_id, task_id)),
            patch.object(tasks_facade, "signal_task_run_user_message", return_value=True) as signal,
            patch.object(
                process,
                "resolve_commenter_identity",
                return_value=self._identity(MentionIdentityStatus.ELIGIBLE, self.user),
            ),
        ):
            self._run()

        self.create_task.assert_not_called()  # no parallel/new run
        signal.assert_called_once()
        self.assertEqual(signal.call_args.kwargs["run_id"], str(run_id))
        self.assertEqual(signal.call_args.kwargs["task_id"], str(task_id))
        self.github.add_reaction_to_comment.assert_called_once_with(REPO, 55, "eyes")
