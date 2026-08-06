from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from parameterized import parameterized

from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact
from products.review_hog.backend.reviewer.artefact_content import ThreadVerdictArtefact
from products.review_hog.backend.reviewer.models.github_meta import PRMetadata
from products.review_hog.backend.reviewer.persistence import load_thread_verdicts, persist_thread_verdict
from products.review_hog.backend.temporal.resolution import (
    ResolutionRunResult,
    ResolveThreadsInput,
    _append_task_run,
    _deliver_side_effects,
    _prepare_run,
)
from products.tasks.backend.models import Task

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
        ):
            _deliver_side_effects(self._input(), str(report.id), "token", None, verdict)

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
        ):
            _deliver_side_effects(self._input(), str(report.id), "token", None, verdict)
        assert "https://github.com/posthog/posthog/commit/abc123" in reply.call_args.kwargs["body"]

    def test_failed_resolve_leaves_a_redeliverable_verdict(self) -> None:
        report = self._report()
        verdict = _verdict(author_is_bot=True, outcome="fixed")
        with (
            patch(f"{_RESOLUTION}.reply_to_thread", return_value=(555, None)),
            patch(f"{_RESOLUTION}.resolve_thread", side_effect=RuntimeError("token cannot resolve")),
        ):
            _deliver_side_effects(self._input(), str(report.id), "token", None, verdict)
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
        meta = PRMetadata(
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
        with (
            patch(f"{_RESOLUTION}._installation_auth", return_value=("token", "inst-1")),
            patch(f"{_RESOLUTION}._fetch_pr_metadata", return_value=meta),
            patch(f"{_RESOLUTION}.fetch_unresolved_threads", return_value=[]),
        ):
            result = _prepare_run(self._input())

        assert isinstance(result, ResolutionRunResult)
        assert result.skipped_reason == "no_unresolved_threads"
        report = ReviewReport.objects.for_team(self.team.id).get(repository="posthog/posthog", pr_number=123)
        assert report.status == ReviewReport.Status.IDLE
        note = ReviewReportArtefact.objects.for_team(self.team.id).get(report_id=report.id, type="note")
        assert "0 thread(s) triaged" in note.content
