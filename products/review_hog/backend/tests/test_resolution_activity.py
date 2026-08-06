from contextlib import ExitStack

import pytest
from posthog.test.base import BaseTest, NonAtomicBaseTest
from unittest.mock import AsyncMock, Mock, patch

from asgiref.sync import async_to_sync
from parameterized import parameterized

from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.models.user import User

from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact
from products.review_hog.backend.reviewer.artefact_content import ThreadVerdictArtefact
from products.review_hog.backend.reviewer.models.github_meta import PRMetadata
from products.review_hog.backend.reviewer.models.thread_resolution import ThreadResolution
from products.review_hog.backend.reviewer.persistence import load_thread_verdicts, persist_thread_verdict
from products.review_hog.backend.reviewer.tools.github_threads import ReviewThread, ThreadComment
from products.review_hog.backend.temporal.resolution import (
    ResolutionRunResult,
    ResolveThreadsInput,
    _append_run_note,
    _append_task_run,
    _deliver_side_effects,
    _prepare_run,
    resolve_threads_activity,
)
from products.tasks.backend.models import Task


def _pr_metadata() -> PRMetadata:
    return PRMetadata(
        number=123,
        title="t",
        state="open",
        draft=False,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        author="octocat",
        base_branch="master",
        head_branch="feature",
        head_sha="deadbeef",
        commits=1,
        additions=1,
        deletions=0,
        changed_files=1,
    )


_RESOLUTION = "products.review_hog.backend.temporal.resolution"


def _verdict(
    thread_id: str = "PRRT_1",
    *,
    outcome: str = "fixed",
    author_is_bot: bool = True,
    reply_posted: bool = False,
    resolved: bool = False,
    commit_sha: str | None = "abc123",
) -> ThreadVerdictArtefact:
    return ThreadVerdictArtefact(
        thread_id=thread_id,
        outcome=outcome,
        path="f.py",
        author_login="someone",
        author_is_bot=author_is_bot,
        reasoning="checked the code",
        reply="what happened and why",
        commit_sha=commit_sha,
        latest_comment_id=100,
        reply_posted=reply_posted,
        resolved=resolved,
    )


class TestResolutionPersistenceAndDelivery(BaseTest):
    def _report(self) -> ReviewReport:
        # ReviewReport is fail-closed (TeamScopedRootMixin), so creation outside request context
        # goes through for_team — the same path the funnel uses.
        return ReviewReport.objects.for_team(self.team.id).create(
            team=self.team,
            repository="posthog/posthog",
            pr_number=123,
            pr_url="https://github.com/PostHog/posthog/pull/123",
            head_branch="feature",
            base_branch="master",
        )

    def _input(self) -> ResolveThreadsInput:
        return ResolveThreadsInput(
            team_id=self.team.id,
            user_id=self.user.id,
            acting_user_id=self.user.id,
            owner="posthog",
            repo="posthog",
            pr_number=123,
        )

    def test_thread_verdict_round_trip_is_latest_wins_per_thread(self) -> None:
        report = self._report()
        persist_thread_verdict(team_id=self.team.id, report_id=str(report.id), verdict=_verdict(outcome="escalate"))
        persist_thread_verdict(
            team_id=self.team.id,
            report_id=str(report.id),
            verdict=_verdict(outcome="fixed", reply_posted=True, resolved=True),
        )
        persist_thread_verdict(
            team_id=self.team.id, report_id=str(report.id), verdict=_verdict("PRRT_2", outcome="wont_fix")
        )

        verdicts = load_thread_verdicts(team_id=self.team.id, report_id=str(report.id))
        assert set(verdicts) == {"PRRT_1", "PRRT_2"}
        assert verdicts["PRRT_1"].outcome == "fixed"
        assert verdicts["PRRT_1"].resolved is True

    @parameterized.expand(
        [
            # (name, author_is_bot, outcome, expect_resolve_called)
            ("bot_terminal_resolves", True, "fixed", True),
            ("human_thread_never_resolved", False, "fixed", False),
            ("escalate_never_resolved", True, "escalate", False),
        ]
    )
    def test_delivery_resolve_etiquette(
        self, _name: str, author_is_bot: bool, outcome: str, expect_resolve: bool
    ) -> None:
        report = self._report()
        verdict = _verdict(
            author_is_bot=author_is_bot, outcome=outcome, commit_sha="abc123" if outcome == "fixed" else None
        )
        persist_thread_verdict(team_id=self.team.id, report_id=str(report.id), verdict=verdict)

        with (
            patch(f"{_RESOLUTION}.reply_to_thread", return_value=(555, "https://github.com/x")) as reply,
            patch(f"{_RESOLUTION}.resolve_thread", return_value=True) as resolve,
            patch(f"{_RESOLUTION}.commit_on_branch", return_value=True),
            patch(f"{_RESOLUTION}._installation_auth", return_value=("token", None)),
        ):
            _deliver_side_effects(self._input(), str(report.id), verdict, branch="feature")

        assert reply.call_count == 1
        assert resolve.call_count == (1 if expect_resolve else 0)
        stored = load_thread_verdicts(team_id=self.team.id, report_id=str(report.id))["PRRT_1"]
        assert stored.reply_posted is True
        assert stored.resolved is expect_resolve
        # The watermark advances to our own posted reply so it can't re-open triage next run.
        assert stored.latest_comment_id == 555

    def test_fixed_reply_links_the_commit(self) -> None:
        report = self._report()
        verdict = _verdict(outcome="fixed", commit_sha="abc123")
        with (
            patch(f"{_RESOLUTION}.reply_to_thread", return_value=(555, None)) as reply,
            patch(f"{_RESOLUTION}.resolve_thread", return_value=True),
            patch(f"{_RESOLUTION}.commit_on_branch", return_value=True),
            patch(f"{_RESOLUTION}._installation_auth", return_value=("token", None)),
        ):
            _deliver_side_effects(self._input(), str(report.id), verdict, branch="feature")
        assert "https://github.com/posthog/posthog/commit/abc123" in reply.call_args.kwargs["body"]

    def test_unverified_commit_withholds_link_and_resolve(self) -> None:
        # The exact failure this guard exists for: a hallucinated or off-branch SHA must not become
        # a public "Fix commit" link, and must not auto-close the thread.
        report = self._report()
        verdict = _verdict(author_is_bot=True, outcome="fixed", commit_sha="deadbee")
        with (
            patch(f"{_RESOLUTION}.reply_to_thread", return_value=(555, None)) as reply,
            patch(f"{_RESOLUTION}.resolve_thread", return_value=True) as resolve,
            patch(f"{_RESOLUTION}.commit_on_branch", return_value=False),
            patch(f"{_RESOLUTION}._installation_auth", return_value=("token", None)),
        ):
            _deliver_side_effects(self._input(), str(report.id), verdict, branch="feature")

        assert "Fix commit" not in reply.call_args.kwargs["body"]
        assert resolve.call_count == 0
        stored = load_thread_verdicts(team_id=self.team.id, report_id=str(report.id))["PRRT_1"]
        assert stored.commit_verified is False
        assert stored.reply_posted is True
        assert stored.resolved is False

    def test_run_note_names_delivery_failures(self) -> None:
        # A token-expiry tail must be visible in the durable run note, not just worker logs.
        report = self._report()
        _append_run_note(
            self._input(),
            str(report.id),
            ResolutionRunResult(report_id=str(report.id), triaged=1, outcomes={"fixed": 1}, undelivered=2),
        )
        note = ReviewReportArtefact.objects.for_team(self.team.id).get(report_id=report.id, type="note")
        assert "2 thread(s) hit delivery failures" in note.content

    def test_failed_resolve_leaves_a_redeliverable_verdict(self) -> None:
        report = self._report()
        verdict = _verdict(author_is_bot=True, outcome="fixed")
        with (
            patch(f"{_RESOLUTION}.reply_to_thread", return_value=(555, None)),
            patch(f"{_RESOLUTION}.resolve_thread", side_effect=RuntimeError("token cannot resolve")),
            patch(f"{_RESOLUTION}.commit_on_branch", return_value=True),
            patch(f"{_RESOLUTION}._installation_auth", return_value=("token", None)),
        ):
            _deliver_side_effects(self._input(), str(report.id), verdict, branch="feature")
        stored = load_thread_verdicts(team_id=self.team.id, report_id=str(report.id))["PRRT_1"]
        # The reply survived (posted once), the resolve stays due — exactly what the pre-filter redelivers.
        assert stored.reply_posted is True
        assert stored.resolved is False

    def test_task_run_artefact_lands_attributed_to_the_session_task(self) -> None:
        # The helper is best-effort (it swallows errors), so a wrong attribution doesn't fail the
        # run — the artefact just silently never lands. This asserts the row actually exists.
        report = self._report()
        task = Task.objects.create(
            team=self.team,
            title="resolution session",
            description="",
            origin_product=Task.OriginProduct.REVIEW_HOG,
            repository="posthog/posthog",
        )
        session = Mock()
        session.task_run.task_id = task.id
        session.task_run.id = "run-1"

        _append_task_run(self._input(), str(report.id), session)

        artefact = ReviewReportArtefact.objects.for_team(self.team.id).get(report_id=report.id, type="task_run")
        assert artefact.task_id == task.id

    def test_noop_run_writes_a_run_note_and_idles_the_report(self) -> None:
        with (
            patch(f"{_RESOLUTION}._installation_auth", return_value=("token", "inst-1")),
            patch(f"{_RESOLUTION}._fetch_pr_metadata", return_value=_pr_metadata()),
            patch(f"{_RESOLUTION}.fetch_unresolved_threads", return_value=[]),
        ):
            result = _prepare_run(self._input())

        assert isinstance(result, ResolutionRunResult)
        assert result.skipped_reason == "no_unresolved_threads"
        report = ReviewReport.objects.for_team(self.team.id).get(repository="posthog/posthog", pr_number=123)
        assert report.status == ReviewReport.Status.IDLE
        note = ReviewReportArtefact.objects.for_team(self.team.id).get(report_id=report.id, type="note")
        assert "0 thread(s) triaged" in note.content


class TestFailedRunActivity(NonAtomicBaseTest):
    """NonAtomic because the activity does its DB work via database_sync_to_async(thread_sensitive=False)
    — separate connections that can't see an unfinished test transaction. Fixtures are rebuilt in
    setUp: the base flushes class-level data after every test."""

    def setUp(self) -> None:
        self.organization = Organization.objects.create(name="Test Org")
        self.team = Team.objects.create(organization=self.organization, name="Test Team")
        self.user = User.objects.create_user(email="rh-activity@example.com", first_name="RH", password="password")

    def _input(self) -> ResolveThreadsInput:
        return ResolveThreadsInput(
            team_id=self.team.id,
            user_id=self.user.id,
            acting_user_id=self.user.id,
            owner="posthog",
            repo="posthog",
            pr_number=123,
        )

    def _thread(self, thread_id: str) -> ReviewThread:
        return ReviewThread(
            thread_id=thread_id,
            path="f.py",
            comments=[ThreadComment(id=1, author_login="greptile", author_is_bot=True, body="fix this")],
        )

    def _base_patches(self, mock_activity: Mock, threads: list[ReviewThread]) -> list:
        return [
            patch(f"{_RESOLUTION}._installation_auth", return_value=("token", "inst-1")),
            patch(f"{_RESOLUTION}._fetch_pr_metadata", return_value=_pr_metadata()),
            patch(f"{_RESOLUTION}.fetch_unresolved_threads", return_value=threads),
            patch(
                f"{_RESOLUTION}.load_resolution_skill_for_run",
                return_value=Mock(skill_name="review-hog-resolution-criteria", version=1),
            ),
            patch(f"{_RESOLUTION}.activity", mock_activity),
            patch(f"{_RESOLUTION}.Heartbeater"),
            patch(f"{_RESOLUTION}._sandbox_workflow_id_prefix", return_value="test-prefix"),
        ]

    def _report_status(self) -> str:
        return ReviewReport.objects.for_team(self.team.id).get(repository="posthog/posthog", pr_number=123).status

    def test_failed_run_idles_the_report_only_when_no_retry_is_coming(self) -> None:
        mock_activity = Mock()
        with ExitStack() as stack:
            for p in self._base_patches(mock_activity, [self._thread("PRRT_9")]):
                stack.enter_context(p)
            stack.enter_context(patch(f"{_RESOLUTION}.start_sandbox_session", side_effect=RuntimeError("sandbox down")))
            for attempt, expected in ((1, ReviewReport.Status.ACTIVE), (2, ReviewReport.Status.IDLE)):
                mock_activity.info.return_value.attempt = attempt
                with pytest.raises(RuntimeError, match="sandbox down"):
                    async_to_sync(resolve_threads_activity)(self._input())
                assert self._report_status() == expected

    def test_poison_thread_skips_on_final_attempt_once_turns_have_landed(self) -> None:
        # T1 triages fine, T2's turn dies (final-attempt skip closes the session), T3's fresh
        # session-open dies too. With a completed turn behind it that must degrade to a skip —
        # not fail the run, which would block this PR's resolution forever.
        mock_activity = Mock()
        mock_activity.info.return_value.attempt = 2
        session = Mock()
        session.task_run.task_id = "11111111-1111-1111-1111-111111111111"
        session.task_run.id = "run-1"
        res1 = ThreadResolution(thread_id="PRRT_A", outcome="wont_fix", reasoning="checked", reply="declined")
        with ExitStack() as stack:
            for p in self._base_patches(mock_activity, [self._thread(t) for t in ("PRRT_A", "PRRT_B", "PRRT_C")]):
                stack.enter_context(p)
            stack.enter_context(
                patch(
                    f"{_RESOLUTION}.start_sandbox_session",
                    AsyncMock(side_effect=[(session, res1), RuntimeError("open failed")]),
                )
            )
            stack.enter_context(
                patch(f"{_RESOLUTION}.continue_sandbox_session", AsyncMock(side_effect=RuntimeError("turn failed")))
            )
            stack.enter_context(patch(f"{_RESOLUTION}.end_sandbox_session", AsyncMock()))
            stack.enter_context(patch(f"{_RESOLUTION}.reply_to_thread", return_value=(555, None)))
            stack.enter_context(patch(f"{_RESOLUTION}.resolve_thread", return_value=True))

            result = async_to_sync(resolve_threads_activity)(self._input())

        assert result.triaged == 1
        assert result.outcomes == {"wont_fix": 1}
        assert result.failed_turns == 2
        assert self._report_status() == ReviewReport.Status.IDLE
