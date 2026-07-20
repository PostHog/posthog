from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.review_hog.backend.models import ReviewReport
from products.review_hog.backend.reviewer.artefact_content import ThreadVerdictArtefact
from products.review_hog.backend.reviewer.persistence import load_thread_verdicts, persist_thread_verdict
from products.review_hog.backend.temporal.resolution import ResolveThreadsInput, _deliver_side_effects

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
        return ReviewReport.objects.create(
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
