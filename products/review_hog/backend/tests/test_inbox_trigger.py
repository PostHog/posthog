import json

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized
from social_django.models import UserSocialAuth

from posthog.models.organization import OrganizationMembership
from posthog.models.user import User

# Imported at module scope so the heavy temporal package loads at collection time (like every other
# temporal test module); letting patch() import it mid-test would run the tasks sandbox-class
# resolution under test settings, where a local SANDBOX_PROVIDER env rejects DEBUG=False.
import products.review_hog.backend.temporal.client  # noqa: F401
from products.review_hog.backend.models import ReviewUserSettings
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.tasks.backend.models import Task, TaskRun

# `_start_review` imports the client at call time, so the defining module is the patch target.
_START = "products.review_hog.backend.temporal.client.start_review_pr_workflow"
_PR_URL = "https://github.com/posthog/posthog/pull/9"
_HEAD_BRANCH = "posthog-code/fix-the-thing"


class TestInboxTrigger(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.signal_report = SignalReport.objects.create(
            team=self.team, status=SignalReport.Status.IN_PROGRESS, signal_count=1, total_weight=1.0
        )
        # The report's assigned reviewer: an org member whose GitHub login the "For you"
        # resolution maps back to them.
        self.alice = self._org_member("alice@posthog.com", github_login="alice")

    def _org_member(self, email: str, *, github_login: str) -> User:
        user = User.objects.create(email=email)
        OrganizationMembership.objects.create(user=user, organization=self.organization)
        UserSocialAuth.objects.create(
            user=user, provider="github", uid=f"gh-{github_login}", extra_data={"login": github_login}
        )
        return user

    def _suggest_reviewers(self, logins: list[str]) -> None:
        SignalReportArtefact.objects.create(
            team=self.team,
            report=self.signal_report,
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
            content=json.dumps([{"github_login": login} for login in logins]),
        )

    def _opt_in(self, user: User) -> None:
        ReviewUserSettings.objects.for_team(self.team.id).create(team=self.team, user=user, review_inbox_prs=True)

    def _task(
        self,
        *,
        with_signal_report: bool = True,
        repository: str | None = "PostHog/posthog",
        internal: bool = False,
        created_by: User | None = None,
    ) -> Task:
        # created_by defaults to None: a background-created task must resolve its acting reviewer
        # from the report's assignment alone, never require a creator.
        return Task.objects.create(
            team=self.team,
            title="Implement the fix",
            description="from a signal report",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
            created_by=created_by,
            repository=repository,
            signal_report=self.signal_report if with_signal_report else None,
            internal=internal,
        )

    def _run(
        self,
        task: Task,
        *,
        status: str = TaskRun.Status.IN_PROGRESS,
        output: dict | None = None,
        branch: str | None = None,
    ) -> TaskRun:
        return TaskRun.objects.create(task=task, team=self.team, status=status, branch=branch, output=output)

    def _record_output(
        self,
        run: TaskRun,
        output: dict | None,
        *,
        update_fields: tuple[str, ...] | None = ("output", "updated_at"),
    ) -> None:
        # Simulates the two real writers: the agent server's PATCH (a full save, update_fields=None)
        # and the GitHub-webhook backstop (update_fields=["output", "updated_at"]) — inside a
        # commit-capture block because the workflow start must be deferred to commit (a
        # mid-transaction start could review work the transaction then rolls back).
        run.output = output
        with self.captureOnCommitCallbacks(execute=True):
            run.save(update_fields=list(update_fields) if update_fields is not None else None)
            self._mock_start.assert_not_called()

    @parameterized.expand(
        [
            # (name, run_status, update_fields) — the trigger must fire for live AND completed runs,
            # and for both real save shapes (webhook declares fields, the agent-server PATCH doesn't).
            ("webhook_shape_on_a_live_run", TaskRun.Status.IN_PROGRESS, ("output", "updated_at")),
            ("full_save_on_a_live_run", TaskRun.Status.IN_PROGRESS, None),
            ("completed_run", TaskRun.Status.COMPLETED, ("output", "updated_at")),
        ]
    )
    @patch(_START, return_value="wf-1")
    def test_recorded_pr_starts_a_review_as_the_assigned_reviewer(
        self, _name, status, update_fields, mock_start
    ) -> None:
        # The feature's spine: the run records its PR → the report's assigned reviewer (Inbox
        # "For you" semantics — the latest suggested_reviewers artefact, NOT Task.created_by,
        # which is None here) opted in → the review starts as that reviewer, publish on,
        # provenance attached. Run COMPLETION is never the trigger: on the tasks architecture a
        # successful run stays in_progress forever (the PR loop keeps it followable).
        self._mock_start = mock_start
        self._suggest_reviewers(["alice"])
        self._opt_in(self.alice)
        task = self._task()
        run = self._run(task)
        self._record_output(run, {"pr_url": _PR_URL, "head_branch": _HEAD_BRANCH}, update_fields=update_fields)

        # The PR leg wins over the branch leg when both targets are present.
        mock_start.assert_called_once_with(
            team_id=self.team.id,
            user_id=self.alice.id,
            publish=True,
            acting_user_id=self.alice.id,
            trigger_source="inbox",
            signal_report_id=str(task.signal_report_id),
            pr_url=_PR_URL,
        )

    @patch(_START, return_value="wf-1")
    def test_branch_only_output_starts_a_branch_review(self, mock_start) -> None:
        # `output.head_branch` is synced by the agent server as soon as the work branch exists —
        # before (or without) a PR. The branch leg reviews and stores; publish needs the PR leg.
        self._mock_start = mock_start
        self._suggest_reviewers(["alice"])
        self._opt_in(self.alice)
        task = self._task()
        self._record_output(self._run(task), {"head_branch": _HEAD_BRANCH})

        mock_start.assert_called_once_with(
            team_id=self.team.id,
            user_id=self.alice.id,
            publish=True,
            acting_user_id=self.alice.id,
            trigger_source="inbox",
            signal_report_id=str(task.signal_report_id),
            # Task.save lowercases the repository slug — the receiver forwards it as stored.
            repository="posthog/posthog",
            head_branch=_HEAD_BRANCH,
        )

    @patch(_START, return_value="wf-1")
    def test_run_creation_with_a_target_does_not_trigger(self, mock_start) -> None:
        # Creation saves are ignored: runs exist before the agent does anything, and a target on a
        # brand-new row (a retry seeded from a prior run) re-fires on its first real output save.
        self._mock_start = mock_start
        self._suggest_reviewers(["alice"])
        self._opt_in(self.alice)
        with self.captureOnCommitCallbacks(execute=True):
            self._run(self._task(), output={"pr_url": _PR_URL})

        mock_start.assert_not_called()

    @patch(_START, return_value="wf-1")
    def test_saves_that_do_not_touch_output_are_ignored(self, mock_start) -> None:
        # The run already carries a PR target, but a declared-fields save that doesn't touch
        # `output` (status flips, follow-up state persistence) must not re-fire a review — this is
        # also what retires the old completion trigger: a status-only flip alone starts nothing.
        self._mock_start = mock_start
        self._suggest_reviewers(["alice"])
        self._opt_in(self.alice)
        run = self._run(self._task(), output={"pr_url": _PR_URL})
        run.status = TaskRun.Status.COMPLETED
        with self.captureOnCommitCallbacks(execute=True):
            run.save(update_fields=["status"])

        mock_start.assert_not_called()

    @parameterized.expand([(TaskRun.Status.FAILED,), (TaskRun.Status.CANCELLED,)])
    @patch(_START, return_value="wf-1")
    def test_terminal_failure_states_do_not_trigger(self, status, mock_start) -> None:
        # A failed/cancelled run's PR is abandoned work — reviewing it wastes a sandbox run.
        self._mock_start = mock_start
        self._suggest_reviewers(["alice"])
        self._opt_in(self.alice)
        run = self._run(self._task(), status=status)
        self._record_output(run, {"pr_url": _PR_URL})

        mock_start.assert_not_called()

    @parameterized.expand(
        [
            # (name, reviewer_logins, expected_login) — both members opted in; the first login that
            # resolves to an org member is the canonical assignee whose options apply.
            ("first_resolved_reviewer_is_canonical", ["bob", "alice"], "bob"),
            ("unresolved_login_is_not_canonical", ["stranger", "alice"], "alice"),
        ]
    )
    @patch(_START, return_value="wf-1")
    def test_the_first_resolved_reviewer_is_canonical(self, _name, reviewer_logins, expected, mock_start) -> None:
        # With multiple assigned reviewers, the first one resolving to an org member is canonical
        # for which ReviewHog options apply (maintainer decision) — the review runs as them.
        self._mock_start = mock_start
        bob = self._org_member("bob@posthog.com", github_login="bob")
        users = {"alice": self.alice, "bob": bob}
        self._suggest_reviewers(reviewer_logins)
        for user in users.values():
            self._opt_in(user)
        self._record_output(self._run(self._task()), {"pr_url": _PR_URL})

        assert mock_start.call_args.kwargs["acting_user_id"] == users[expected].id
        assert mock_start.call_args.kwargs["user_id"] == users[expected].id

    @patch(_START, return_value="wf-1")
    def test_opted_out_canonical_reviewer_blocks_the_review(self, mock_start) -> None:
        # The canonical assignee's toggle is THE gate for background-created runs: if they kept the
        # default off, a later reviewer's opt-in must not hijack whose options the review runs with.
        self._mock_start = mock_start
        self._org_member("bob@posthog.com", github_login="bob")  # canonical, not opted in
        self._suggest_reviewers(["bob", "alice"])
        self._opt_in(self.alice)
        self._record_output(self._run(self._task()), {"pr_url": _PR_URL})

        mock_start.assert_not_called()

    @patch(_START, return_value="wf-1")
    def test_assigned_requester_gets_their_own_rules(self, mock_start) -> None:
        # A reviewer who personally asked for the implementation ("Create PR" — task.created_by)
        # gets THEIR ReviewHog rules applied to its review, even when they are not the report's
        # first reviewer and the first reviewer never opted in.
        self._mock_start = mock_start
        self._org_member("bob@posthog.com", github_login="bob")  # first reviewer, not opted in
        self._suggest_reviewers(["bob", "alice"])
        self._opt_in(self.alice)
        self._record_output(self._run(self._task(created_by=self.alice)), {"pr_url": _PR_URL})

        assert mock_start.call_args.kwargs["acting_user_id"] == self.alice.id
        assert mock_start.call_args.kwargs["user_id"] == self.alice.id

    @patch(_START, return_value="wf-1")
    def test_non_assigned_requester_follows_the_canonical_reviewer(self, mock_start) -> None:
        # A creator who is NOT among the assigned reviewers (a non-assigned teammate clicking
        # "Create PR", or a background system creator) carries no assignment meaning: the primary
        # assignee's rules govern — here they never opted in, so no review runs even though the
        # creator did.
        self._mock_start = mock_start
        self._org_member("bob@posthog.com", github_login="bob")  # canonical, not opted in
        charlie = self._org_member("charlie@posthog.com", github_login="charlie")  # not assigned
        self._suggest_reviewers(["bob"])
        self._opt_in(charlie)
        self._record_output(self._run(self._task(created_by=charlie)), {"pr_url": _PR_URL})

        mock_start.assert_not_called()

    @parameterized.expand(
        [
            # (name, with_signal_report, internal, reviewers, opt_in, output, repository)
            ("not_a_signals_task", False, False, ["alice"], True, {"pr_url": _PR_URL}, "o/r"),
            ("internal_pipeline_task", True, True, ["alice"], True, {"pr_url": _PR_URL}, "o/r"),
            ("no_reviewers_artefact", True, False, None, True, {"pr_url": _PR_URL}, "o/r"),
            ("reviewer_not_an_org_member", True, False, ["stranger"], True, {"pr_url": _PR_URL}, "o/r"),
            ("nobody_opted_in", True, False, ["alice"], False, {"pr_url": _PR_URL}, "o/r"),
            ("empty_output", True, False, ["alice"], True, {}, "o/r"),
            ("output_without_a_target", True, False, ["alice"], True, {"other": "x"}, "o/r"),
            ("branch_target_without_a_repository", True, False, ["alice"], True, {"head_branch": "b"}, None),
        ]
    )
    @patch(_START, return_value="wf-1")
    def test_gates_skip_without_starting_a_review(
        self, _name, with_signal_report, internal, reviewers, opt_in, output, repository, mock_start
    ) -> None:
        # Each gate protects real money (a sandbox review per trigger) or correctness: internal
        # pipeline tasks (research/repo-selection, created as the integration creator) must never
        # trigger, and reviews must only run for reports actually assigned to someone who opted in.
        self._mock_start = mock_start
        if reviewers is not None:
            self._suggest_reviewers(reviewers)
        if opt_in:
            self._opt_in(self.alice)
        task = self._task(with_signal_report=with_signal_report, repository=repository, internal=internal)
        # branch="master" on the row: the TaskRun.branch FIELD must never be treated as a target
        # (auto-start seeds it with the BASE branch; only output.head_branch is the pushed head).
        run = self._run(task, branch="master")
        self._record_output(run, output)

        mock_start.assert_not_called()

    @patch(_START, side_effect=RuntimeError("temporal down"))
    def test_workflow_start_failure_never_raises_into_the_save_path(self, mock_start) -> None:
        # The receiver runs inside tasks' save path: Temporal being down must cost a log line, not
        # break the run's output save.
        self._mock_start = mock_start
        self._suggest_reviewers(["alice"])
        self._opt_in(self.alice)
        self._record_output(self._run(self._task()), {"pr_url": _PR_URL})  # must not raise

        mock_start.assert_called_once()
