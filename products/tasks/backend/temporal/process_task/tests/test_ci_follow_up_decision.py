import uuid
from datetime import UTC, datetime

import pytest
from unittest.mock import Mock

from products.tasks.backend.temporal.babysit_pr.snapshot import (
    BabysitJournal,
    CommentItem,
    FailingCheck,
    PRSnapshot,
    ReviewThreadItem,
)
from products.tasks.backend.temporal.process_task import workflow as process_task_workflow_module
from products.tasks.backend.temporal.process_task.activities.get_pr_babysit_snapshot import get_pr_babysit_snapshot
from products.tasks.backend.temporal.process_task.activities.get_pr_context import GetPrContextOutput, get_pr_context
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.workflow import (
    CIFollowUpDecision,
    ProcessTaskInput,
    ProcessTaskWorkflow,
    ResumedSandboxState,
)

pytestmark = [pytest.mark.asyncio]


class TestShouldRunCIFollowUpDecision:
    # Direct decision tests for ProcessTaskWorkflow's copy of the CI follow-up
    # gate (task_management has its own copy with an equivalent suite). Guards
    # against re-introducing "nothing to report" wake-ups: a fingerprint change
    # must only fire when the PR state is actionable.
    @pytest.mark.parametrize(
        "ci_status,changes_requested,expected_decision,expected_fingerprint",
        [
            # Actionable changes fire.
            ("failing", False, CIFollowUpDecision.FIRE, "fp-1"),
            ("passing", True, CIFollowUpDecision.FIRE, "fp-1"),
            # Non-actionable changes persist the fingerprint but stay quiet.
            # Pending needs no deferral: the settled state hashes differently
            # (CI status and head SHA are both in the fingerprint), so it still
            # registers as a change on a later tick.
            ("passing", False, CIFollowUpDecision.SKIP, "fp-1"),
            ("none", False, CIFollowUpDecision.SKIP, "fp-1"),
            ("pending", False, CIFollowUpDecision.SKIP, "fp-1"),
        ],
    )
    async def test_fingerprint_change_fires_only_when_actionable(
        self,
        monkeypatch,
        ci_status,
        changes_requested,
        expected_decision,
        expected_fingerprint,
    ):
        wf = ProcessTaskWorkflow()
        wf._context = TaskProcessingContext(
            task_id="task-1",
            run_id="run-1",
            team_id=1,
            team_uuid=str(uuid.uuid4()),
            organization_id=str(uuid.uuid4()),
            github_integration_id=1,
            repository="org/repo",
            distinct_id="user-1",
        )
        wf._pr_fingerprint = "fp-0"
        wf._pr_progress_emitted = True

        async def fake_execute_activity(activity_fn, *args, **kwargs):
            return GetPrContextOutput(
                pr_url="https://github.com/org/repo/pull/1",
                pr_state="open",
                fingerprint="fp-1",
                ci_status=ci_status,
                changes_requested=changes_requested,
            )

        monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", fake_execute_activity)
        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", Mock())

        decision = await wf._should_run_ci_follow_up()

        assert decision is expected_decision
        assert wf._pr_fingerprint == expected_fingerprint

    @pytest.mark.parametrize(
        "prev_threads,new_threads,fingerprint,expected_decision",
        [
            # New review threads are feedback — fire even when the fingerprint
            # hasn't moved.
            (0, 2, "fp-0", CIFollowUpDecision.FIRE),
            # Resolving threads is not feedback.
            (2, 1, "fp-0", CIFollowUpDecision.SKIP),
            # A green change with a stable thread count stays quiet.
            (2, 2, "fp-1", CIFollowUpDecision.SKIP),
            # A green change accompanied by new feedback fires.
            (0, 3, "fp-1", CIFollowUpDecision.FIRE),
        ],
    )
    async def test_new_review_threads_fire_follow_up(
        self,
        monkeypatch,
        prev_threads,
        new_threads,
        fingerprint,
        expected_decision,
    ):
        wf = ProcessTaskWorkflow()
        wf._context = TaskProcessingContext(
            task_id="task-1",
            run_id="run-1",
            team_id=1,
            team_uuid=str(uuid.uuid4()),
            organization_id=str(uuid.uuid4()),
            github_integration_id=1,
            repository="org/repo",
            distinct_id="user-1",
        )
        wf._pr_fingerprint = "fp-0"
        wf._pr_unresolved_threads = prev_threads
        wf._pr_progress_emitted = True

        async def fake_execute_activity(activity_fn, *args, **kwargs):
            return GetPrContextOutput(
                pr_url="https://github.com/org/repo/pull/1",
                pr_state="open",
                fingerprint=fingerprint,
                ci_status="passing",
                unresolved_threads=new_threads,
            )

        monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", fake_execute_activity)
        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", Mock())

        decision = await wf._should_run_ci_follow_up()

        assert decision is expected_decision
        # The count must track last-seen (not max) so post-resolve feedback re-fires.
        assert wf._pr_unresolved_threads == new_threads


BABYSIT_PR_URL = "https://github.com/acme/widgets/pull/7"
BABYSIT_CHECK = FailingCheck(key="CI/backend", details_url="https://ci.example.com/1")
BABYSIT_THREAD = ReviewThreadItem(id="T1", last_comment_id="C1", author="reviewer", body_excerpt="rename this helper")


def _babysit_snapshot(**overrides) -> PRSnapshot:
    defaults: dict = {
        "pr_url": BABYSIT_PR_URL,
        "pr_state": "open",
        "head_sha": "head1",
        "author_login": "posthog-bot",
    }
    defaults.update(overrides)
    return PRSnapshot(**defaults)


def _babysit_workflow(*, pr_babysit_enabled: bool = True, ci_prompt: str | None = None) -> ProcessTaskWorkflow:
    wf = ProcessTaskWorkflow()
    wf._context = TaskProcessingContext(
        task_id="task-1",
        run_id="run-1",
        team_id=1,
        team_uuid=str(uuid.uuid4()),
        organization_id=str(uuid.uuid4()),
        github_integration_id=1,
        repository="org/repo",
        distinct_id="user-1",
        pr_loop_enabled=True,
        pr_babysit_enabled=pr_babysit_enabled,
        ci_prompt=ci_prompt,
    )
    wf._pr_progress_emitted = True
    return wf


def _resumed_state(**overrides) -> ResumedSandboxState:
    defaults: dict = {
        "sandbox_id": "sandbox-1",
        "sandbox_url": "https://sandbox.example.com",
        "connect_token": None,
        "ci_repetitions": 1,
        "pr_fingerprint": None,
        "pr_progress_emitted": True,
        "first_user_message_received": True,
        "is_agent_design_enabled": False,
        "last_active_time": None,
    }
    defaults.update(overrides)
    return ResumedSandboxState(**defaults)


def _patch_snapshot(monkeypatch, snapshot: PRSnapshot | None) -> None:
    async def fake_execute_activity(activity_fn, *args, **kwargs):
        return snapshot

    monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", fake_execute_activity)
    monkeypatch.setattr(process_task_workflow_module.workflow, "logger", Mock())


def _capture_dispatched_messages(monkeypatch) -> list[str]:
    sent: list[str] = []

    async def fake_send(self, message, artifact_ids, *args, **kwargs):
        sent.append(message)
        return None

    monkeypatch.setattr(ProcessTaskWorkflow, "_send_followup_to_sandbox", fake_send)
    monkeypatch.setattr(process_task_workflow_module.workflow, "now", lambda: datetime(2026, 8, 18, tzinfo=UTC))
    return sent


class TestBabysitFollowUpDecision:
    @pytest.mark.parametrize(
        "pr_babysit_enabled,expected_activity",
        [
            (False, get_pr_context),
            (True, get_pr_babysit_snapshot),
        ],
    )
    async def test_gate_routes_to_the_matching_pr_activity(self, monkeypatch, pr_babysit_enabled, expected_activity):
        wf = _babysit_workflow(pr_babysit_enabled=pr_babysit_enabled)
        executed = []

        async def fake_execute_activity(activity_fn, *args, **kwargs):
            executed.append(activity_fn)
            return None

        monkeypatch.setattr(process_task_workflow_module.workflow, "execute_activity", fake_execute_activity)
        monkeypatch.setattr(process_task_workflow_module.workflow, "logger", Mock())

        await wf._should_run_ci_follow_up()

        assert executed == [expected_activity]

    @pytest.mark.parametrize(
        "snapshot,expected_decision",
        [
            (None, CIFollowUpDecision.NO_PR),
            (_babysit_snapshot(pr_state="merged"), CIFollowUpDecision.TERMINAL),
            (_babysit_snapshot(pr_state="closed"), CIFollowUpDecision.TERMINAL),
            (_babysit_snapshot(), CIFollowUpDecision.SKIP),
            (_babysit_snapshot(failing_checks=[BABYSIT_CHECK]), CIFollowUpDecision.FIRE),
        ],
    )
    async def test_snapshot_drives_the_decision(self, monkeypatch, snapshot, expected_decision):
        wf = _babysit_workflow()
        _patch_snapshot(monkeypatch, snapshot)

        assert await wf._should_run_ci_follow_up() is expected_decision

    async def test_dispatched_check_is_silenced_until_a_new_head(self, monkeypatch):
        wf = _babysit_workflow()
        sent = _capture_dispatched_messages(monkeypatch)

        _patch_snapshot(monkeypatch, _babysit_snapshot(failing_checks=[BABYSIT_CHECK]))
        assert await wf._should_run_ci_follow_up() is CIFollowUpDecision.FIRE
        await wf._dispatch_ci_follow_up()

        assert await wf._should_run_ci_follow_up() is CIFollowUpDecision.SKIP

        _patch_snapshot(monkeypatch, _babysit_snapshot(head_sha="head2", failing_checks=[BABYSIT_CHECK]))
        assert await wf._should_run_ci_follow_up() is CIFollowUpDecision.FIRE
        assert len(sent) == 1

    async def test_dispatch_message_carries_the_attention_items_and_extra_instructions(self, monkeypatch):
        wf = _babysit_workflow(ci_prompt="Update the changelog entry too.")
        sent = _capture_dispatched_messages(monkeypatch)
        _patch_snapshot(
            monkeypatch,
            _babysit_snapshot(failing_checks=[BABYSIT_CHECK], unresolved_threads=[BABYSIT_THREAD]),
        )

        assert await wf._should_run_ci_follow_up() is CIFollowUpDecision.FIRE
        await wf._dispatch_ci_follow_up()

        message = sent[0]
        assert BABYSIT_PR_URL in message
        assert "CI/backend" in message
        assert "https://ci.example.com/1" in message
        assert "rename this helper" in message
        assert "Update the changelog entry too." in message

    async def test_journal_survives_continue_as_new(self, monkeypatch):
        wf = _babysit_workflow()
        sent = _capture_dispatched_messages(monkeypatch)
        _patch_snapshot(
            monkeypatch,
            _babysit_snapshot(
                has_conflict=True,
                failing_checks=[BABYSIT_CHECK],
                unresolved_threads=[BABYSIT_THREAD],
                comments=[CommentItem(id="M1", author="coderabbit")],
            ),
        )
        assert await wf._should_run_ci_follow_up() is CIFollowUpDecision.FIRE
        await wf._dispatch_ci_follow_up()
        wf._chain_started_at = datetime(2026, 8, 18, tzinfo=UTC)

        resumed = wf._build_resumed_input(ProcessTaskInput(run_id="run-1"), "sandbox-1").resumed_sandbox
        assert resumed is not None
        continuation = _babysit_workflow()
        continuation._restore_resumed_state(resumed)

        assert await continuation._should_run_ci_follow_up() is CIFollowUpDecision.SKIP
        assert len(sent) == 1

    async def test_resumed_payload_without_a_babysit_journal_still_fires(self, monkeypatch):
        wf = _babysit_workflow()
        wf._restore_resumed_state(_resumed_state())
        _patch_snapshot(
            monkeypatch, _babysit_snapshot(failing_checks=[BABYSIT_CHECK], unresolved_threads=[BABYSIT_THREAD])
        )

        assert await wf._should_run_ci_follow_up() is CIFollowUpDecision.FIRE

    async def test_restored_journal_silences_an_already_dispatched_item(self, monkeypatch):
        wf = _babysit_workflow()
        wf._restore_resumed_state(
            _resumed_state(
                babysit_journal=BabysitJournal(
                    threads={BABYSIT_THREAD.id: BABYSIT_THREAD.last_comment_id},
                    head_sha="head1",
                    head_keys=[BABYSIT_CHECK.key],
                )
            )
        )
        _patch_snapshot(
            monkeypatch, _babysit_snapshot(failing_checks=[BABYSIT_CHECK], unresolved_threads=[BABYSIT_THREAD])
        )

        assert await wf._should_run_ci_follow_up() is CIFollowUpDecision.SKIP
