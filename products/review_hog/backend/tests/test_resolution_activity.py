import json
from contextlib import ExitStack

import pytest
from posthog.test.base import BaseTest, NonAtomicBaseTest
from unittest.mock import AsyncMock, Mock, patch

from asgiref.sync import async_to_sync
from parameterized import parameterized
from social_django.models import UserSocialAuth

from posthog.models.organization import Organization
from posthog.models.team import Team
from posthog.models.user import User

from products.review_hog.backend.models import ReviewReport, ReviewReportArtefact, ReviewSkillConfig
from products.review_hog.backend.reviewer.artefact_content import ResolutionRunArtefact, ThreadVerdictArtefact
from products.review_hog.backend.reviewer.constants import RESOLUTION_MAX_ATTEMPTS
from products.review_hog.backend.reviewer.lazy_seed import sync_canonical_resolution
from products.review_hog.backend.reviewer.models.github_meta import PRMetadata
from products.review_hog.backend.reviewer.models.thread_resolution import ThreadResolution
from products.review_hog.backend.reviewer.persistence import load_thread_verdicts, persist_thread_verdict
from products.review_hog.backend.reviewer.skill_loader import REVIEW_HOG_RESOLUTION_SKILL_NAME
from products.review_hog.backend.reviewer.tools.github_threads import FixCommitInspection, ReviewThread, ThreadComment
from products.review_hog.backend.temporal.resolution import (
    FailResolutionInput,
    ResolutionRunResult,
    ResolveThreadsInput,
    _append_run_note,
    _append_task_run,
    _deliver_side_effects,
    _fail_resolution,
    _prepare_run,
    _PreparedRun,
    resolve_threads_activity,
)
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.skills.backend.models.skills import LLMSkill
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


def _inspection(restricted: list[str] | None = None, *, provenance_ok: bool = True) -> FixCommitInspection:
    return FixCommitInspection(restricted_paths=restricted or [], provenance_ok=provenance_ok)


def _mock_installation() -> Mock:
    github = Mock()
    github.get_access_token.return_value = "token"
    github.github_installation_id = "inst-1"
    github.integration.id = 42
    return github


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
            patch(f"{_RESOLUTION}.inspect_fix_commit", return_value=_inspection()),
            patch(f"{_RESOLUTION}._delivery_auth", return_value=("token", None)),
        ):
            _deliver_side_effects(self._input(), str(report.id), verdict, branch="feature", integration_row_id=1)

        assert reply.call_count == 1
        assert resolve.call_count == (1 if expect_resolve else 0)
        stored = load_thread_verdicts(team_id=self.team.id, report_id=str(report.id))["PRRT_1"]
        assert stored.reply_posted is True
        assert stored.resolved is expect_resolve
        # The watermark advances to our own posted reply so it can't re-open triage next run.
        assert stored.latest_comment_id == 555

    def test_fixed_reply_links_the_commit_and_records_it_once(self) -> None:
        report = self._report()
        verdict = _verdict(outcome="fixed", commit_sha="abc123")
        with (
            patch(f"{_RESOLUTION}.reply_to_thread", return_value=(555, None)) as reply,
            patch(f"{_RESOLUTION}.resolve_thread", return_value=True),
            patch(f"{_RESOLUTION}.commit_on_branch", return_value=True),
            patch(f"{_RESOLUTION}.inspect_fix_commit", return_value=_inspection()),
            patch(f"{_RESOLUTION}._delivery_auth", return_value=("token", None)),
        ):
            delivered = _deliver_side_effects(
                self._input(), str(report.id), verdict, branch="feature", integration_row_id=1
            )
            # A redelivery of the already-verified verdict must not duplicate the commit artefact.
            _deliver_side_effects(self._input(), str(report.id), delivered, branch="feature", integration_row_id=1)
        assert "https://github.com/posthog/posthog/commit/abc123" in reply.call_args_list[0].kwargs["body"]
        commits = ReviewReportArtefact.objects.for_team(self.team.id).filter(report_id=report.id, type="commit")
        assert commits.count() == 1
        assert json.loads(commits.get().content)["commit_sha"] == "abc123"

    def test_unverified_commit_withholds_link_and_resolve(self) -> None:
        # The exact failure this guard exists for: a hallucinated or off-branch SHA must not become
        # a public "Fix commit" link, and must not auto-close the thread.
        report = self._report()
        verdict = _verdict(author_is_bot=True, outcome="fixed", commit_sha="deadbee")
        with (
            patch(f"{_RESOLUTION}.reply_to_thread", return_value=(555, None)) as reply,
            patch(f"{_RESOLUTION}.resolve_thread", return_value=True) as resolve,
            patch(f"{_RESOLUTION}.commit_on_branch", return_value=False),
            patch(f"{_RESOLUTION}._delivery_auth", return_value=("token", None)),
        ):
            _deliver_side_effects(self._input(), str(report.id), verdict, branch="feature", integration_row_id=1)

        body = reply.call_args.kwargs["body"]
        assert "Fix commit" not in body
        assert "could not be confirmed as this run's own fix" in body
        assert resolve.call_count == 0
        stored = load_thread_verdicts(team_id=self.team.id, report_id=str(report.id))["PRRT_1"]
        assert stored.commit_verified is False
        assert stored.reply_posted is True
        assert stored.resolved is False
        # An unproven SHA must never enter the commit artefact log (pushed commits only).
        assert (
            not ReviewReportArtefact.objects.for_team(self.team.id).filter(report_id=report.id, type="commit").exists()
        )

    def test_foreign_authored_commit_is_treated_as_unverified(self) -> None:
        # "On the branch" includes every ancestor, so a steered turn could echo someone's old clean
        # commit; a reachable SHA that is not a verified app-bot commit must stay unverified.
        report = self._report()
        verdict = _verdict(author_is_bot=True, outcome="fixed", commit_sha="abc123")
        with (
            patch(f"{_RESOLUTION}.reply_to_thread", return_value=(555, None)) as reply,
            patch(f"{_RESOLUTION}.resolve_thread", return_value=True) as resolve,
            patch(f"{_RESOLUTION}.commit_on_branch", return_value=True),
            patch(f"{_RESOLUTION}.inspect_fix_commit", return_value=_inspection(provenance_ok=False)),
            patch(f"{_RESOLUTION}._delivery_auth", return_value=("token", None)),
        ):
            _deliver_side_effects(self._input(), str(report.id), verdict, branch="feature", integration_row_id=1)

        body = reply.call_args.kwargs["body"]
        assert "Fix commit" not in body
        assert "could not be confirmed as this run's own fix" in body
        assert resolve.call_count == 0
        stored = load_thread_verdicts(team_id=self.team.id, report_id=str(report.id))["PRRT_1"]
        assert stored.commit_verified is False
        assert (
            not ReviewReportArtefact.objects.for_team(self.team.id).filter(report_id=report.id, type="commit").exists()
        )

    def _prepare_unpinned(self) -> object:
        thread = ReviewThread(
            thread_id="PRRT_1",
            path="f.py",
            comments=[ThreadComment(id=1, author_login="greptile", author_is_bot=True, body="b")],
        )
        with (
            patch(f"{_RESOLUTION}._installation_for", return_value=_mock_installation()),
            patch(f"{_RESOLUTION}._fetch_pr_metadata", return_value=_pr_metadata()),
            patch(f"{_RESOLUTION}.fetch_unresolved_threads", return_value=[thread]),
            patch(f"{_RESOLUTION}.add_eyes_reaction"),
        ):
            return _prepare_run(
                ResolveThreadsInput(
                    team_id=self.team.id,
                    user_id=self.user.id,
                    acting_user_id=None,
                    owner="posthog",
                    repo="posthog",
                    pr_number=123,
                )
            )

    def test_unpinned_acting_user_with_unmapped_author_pins_canonical_criteria(self) -> None:
        # The /resolve landmine: with no acting user pinned and an unmapped author, the RUN user's
        # personal selection must not govern someone else's PR — the canonical bar applies.
        sync_canonical_resolution(self.team)
        LLMSkill.objects.create(
            team=self.team,
            name="review-hog-resolution-run-users-own",
            description="d",
            body="x" * 250,
            version=1,
            is_latest=True,
            created_by=self.user,
        )
        ReviewSkillConfig.objects.for_team(self.team.id).create(
            team_id=self.team.id, user_id=self.user.id, skill_name="review-hog-resolution-run-users-own", enabled=True
        )

        prepared = self._prepare_unpinned()

        assert isinstance(prepared, _PreparedRun)
        assert prepared.skill_name == REVIEW_HOG_RESOLUTION_SKILL_NAME

    def test_unpinned_acting_user_maps_the_pr_author(self) -> None:
        sync_canonical_resolution(self.team)
        author = User.objects.create_and_join(self.organization, "author@example.com", None)
        UserSocialAuth.objects.create(user=author, provider="github", uid="gh-octocat", extra_data={"login": "octocat"})
        LLMSkill.objects.create(
            team=self.team,
            name="review-hog-resolution-authors-own",
            description="d",
            body="x" * 250,
            version=1,
            is_latest=True,
            created_by=author,
        )
        ReviewSkillConfig.objects.for_team(self.team.id).create(
            team_id=self.team.id, user_id=author.id, skill_name="review-hog-resolution-authors-own", enabled=True
        )

        prepared = self._prepare_unpinned()

        assert isinstance(prepared, _PreparedRun)
        assert prepared.skill_name == "review-hog-resolution-authors-own"

    def test_restricted_commit_delivers_warning_and_never_resolves(self) -> None:
        # The hard-floor backstop: a real commit touching CI/CODEOWNERS/dependency files must not be
        # presented as settled — no link, no auto-resolve, a human-review warning instead.
        report = self._report()
        verdict = _verdict(author_is_bot=True, outcome="fixed", commit_sha="abc123")
        with (
            patch(f"{_RESOLUTION}.reply_to_thread", return_value=(555, None)) as reply,
            patch(f"{_RESOLUTION}.resolve_thread", return_value=True) as resolve,
            patch(f"{_RESOLUTION}.commit_on_branch", return_value=True),
            patch(
                f"{_RESOLUTION}.inspect_fix_commit", return_value=_inspection(restricted=[".github/workflows/ci.yml"])
            ),
            patch(f"{_RESOLUTION}._delivery_auth", return_value=("token", None)),
        ):
            _deliver_side_effects(self._input(), str(report.id), verdict, branch="feature", integration_row_id=1)

        body = reply.call_args.kwargs["body"]
        assert "Fix commit:" not in body
        assert "protected files" in body
        assert resolve.call_count == 0
        stored = load_thread_verdicts(team_id=self.team.id, report_id=str(report.id))["PRRT_1"]
        assert stored.commit_verified is True
        assert stored.commit_restricted is True
        assert stored.resolved is False
        # Restricted commits are real pushed commits: the restriction gates delivery, not the audit log.
        assert ReviewReportArtefact.objects.for_team(self.team.id).filter(report_id=report.id, type="commit").exists()

    def test_fail_resolution_idles_the_report_and_marks_where_it_stopped(self) -> None:
        # The workflow-level crash cleanup: it must count only delivered threads against the queued
        # work-list, and a crash before anything was queued must not edit (or create) a comment —
        # the create-on-demand path would post a spurious "stopped at 0/0" otherwise.
        report = self._report()
        ReviewReportArtefact.append_resolution_run(
            team_id=self.team.id,
            report_id=str(report.id),
            content=ResolutionRunArtefact(total=3, thread_ids=["PRRT_1", "PRRT_2", "PRRT_3"]),
            attribution=ArtefactAttribution.system(),
        )
        persist_thread_verdict(
            team_id=self.team.id,
            report_id=str(report.id),
            verdict=_verdict(outcome="fixed", reply_posted=True),
        )
        persist_thread_verdict(
            team_id=self.team.id,
            report_id=str(report.id),
            verdict=_verdict(thread_id="PRRT_2", outcome="fixed", reply_posted=False),
        )

        with patch(f"{_RESOLUTION}.update_resolution_status_comment") as status_comment:
            _fail_resolution(FailResolutionInput(team_id=self.team.id, owner="posthog", repo="posthog", pr_number=123))

        assert ReviewReport.objects.for_team(self.team.id).get(id=report.id).status == ReviewReport.Status.IDLE
        assert "stopped at 1/3" in status_comment.call_args.args[2]

        # Crash before prepare queued anything: no run anchor, so no section to replace.
        report.pr_number = 124
        report.status = ReviewReport.Status.ACTIVE
        report.save(update_fields=["pr_number", "status"])
        ReviewReportArtefact.objects.for_team(self.team.id).filter(report_id=report.id).delete()
        with patch(f"{_RESOLUTION}.update_resolution_status_comment") as status_comment:
            _fail_resolution(FailResolutionInput(team_id=self.team.id, owner="posthog", repo="posthog", pr_number=124))
        assert ReviewReport.objects.for_team(self.team.id).get(id=report.id).status == ReviewReport.Status.IDLE
        assert status_comment.call_count == 0

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

    def test_failed_resolve_raises_but_leaves_a_redeliverable_verdict(self) -> None:
        report = self._report()
        verdict = _verdict(author_is_bot=True, outcome="fixed")
        with (
            patch(f"{_RESOLUTION}.reply_to_thread", return_value=(555, None)),
            patch(f"{_RESOLUTION}.resolve_thread", side_effect=RuntimeError("token cannot resolve")),
            patch(f"{_RESOLUTION}.commit_on_branch", return_value=True),
            patch(f"{_RESOLUTION}.inspect_fix_commit", return_value=_inspection()),
            patch(f"{_RESOLUTION}._delivery_auth", return_value=("token", None)),
        ):
            # The failure must propagate so the run counts the thread as undelivered instead of
            # reporting a clean note over a resolve that never happened.
            with pytest.raises(RuntimeError, match="token cannot resolve"):
                _deliver_side_effects(self._input(), str(report.id), verdict, branch="feature", integration_row_id=1)
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
            patch(f"{_RESOLUTION}._installation_for", return_value=_mock_installation()),
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
        # No queued threads means no progress anchor — a total=0 run artefact would render this
        # clean no-op as a crashed run once it aged past the staleness window.
        assert (
            not ReviewReportArtefact.objects.for_team(self.team.id)
            .filter(report_id=report.id, type="resolution_run")
            .exists()
        )

    def _prepare_with(self, threads: list[ReviewThread], eyes: Mock | None = None) -> object:
        eyes = eyes if eyes is not None else Mock()
        with (
            patch(f"{_RESOLUTION}._installation_for", return_value=_mock_installation()),
            patch(f"{_RESOLUTION}._fetch_pr_metadata", return_value=_pr_metadata()),
            patch(f"{_RESOLUTION}.fetch_unresolved_threads", return_value=threads),
            patch(f"{_RESOLUTION}.add_eyes_reaction", eyes),
            patch(
                f"{_RESOLUTION}.load_resolution_skill_for_run",
                return_value=Mock(skill_name="review-hog-resolution-criteria", version=1),
            ),
        ):
            return _prepare_run(self._input())

    def test_prepare_anchors_the_run_and_marks_only_queued_threads(self) -> None:
        # The run's progress anchor must list exactly the queued threads (progress counts verdicts
        # against it, so a settled thread in the list would read as forever-unfinished work), and
        # the 👀 queue marker must skip settled threads for the same reason.
        report = self._report()
        queued = ReviewThread(
            thread_id="PRRT_1",
            path="f.py",
            comments=[ThreadComment(id=1, node_id="PRRC_1", author_login="greptile", author_is_bot=True, body="b")],
        )
        settled = ReviewThread(
            thread_id="PRRT_2",
            path="f.py",
            comments=[ThreadComment(id=100, node_id="PRRC_2", author_login="greptile", author_is_bot=True, body="b")],
        )
        persist_thread_verdict(
            team_id=self.team.id,
            report_id=str(report.id),
            verdict=_verdict("PRRT_2", outcome="wont_fix", reply_posted=True, resolved=True, commit_sha=None),
        )
        eyes = Mock()

        prepared = self._prepare_with([queued, settled], eyes)

        assert isinstance(prepared, _PreparedRun)
        run_artefact = ReviewReportArtefact.objects.for_team(self.team.id).get(
            report_id=report.id, type="resolution_run"
        )
        content = json.loads(run_artefact.content)
        assert content["total"] == 1
        assert content["thread_ids"] == ["PRRT_1"]
        assert content["skipped"] == 1
        assert eyes.call_args_list == [((), {"token": "token", "subject_id": "PRRC_1", "installation_id": "inst-1"})]

    def test_reaction_failure_never_fails_prepare(self) -> None:
        # A GitHub flake on the cosmetic queue marker must not cost the run (or the progress anchor,
        # which is written first).
        report = self._report()
        thread = ReviewThread(
            thread_id="PRRT_1",
            path="f.py",
            comments=[ThreadComment(id=1, node_id="PRRC_1", author_login="greptile", author_is_bot=True, body="b")],
        )

        prepared = self._prepare_with([thread], Mock(side_effect=RuntimeError("github flake")))

        assert isinstance(prepared, _PreparedRun)
        assert (
            ReviewReportArtefact.objects.for_team(self.team.id)
            .filter(report_id=report.id, type="resolution_run")
            .exists()
        )


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
            patch(f"{_RESOLUTION}._installation_for", return_value=_mock_installation()),
            patch(f"{_RESOLUTION}._delivery_auth", return_value=("token", "inst-1")),
            patch(f"{_RESOLUTION}._fetch_pr_metadata", return_value=_pr_metadata()),
            patch(f"{_RESOLUTION}.fetch_unresolved_threads", return_value=threads),
            patch(f"{_RESOLUTION}.add_eyes_reaction"),
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
            for attempt, expected in (
                (1, ReviewReport.Status.ACTIVE),
                (RESOLUTION_MAX_ATTEMPTS, ReviewReport.Status.IDLE),
            ):
                mock_activity.info.return_value.attempt = attempt
                with pytest.raises(RuntimeError, match="sandbox down"):
                    async_to_sync(resolve_threads_activity)(self._input())
                assert self._report_status() == expected

    def test_poison_thread_skips_on_final_attempt_once_turns_have_landed(self) -> None:
        # T1 triages fine, T2's turn dies (final-attempt skip closes the session), T3's fresh
        # session-open dies too. With a completed turn behind it that must degrade to a skip —
        # not fail the run, which would block this PR's resolution forever.
        mock_activity = Mock()
        mock_activity.info.return_value.attempt = RESOLUTION_MAX_ATTEMPTS
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

    def test_undelivered_thread_never_counts_as_settled_in_the_status_comment(self) -> None:
        # A judged thread whose GitHub writes failed has no reply on the PR — the progress line and
        # the closing tally must not claim it as done/declined; it lands in "couldn't handle" instead.
        mock_activity = Mock()
        mock_activity.info.return_value.attempt = 1
        session = Mock()
        session.task_run.task_id = "11111111-1111-1111-1111-111111111111"
        session.task_run.id = "run-1"
        res = ThreadResolution(thread_id="PRRT_A", outcome="wont_fix", reasoning="checked", reply="declined")
        with ExitStack() as stack:
            for p in self._base_patches(mock_activity, [self._thread("PRRT_A")]):
                stack.enter_context(p)
            stack.enter_context(patch(f"{_RESOLUTION}.start_sandbox_session", AsyncMock(return_value=(session, res))))
            stack.enter_context(patch(f"{_RESOLUTION}.end_sandbox_session", AsyncMock()))
            stack.enter_context(patch(f"{_RESOLUTION}.reply_to_thread", side_effect=RuntimeError("token expired")))
            status_comment = stack.enter_context(patch(f"{_RESOLUTION}.update_resolution_status_comment"))

            result = async_to_sync(resolve_threads_activity)(self._input())

        assert result.outcomes == {"wont_fix": 1}
        assert result.delivered_outcomes == {}
        assert result.undelivered == 1
        final_section = status_comment.call_args.args[2]
        assert "couldn't handle 1" in final_section
        assert "declined" not in final_section
