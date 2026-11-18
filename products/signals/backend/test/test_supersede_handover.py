from contextlib import nullcontext
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.db import transaction
from django.utils import timezone

from asgiref.sync import async_to_sync
from parameterized import parameterized

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import (
    ImplementationDecision,
    ImplementationDispatch,
    ImplementationHandover,
    ImplementationReplacement,
)
from products.signals.backend.auto_start import (
    ImplementationReportContent,
    ReportChangedDuringAutostart,
    _create_implementation_task_if_absent,
    _resolve_supersede,
    maybe_autostart_implementation_task,
)
from products.signals.backend.implementation_pr import fetch_implementation_prs_for_reports
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportAssignment
from products.signals.backend.report_assignments import create_claim, release_claim, update_assignments_for_pull_request
from products.signals.backend.report_claims import ReportClaim, get_active_claim
from products.signals.backend.report_generation.research import ActionabilityAssessment, ActionabilityChoice
from products.signals.backend.scout_harness.tools.report import record_implementation_decision
from products.signals.backend.supersession import (
    MAX_HANDOVER_ATTEMPTS,
    TargetVerificationUnavailable,
    append_handover,
    automated_targets,
    latest_handover,
    pending_replacement,
    reconcile_replacement,
    research_implementation_context,
)
from products.signals.backend.task_run_artefacts import record_implementation_task
from products.tasks.backend.models import Task, TaskRun

OLD_PR = "https://github.com/example/repo/pull/1"
KEPT_PR = "https://github.com/example/repo/pull/2"
NEW_PR = "https://github.com/example/repo/pull/3"


class TestSupersedeHandover(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.report = SignalReport.objects.create(
            team=self.team,
            status="ready",
            title="Fix checkout",
            summary="Updated fix",
            run_count=2,
            implemented_at_run_count=1,
            last_run_at=timezone.now(),
        )
        self.task = Task.objects.create(
            team=self.team,
            signal_report=self.report,
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
            title="Original implementation",
            repository="example/repo",
            internal=True,
        )
        self.implementation_run = TaskRun.objects.create(
            team=self.team,
            task=self.task,
            status="completed",
            environment="cloud",
            state={"ai_stage": "implementation", "self_driving_head_branch": "automated-original"},
            output={"pr_urls": [OLD_PR, KEPT_PR]},
        )
        with transaction.atomic():
            record_implementation_task(
                team_id=self.team.id,
                report_id=str(self.report.id),
                task_id=str(self.task.id),
                run_id=str(self.implementation_run.id),
                automation_branch="automated-original",
            )
        self.prs: dict[int, dict[str, str | bool | int]] = {
            n: {
                "success": True,
                "state": "open",
                "merged": False,
                "head_sha": f"sha-{n}",
                "head_branch": "automated-original" if n != 3 else "automated-replacement",
                "head_repository": "example/repo",
            }
            for n in (1, 2, 3)
        }
        self.github = MagicMock()
        self.github.get_pull_request.side_effect = lambda repository, number: self.prs[number]
        self.github.has_pull_request_comment.return_value = False
        self.github.comment_on_pull_request.return_value = {"success": True}

        def close(repository, number):
            self.prs[number] = {**self.prs[number], "state": "closed"}
            return {"success": True, "state": "closed"}

        self.github.close_pull_request.side_effect = close
        patcher = patch(
            "products.signals.backend.supersession.GitHubIntegration.first_for_team_repository",
            return_value=self.github,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def current_claim(self) -> ReportClaim:
        claim = get_active_claim(team_id=self.team.id, report_id=self.report.id)
        assert claim is not None
        return claim

    def handover(self, replacement: SignalReportArtefact) -> ImplementationHandover:
        handover = latest_handover(replacement)
        assert handover is not None
        return handover

    def decision(self) -> ImplementationDecision:
        context = research_implementation_context(self.team.id, str(self.report.id))
        decision = ImplementationDecision(
            supersede=True,
            reason="The first fix targets the wrong layer.",
            targets=[target for target in context.candidates if target.pr_url == OLD_PR],
            research_run_count=context.run_count,
            research_started_at=context.started_at,
            content_revision_count=context.content_revision_count,
        )
        SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=str(self.report.id),
            content=decision,
            attribution=ArtefactAttribution.system(),
        )
        return decision

    def start_replacement(
        self, decision: ImplementationDecision | None = None, dispatch: ImplementationDispatch | None = None
    ) -> SignalReportArtefact:
        decision = decision or self.decision()
        supersede = _resolve_supersede(self.report, decision)
        assert supersede.allowed

        def create(**kwargs):
            task = Task.objects.create(
                team=self.team,
                signal_report=self.report,
                origin_product=Task.OriginProduct.SIGNAL_REPORT,
                title="Replacement",
                repository="example/repo",
                internal=True,
            )
            run = TaskRun.objects.create(
                team=self.team,
                task=task,
                status="in_progress",
                environment="cloud",
                state={"ai_stage": "implementation", "self_driving_head_branch": kwargs["self_driving_head_branch"]},
                output={},
            )
            return SimpleNamespace(task_id=task.id, latest_run=SimpleNamespace(id=run.id))

        with patch("products.signals.backend.auto_start.tasks_facade.create_and_run_task", side_effect=create):
            outcomes = [
                _create_implementation_task_if_absent(
                    team_id=self.team.id,
                    report_id=str(self.report.id),
                    title="Replacement",
                    description="Fix the changed layer",
                    expected_content=ImplementationReportContent.from_report(self.report),
                    user_id=self.user.id,
                    repository="example/repo",
                    base_branch=None,
                    supersede=supersede,
                    dispatch=dispatch,
                )
                for _ in range(2)
            ]
            assert outcomes == [True, False]
        return SignalReportArtefact.objects.get(report=self.report, type="implementation_replacement")

    @parameterized.expand([("expired",), ("replaced",), ("current",)])
    def test_dispatch_lease_fences_task_creation(self, lease: str) -> None:
        decision = self.decision()
        row = SignalReportArtefact.objects.get(report=self.report, type="implementation_decision")
        reservation = ImplementationDispatch(
            decision_id=row.id,
            status="processing",
            worker_token=uuid4(),
            lease_until=timezone.now() + timedelta(seconds=300),
        )
        stored = reservation.model_copy()
        if lease == "expired":
            stored.lease_until = timezone.now() - timedelta(seconds=1)
        elif lease == "replaced":
            stored.worker_token = uuid4()
        SignalReportArtefact.append_status(
            team_id=self.team.id,
            report_id=str(self.report.id),
            content=stored,
            attribution=ArtefactAttribution.system(),
        )
        if lease == "current":
            replacement = self.start_replacement(decision, reservation)
            assert ImplementationReplacement.model_validate_json(replacement.content).decision_id == row.id
        else:
            with self.assertRaises(ReportChangedDuringAutostart):
                self.start_replacement(decision, reservation)
            assert not SignalReportArtefact.objects.filter(
                report=self.report, type="implementation_replacement"
            ).exists()
        self.github.close_pull_request.assert_not_called()

    def complete(self, replacement: SignalReportArtefact) -> TaskRun:
        content = ImplementationReplacement.model_validate_json(replacement.content)
        run = TaskRun.objects.get(id=content.run_id)
        self.prs[3]["head_branch"] = run.state["self_driving_head_branch"]
        run.status = "completed"
        run.output = {"pr_url": NEW_PR, "pr_state": "open"}
        run.save(update_fields=["status", "output"])
        return run

    @parameterized.expand([("unchanged", False), ("revised_again", True)])
    def test_scout_replacement_is_bound_to_its_content_revision(self, _name: str, revised_again: bool) -> None:
        self.report.run_count = 0
        self.report.implemented_at_run_count = 0
        self.report.last_run_at = None
        self.report.save()
        context = research_implementation_context(self.team.id, str(self.report.id))
        self.report.content_revision_count = 1
        self.report.save(update_fields=["content_revision_count"])
        record_implementation_decision(
            team_id=self.team.id,
            report_id=str(self.report.id),
            supersede=True,
            updated_fields=["summary"],
            attribution=ArtefactAttribution.system(),
            implementation_context=context,
        )
        row = SignalReportArtefact.objects.get(report=self.report, type="implementation_decision")
        decision = ImplementationDecision.model_validate_json(row.content)
        assert {target.pr_url for target in decision.targets} == {OLD_PR, KEPT_PR}
        replacement = self.start_replacement(decision)
        self.report.refresh_from_db()
        assert self.report.implemented_at_revision_count == 1
        self.complete(replacement)
        if revised_again:
            self.report.content_revision_count = 2
            self.report.save(update_fields=["content_revision_count"])
        assert not reconcile_replacement(self.team.id, str(replacement.id))
        assert self.github.close_pull_request.call_count == (0 if revised_again else 2)
        assert self.handover(replacement).status == ("needs_attention" if revised_again else "completed")

    def test_selective_handover_transfers_claim_and_is_idempotent(self) -> None:
        replacement = self.start_replacement()
        assert self.current_claim().actor_task_id == replacement.task_id
        assert not reconcile_replacement(self.team.id, str(replacement.id))
        self.github.close_pull_request.assert_not_called()
        self.complete(replacement)
        assert not reconcile_replacement(self.team.id, str(replacement.id))
        assert not reconcile_replacement(self.team.id, str(replacement.id))
        self.github.close_pull_request.assert_called_once_with("example/repo", 1)
        assert self.prs[2]["state"] == "open"
        assert self.handover(replacement).status == "completed"

    @parameterized.expand([("interactive", "cloud", "interactive"), ("local", "local", "background")])
    def test_non_automated_execution_modes_are_ineligible(self, name: str, environment: str, mode: str) -> None:
        self.implementation_run.environment = environment
        self.implementation_run.state = {**self.implementation_run.state, "mode": mode}
        self.implementation_run.save(update_fields=["environment", "state"])
        assert not automated_targets(self.team.id, str(self.report.id))

    def test_manual_background_run_cannot_inherit_automation_receipt(self) -> None:
        self.implementation_run.output = {}
        self.implementation_run.save(update_fields=["output"])
        TaskRun.objects.create(
            team=self.team,
            task=self.task,
            status="completed",
            environment="cloud",
            state=self.implementation_run.state,
            output={"pr_url": OLD_PR},
        )
        assert not automated_targets(self.team.id, str(self.report.id))

    def test_missing_receipt_and_cross_team_are_ineligible(self) -> None:
        assert not automated_targets(self.team.id + 1, str(self.report.id))
        SignalReportArtefact.objects.filter(report=self.report, type="task_run").delete()
        assert not automated_targets(self.team.id, str(self.report.id))

    def test_active_user_continuation_blocks_the_entire_task(self) -> None:
        TaskRun.objects.create(
            team=self.team, task=self.task, status="in_progress", environment="cloud", state={"mode": "interactive"}
        )
        assert not automated_targets(self.team.id, str(self.report.id))

    def test_completed_manual_continuation_also_blocks_the_original_run(self) -> None:
        TaskRun.objects.create(
            team=self.team,
            task=self.task,
            status="completed",
            environment="cloud",
            state=self.implementation_run.state,
            output={"pr_url": OLD_PR},
        )
        assert not automated_targets(self.team.id, str(self.report.id))

    def test_wall_clock_timeout_after_verified_pr_allows_replacement(self) -> None:
        self.implementation_run.status = "failed"
        self.implementation_run.state = {
            **self.implementation_run.state,
            "timed_out_wall_clock": True,
            "verified_pr_urls": [OLD_PR],
        }
        self.implementation_run.save(update_fields=["status", "state"])

        assert {target.pr_url for target in automated_targets(self.team.id, str(self.report.id))} == {OLD_PR}
        assert _resolve_supersede(self.report, self.decision()).allowed

    @parameterized.expand(
        [
            ("other_failure", "failed", False, [OLD_PR]),
            ("unverified", "failed", True, []),
            ("cancelled", "cancelled", True, [OLD_PR]),
        ]
    )
    def test_failed_run_without_verified_wall_clock_timeout_is_ineligible(
        self, _name: str, status: str, timed_out: bool, verified_urls: list[str]
    ) -> None:
        self.implementation_run.status = status
        self.implementation_run.state = {
            **self.implementation_run.state,
            "timed_out_wall_clock": timed_out,
            "verified_pr_urls": verified_urls,
        }
        self.implementation_run.save(update_fields=["status", "state"])

        assert not automated_targets(self.team.id, str(self.report.id))

    def test_fork_and_changed_head_do_not_authorize_replacement(self) -> None:
        decision = self.decision()
        self.prs[1]["head_sha"] = "human-edit"
        assert not _resolve_supersede(self.report, decision).allowed
        self.prs[1]["head_repository"] = "other/repo"
        assert OLD_PR not in {
            target.pr_url for target in research_implementation_context(self.team.id, str(self.report.id)).candidates
        }

    def test_unreachable_github_does_not_read_as_an_ineligible_target(self) -> None:
        decision = self.decision()
        self.prs[1] = {"success": False, "status_code": 502}
        with self.assertRaises(TargetVerificationUnavailable):
            _resolve_supersede(self.report, decision)

    def test_human_claim_blocks_replacement(self) -> None:
        decision = self.decision()
        with transaction.atomic():
            claim = get_active_claim(team_id=self.team.id, report_id=self.report.id)
            assert claim is not None
            release_claim(claim, ArtefactAttribution.system())
            create_claim(self.report, ArtefactAttribution.from_user(self.user.id))
        assert not _resolve_supersede(self.report, decision).allowed

    @parameterized.expand([("new_pass",), ("dismissed",)])
    def test_rechecks_generation_and_status_after_resolving(self, change: str) -> None:
        supersede = _resolve_supersede(self.report, self.decision())
        assert supersede.allowed
        SignalReport.objects.filter(id=self.report.id).update(
            **({"run_count": 3} if change == "new_pass" else {"status": "suppressed"})
        )
        with (
            patch("products.signals.backend.auto_start.tasks_facade.create_and_run_task") as create,
            self.assertRaises(ReportChangedDuringAutostart) if change == "new_pass" else nullcontext(),
        ):
            assert not _create_implementation_task_if_absent(
                team_id=self.team.id,
                report_id=str(self.report.id),
                title="t",
                description="d",
                expected_content=ImplementationReportContent.from_report(self.report),
                user_id=self.user.id,
                repository="example/repo",
                base_branch=None,
                supersede=supersede,
            )
        create.assert_not_called()

    def test_closing_predecessor_keeps_pending_report_active(self) -> None:
        replacement = self.start_replacement()
        for number in (1, 2):
            update_assignments_for_pull_request(
                team_ids=[self.team.id], repository="example/repo", pr_number=number, pr_state="closed"
            )
        self.report.refresh_from_db()
        assert self.report.status == "ready"
        pending = pending_replacement(self.team.id, str(self.report.id))
        assert pending is not None and pending.id == replacement.id

    @parameterized.expand([("failed",), ("cancelled",)])
    def test_unsuccessful_replacement_releases_only_its_claim(self, status: str) -> None:
        replacement = self.start_replacement()
        content = ImplementationReplacement.model_validate_json(replacement.content)
        TaskRun.objects.filter(id=content.run_id).update(status=status)
        assert not reconcile_replacement(self.team.id, str(replacement.id))
        assert pending_replacement(self.team.id, str(self.report.id)) is None
        assert get_active_claim(team_id=self.team.id, report_id=self.report.id) is None
        self.github.close_pull_request.assert_not_called()

    def test_closed_replacement_does_not_close_predecessors(self) -> None:
        replacement = self.start_replacement()
        self.complete(replacement)
        self.prs[3]["state"] = "closed"
        assert not reconcile_replacement(self.team.id, str(replacement.id))
        assert self.handover(replacement).status == "needs_attention"
        self.github.close_pull_request.assert_not_called()

    @parameterized.expand([("branch", "head_branch", "unrelated"), ("fork", "head_repository", "other/repo")])
    def test_unrelated_replacement_output_cannot_authorize_closure(self, name: str, field: str, value: str) -> None:
        replacement = self.start_replacement()
        self.complete(replacement)
        self.prs[3][field] = value
        assert not reconcile_replacement(self.team.id, str(replacement.id))
        assert self.handover(replacement).status == "needs_attention"
        self.github.close_pull_request.assert_not_called()

    def test_human_push_during_comment_does_not_close_predecessor(self) -> None:
        replacement = self.start_replacement()
        self.complete(replacement)

        def comment(repository, number, body):
            self.prs[number]["head_sha"] = "human-edit"
            return {"success": True}

        self.github.comment_on_pull_request.side_effect = comment
        assert reconcile_replacement(self.team.id, str(replacement.id))
        assert not reconcile_replacement(self.team.id, str(replacement.id))
        assert self.handover(replacement).results[OLD_PR] == "skipped"
        self.github.close_pull_request.assert_not_called()

    def test_changed_predecessor_is_left_open(self) -> None:
        replacement = self.start_replacement()
        self.complete(replacement)
        self.prs[1]["head_sha"] = "human-edit"
        assert not reconcile_replacement(self.team.id, str(replacement.id))
        assert self.handover(replacement).results[OLD_PR] == "skipped"
        self.github.close_pull_request.assert_not_called()

    def test_predecessor_shared_with_another_report_is_recorded_as_skipped(self) -> None:
        replacement = self.start_replacement()
        self.complete(replacement)
        other = SignalReport.objects.create(team=self.team, status="ready", title="Other", summary="Other work")
        SignalReportAssignment.objects.create(
            team_id=self.team.id,
            report_id=other.id,
            pr_url=OLD_PR,
            repository="example/repo",
            pr_number=1,
            pr_state="open",
        )
        assert not reconcile_replacement(self.team.id, str(replacement.id))
        assert self.handover(replacement).results[OLD_PR] == "skipped"
        assert self.handover(replacement).status == "needs_attention"
        self.github.close_pull_request.assert_not_called()

    def test_transient_failure_retries_without_duplicate_close(self) -> None:
        replacement = self.start_replacement()
        self.complete(replacement)
        self.github.close_pull_request.side_effect = None
        self.github.close_pull_request.return_value = {"success": False}
        assert reconcile_replacement(self.team.id, str(replacement.id))
        assert self.handover(replacement).status == "processing"
        self.github.close_pull_request.return_value = {"success": True}
        assert not reconcile_replacement(self.team.id, str(replacement.id))
        assert self.handover(replacement).status == "completed"

    def test_replacement_links_survive_an_attempt_that_ends_early(self) -> None:
        replacement = self.start_replacement()
        self.complete(replacement)
        self.github.close_pull_request.side_effect = None
        self.github.close_pull_request.return_value = {"success": False}
        assert reconcile_replacement(self.team.id, str(replacement.id))
        assert self.handover(replacement).replacement_pr_urls == [NEW_PR]
        SignalReport.objects.filter(id=self.report.id).update(run_count=3)
        assert not reconcile_replacement(self.team.id, str(replacement.id))
        assert self.handover(replacement).status == "needs_attention"
        assert self.handover(replacement).replacement_pr_urls == [NEW_PR]

    def test_lost_close_response_recovers_from_github_state(self) -> None:
        replacement = self.start_replacement()
        self.complete(replacement)

        def close_then_timeout(repository, number):
            self.prs[number]["state"] = "closed"
            raise TimeoutError("Response lost after GitHub accepted the close")

        self.github.close_pull_request.side_effect = close_then_timeout
        assert reconcile_replacement(self.team.id, str(replacement.id))
        assert not reconcile_replacement(self.team.id, str(replacement.id))
        assert self.handover(replacement).results[OLD_PR] == "already_closed"
        assert self.handover(replacement).status == "completed"
        prs = fetch_implementation_prs_for_reports([str(self.report.id)], team_id=self.team.id)[str(self.report.id)]
        assert next(pr for pr in prs if pr.url == OLD_PR).state == "closed"
        self.github.close_pull_request.assert_called_once_with("example/repo", 1)

    def test_missing_output_exhausts_retries_and_releases_the_claim(self) -> None:
        replacement = self.start_replacement()
        content = ImplementationReplacement.model_validate_json(replacement.content)
        TaskRun.objects.filter(id=content.run_id).update(status="completed", output={})
        for attempt in range(MAX_HANDOVER_ATTEMPTS):
            assert reconcile_replacement(self.team.id, str(replacement.id)) == (attempt < MAX_HANDOVER_ATTEMPTS - 1)
        assert self.handover(replacement).status == "failed"
        assert pending_replacement(self.team.id, str(self.report.id)) is None
        assert get_active_claim(team_id=self.team.id, report_id=self.report.id) is None
        self.github.close_pull_request.assert_not_called()

    def test_only_the_implementation_run_wakes_the_handover(self) -> None:
        replacement = self.start_replacement()
        content = ImplementationReplacement.model_validate_json(replacement.content)
        run = TaskRun.objects.get(id=content.run_id)
        second = SignalReportArtefact.add_log(
            team_id=self.team.id,
            report_id=str(self.report.id),
            content=content,
            attribution=ArtefactAttribution.from_task(str(replacement.task_id)),
        )
        with patch("products.signals.backend.tasks.reconcile_implementation_replacement.delay") as enqueue:
            with self.captureOnCommitCallbacks(execute=True):
                run.status = "completed"
                run.save(update_fields=["status"])
            assert {call.args[1] for call in enqueue.call_args_list} == {str(replacement.id), str(second.id)}
            enqueue.reset_mock()
            unrelated = TaskRun.objects.create(
                team=self.team,
                task_id=run.task_id,
                status="in_progress",
                environment="cloud",
                state={},
                output={},
            )
            with self.captureOnCommitCallbacks(execute=True):
                unrelated.status = "completed"
                unrelated.save(update_fields=["status"])
            assert not enqueue.called

    def test_worker_lease_blocks_duplicates_then_recovers_after_expiry(self) -> None:
        replacement = self.start_replacement()
        self.complete(replacement)
        progress = ImplementationHandover(
            replacement_id=replacement.id,
            status="processing",
            attempt=1,
            worker_token=uuid4(),
            lease_until=timezone.now() + timedelta(minutes=5),
        )
        append_handover(replacement, progress)
        assert reconcile_replacement(self.team.id, str(replacement.id))
        self.github.close_pull_request.assert_not_called()
        progress.lease_until = timezone.now() - timedelta(seconds=1)
        append_handover(replacement, progress)
        with patch("products.signals.backend.tasks.reconcile_implementation_replacement.apply_async") as enqueue:
            with self.captureOnCommitCallbacks(execute=True):
                assert not reconcile_replacement(self.team.id, str(replacement.id))
            assert any(call.kwargs.get("countdown") == 301 for call in enqueue.call_args_list)
        assert self.handover(replacement).status == "completed"
        self.github.close_pull_request.assert_called_once_with("example/repo", 1)

    def test_human_takeover_during_verification_preserves_claim_and_predecessors(self) -> None:
        replacement = self.start_replacement()
        self.complete(replacement)
        original = self.github.get_pull_request.side_effect

        def read(repository, number):
            if number == 3:
                with transaction.atomic():
                    claim = self.current_claim()
                    if claim.actor_kind == "task":
                        release_claim(claim, ArtefactAttribution.system())
                        create_claim(self.report, ArtefactAttribution.from_user(self.user.id))
            return original(repository, number)

        self.github.get_pull_request.side_effect = read
        assert not reconcile_replacement(self.team.id, str(replacement.id))
        assert self.handover(replacement).status == "cancelled"
        assert self.current_claim().actor_user_id == self.user.id
        self.github.close_pull_request.assert_not_called()

    def test_external_work_already_addressed_blocks_supersede(self) -> None:
        decision = self.decision()
        with patch("products.signals.backend.auto_start.tasks_facade.create_and_run_task") as create:
            async_to_sync(maybe_autostart_implementation_task)(
                team_id=self.team.id,
                report_id=str(self.report.id),
                repository="example/repo",
                title="t",
                summary="s",
                actionability=ActionabilityAssessment(
                    explanation="Another PR fixes it",
                    actionability=ActionabilityChoice.IMMEDIATELY_ACTIONABLE,
                    already_addressed=True,
                ),
                reviewers_content=[],
                priority=None,
                implementation_decision=decision,
            )
        create.assert_not_called()
