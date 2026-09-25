from __future__ import annotations

import json
import asyncio
from collections.abc import Callable
from typing import Literal
from uuid import UUID, uuid4

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, patch

from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from asgiref.sync import async_to_sync
from parameterized import parameterized
from pydantic import BaseModel
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

from posthog.models import Team, User
from posthog.models.scoping import team_scope
from posthog.storage import object_storage

from products.signals.backend.models import SignalScoutConfig
from products.signals.backend.scout_harness.trial_evaluation import (
    MAX_SOURCE_CHARS,
    MAX_TRACE_BYTES,
    TrialEvaluationError,
    assert_evaluation_access,
    finish_trial_evaluation,
    prepare_trial_evaluation,
    read_trial_evaluation,
    read_trial_evaluation_report,
    run_evaluation_run,
)
from products.signals.backend.scout_harness.trial_evaluation_types import (
    TrialEvaluationRequest,
    TrialEvaluationVariant,
    TrialRunJudgment,
)
from products.signals.backend.scout_harness.trial_launch import ScoutTrialLaunchError, TrialContext, TrialLaunch
from products.signals.backend.scout_harness.trial_result import TrialWorkflowStatus, export_trial_result
from products.signals.backend.scout_harness.trial_state import ScoutTrialStore
from products.signals.backend.temporal.agentic.scout_trial_evaluation import (
    RunScoutTrialEvaluationWorkflow,
    TrialEvaluationInput,
    TrialEvaluationRunInput,
    finish_scout_trial_evaluation_activity,
    load_scout_trial_evaluation_activity,
)
from products.signals.backend.test.test_scout_harness_api import _make_run
from products.skills.backend.models.skills import LLMSkill

MODULE = "products.signals.backend.scout_harness.trial_evaluation"
JUDGE_MODULE = "products.signals.backend.scout_harness.trial_judge"
WORKFLOW_MODULE = "products.signals.backend.temporal.agentic.scout_trial_evaluation"


@override_settings(SCOUT_LIVE_TRIALS_ENABLED=True, SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE=True)
class TestScoutTrialEvaluationValidation(SimpleTestCase):
    @parameterized.expand(["duplicate_variant", "duplicate_launch", "missing_baseline", "too_many_runs"])
    def test_rejects_ambiguous_groups_before_loading_evidence(self, invalid: str) -> None:
        first = TrialEvaluationVariant(id=uuid4(), label="Baseline", launch_ids=[uuid4()])
        second = TrialEvaluationVariant(id=uuid4(), label="Candidate", launch_ids=[uuid4()])
        baseline = first.id
        if invalid == "duplicate_variant":
            second = second.model_copy(update={"id": first.id})
        elif invalid == "duplicate_launch":
            second = second.model_copy(update={"launch_ids": first.launch_ids})
        elif invalid == "missing_baseline":
            baseline = uuid4()
        else:
            first = first.model_copy(update={"launch_ids": [uuid4() for _ in range(20)]})
        request = TrialEvaluationRequest(
            evaluation_id=uuid4(), baseline_variant_id=baseline, variants=[first, second], rubric_source="mock"
        )
        with self.assertRaises(TrialEvaluationError):
            prepare_trial_evaluation(config=SignalScoutConfig(team_id=2), user=User(id=17), request=request)

    def test_malformed_snapshot_error_does_not_expose_source_text(self) -> None:
        with patch(f"{MODULE}.object_storage.read", return_value=json.dumps({"team_id": "private fixture value"})):
            with self.assertRaisesMessage(TrialEvaluationError, "The saved evaluation document is invalid.") as error:
                read_trial_evaluation(2, uuid4())
        assert "private fixture value" not in str(error.exception)


@override_settings(SCOUT_LIVE_TRIALS_ENABLED=True, SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE=True)
class TestScoutTrialEvaluation(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        if self.team.id != 2:
            self.team = Team.objects.create(id=2, organization=self.organization, name="Internal example")
        self.enterContext(team_scope(self.team.id, canonical=True))
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.skill = LLMSkill.objects.create(
            team=self.team,
            name="signals-scout-example",
            version=1,
            body="Inspect the synthetic checkout result.",
            allowed_tools=["emit_report"],
        )
        self.config = SignalScoutConfig.objects.create(team=self.team, skill_name=self.skill.name, enabled=False)
        self.context = TrialContext(
            id=uuid4(),
            team_id=self.team.id,
            config_id=self.config.id,
            user_id=self.user.id,
            created_at=timezone.now(),
            skill_name=self.skill.name,
            skill_version=1,
            skill_body=self.skill.body,
            skill_origin="custom",
            allowed_tools=["emit_report"],
            capabilities={},
            runtime_adapter="codex",
            model="gpt-5.5",
            reasoning_effort="medium",
            note="Use only the example fixture.",
        )
        self.launch = TrialLaunch(
            id=uuid4(),
            team_id=self.team.id,
            config_id=self.config.id,
            user_id=self.user.id,
            context_id=self.context.id,
            created_at=timezone.now(),
            skill_name=self.skill.name,
            skill_version=1,
            skill_body=self.skill.body,
            runtime_adapter="codex",
            model="gpt-5.5",
            reasoning_effort="medium",
            note=self.context.note,
            request_hash="synthetic-launch",
        )
        self.documents: dict[str, str] = {}
        self._save("contexts", self.context.id, self.context)
        self._save("launches", self.launch.id, self.launch)
        self.enterContext(
            patch.object(object_storage, "read", side_effect=lambda key, **kwargs: self.documents.get(key))
        )
        self.enterContext(patch.object(object_storage, "write", side_effect=self._write))
        self.enterContext(patch(f"{MODULE}.get_task_run_log_urls", return_value=None))
        marker = {"version": 1, "context_id": str(self.context.id), "launch_id": str(self.launch.id)}
        self.scout_run = _make_run(
            self.team,
            scout_config=self.config,
            skill_name=self.skill.name,
            task_run_status="completed",
            summary="The synthetic checkout total is correct.",
            metadata={"scout_trial": marker},
        )
        task = self.scout_run.task_run.task
        task.created_by = self.user
        task.origin_product = "signals_scout"
        task.origin_key = f"scout-trial:{self.launch.id}"
        task.save(update_fields=["created_by", "origin_product", "origin_key"])
        self.scout_run.task_run.state = {
            "scout_trial": marker,
            "runtime_adapter": "codex",
            "model": "gpt-5.5",
            "reasoning_effort": "medium",
            "service_tier": None,
            "token_usage": {"input_tokens": 120, "output_tokens": 30},
        }
        self.scout_run.task_run.save(update_fields=["state"])
        variant = TrialEvaluationVariant(id=uuid4(), label="Baseline", launch_ids=[self.launch.id])
        self.request = TrialEvaluationRequest(
            evaluation_id=uuid4(), baseline_variant_id=variant.id, variants=[variant], rubric_source="mock"
        )

    def _save(self, kind: str, identifier: UUID, document: BaseModel) -> None:
        self.documents[f"signals/scout-trials/{self.team.id}/{kind}/{identifier}.json"] = document.model_dump_json()

    def _write(self, key: str, content: str, **kwargs: object) -> None:
        if key in self.documents:
            raise object_storage.ObjectStorageError("Object already exists")
        self.documents[key] = content

    def test_snapshot_is_frozen_and_reused_only_for_the_same_request(self) -> None:
        snapshot = prepare_trial_evaluation(config=self.config, user=self.user, request=self.request)
        self.scout_run.summary = "A later edit must not change the evidence."
        self.scout_run.save(update_fields=["summary"])
        self.skill.body = "The current skill changed after capture."
        self.skill.save(update_fields=["body"])
        repeat = prepare_trial_evaluation(config=self.config, user=self.user, request=self.request)
        assert repeat == snapshot
        assert (
            next(source.text for source in snapshot.runs[0].sources if source.kind == "summary")
            == "The synthetic checkout total is correct."
        )
        assert snapshot.runs[0].input_tokens == 120
        assert snapshot.criteria
        changed = self.request.model_copy(
            update={"variants": [self.request.variants[0].model_copy(update={"label": "Changed"})]}
        )
        with self.assertRaisesMessage(TrialEvaluationError, "different request"):
            prepare_trial_evaluation(config=self.config, user=self.user, request=changed)

    def test_saved_report_remains_readable_when_launches_are_disabled(self) -> None:
        snapshot = prepare_trial_evaluation(config=self.config, user=self.user, request=self.request)
        report = finish_trial_evaluation(self.team.id, snapshot.evaluation_id)
        with override_settings(SCOUT_LIVE_TRIALS_ENABLED=False, SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE=False):
            assert_evaluation_access(snapshot, config=self.config, user=self.user)
            assert read_trial_evaluation_report(snapshot) == report
            with self.assertRaises(ScoutTrialLaunchError):
                prepare_trial_evaluation(config=self.config, user=self.user, request=self.request)

    def test_invalidation_after_export_excludes_the_trial(self) -> None:
        export_trial_result(self.scout_run)
        ScoutTrialStore(self.scout_run).invalidate("The runtime changed after export.", allow_terminal=True)
        snapshot = prepare_trial_evaluation(config=self.config, user=self.user, request=self.request)
        assert snapshot.runs[0].exclusion_reason is not None
        judge = AsyncMock()
        with patch(f"{JUDGE_MODULE}.judge_trial_run", judge):
            async_to_sync(run_evaluation_run)(self.team.id, snapshot.evaluation_id, self.launch.id)
        judge.assert_not_called()
        report = finish_trial_evaluation(self.team.id, snapshot.evaluation_id)
        assert report.runs[0].status == "excluded"

    @parameterized.expand(
        ["user_id", "context_id", "model", "runtime_adapter", "reasoning_effort", "service_tier", "skill_body"]
    )
    def test_rejects_mixed_launch_ownership_context_or_settings(self, field: str) -> None:
        changes: dict[str, object] = {"id": uuid4()}
        changes[field] = {
            "user_id": self.user.id + 1,
            "context_id": uuid4(),
            "model": "different-model",
            "runtime_adapter": "claude",
            "reasoning_effort": "high",
            "service_tier": "priority",
            "skill_body": "Different instructions.",
        }[field]
        other = self.launch.model_copy(update=changes)
        self._save("launches", other.id, other)
        variant = self.request.variants[0].model_copy(update={"launch_ids": [self.launch.id, other.id]})
        request = self.request.model_copy(update={"variants": [variant]})
        with self.assertRaises(TrialEvaluationError):
            prepare_trial_evaluation(config=self.config, user=self.user, request=request)

    def test_private_task_owner_must_match_the_saved_launch(self) -> None:
        task = self.scout_run.task_run.task
        task.created_by = None
        task.save(update_fields=["created_by"])
        with self.assertRaisesMessage(TrialEvaluationError, "private task and operator"):
            prepare_trial_evaluation(config=self.config, user=self.user, request=self.request)

    @parameterized.expand(["pending", "unknown", "not_started"])
    def test_unbound_launch_needs_a_known_terminal_workflow(
        self, status: Literal["pending", "unknown", "not_started"]
    ) -> None:
        other = self.launch.model_copy(update={"id": uuid4()})
        self._save("launches", other.id, other)
        variant = self.request.variants[0].model_copy(update={"launch_ids": [other.id]})
        request = self.request.model_copy(update={"variants": [variant]})
        with patch(f"{MODULE}.get_trial_workflow_status", return_value=TrialWorkflowStatus(status=status)):
            with self.assertRaisesMessage(TrialEvaluationError, "known terminal state"):
                prepare_trial_evaluation(config=self.config, user=self.user, request=request)

    @parameterized.expand(["foreign_chain", "oversized"])
    def test_trace_reads_are_limited_to_the_exact_bounded_run(self, scenario: str) -> None:
        urls = [self.scout_run.task_run.log_url]
        if scenario == "foreign_chain":
            urls.insert(0, "s3://example/another-run.jsonl")
        with (
            patch(f"{MODULE}.get_task_run_log_urls", return_value=urls),
            patch(f"{MODULE}.get_task_run_log_size", return_value=MAX_TRACE_BYTES + 1),
            patch(f"{MODULE}.read_task_run_log_content") as read_content,
        ):
            snapshot = prepare_trial_evaluation(config=self.config, user=self.user, request=self.request)
        read_content.assert_not_called()
        assert not any(source.kind == "trace" for source in snapshot.runs[0].sources)
        assert any("trace" in limitation for limitation in snapshot.runs[0].limitations)

    def test_truncated_evidence_is_explicit_and_snapshot_is_bounded(self) -> None:
        self.scout_run.summary = "Synthetic finding. " * MAX_SOURCE_CHARS
        self.scout_run.save(update_fields=["summary"])
        snapshot = prepare_trial_evaluation(config=self.config, user=self.user, request=self.request)
        source = next(source for source in snapshot.runs[0].sources if source.kind == "summary")
        assert len(source.text) == MAX_SOURCE_CHARS
        assert source.text.endswith("[Evidence truncated]")
        assert any("summary was truncated" in value for value in snapshot.runs[0].limitations)

    @parameterized.expand([False, True])
    def test_retries_do_not_repeat_paid_judgments(self, interrupted: bool) -> None:
        snapshot = prepare_trial_evaluation(config=self.config, user=self.user, request=self.request)
        judgment = TrialRunJudgment(
            launch_id=self.launch.id,
            variant_id=self.request.baseline_variant_id,
            status="judge_error",
            summary="Synthetic unavailable judgment.",
            error="Synthetic failure",
        )
        judge = AsyncMock(return_value=judgment)
        with patch(f"{JUDGE_MODULE}.judge_trial_run", judge):
            async_to_sync(run_evaluation_run)(self.team.id, snapshot.evaluation_id, self.launch.id)
            if interrupted:
                del self.documents[
                    f"signals/scout-trials/{self.team.id}/evaluations/{snapshot.evaluation_id}/runs/{self.launch.id}.json"
                ]
            async_to_sync(run_evaluation_run)(self.team.id, snapshot.evaluation_id, self.launch.id)
        judge.assert_awaited_once()
        report = finish_trial_evaluation(self.team.id, snapshot.evaluation_id)
        assert report.runs[0].status == "judge_error"

    def test_worker_rechecks_operator_access_before_judging(self) -> None:
        snapshot = prepare_trial_evaluation(config=self.config, user=self.user, request=self.request)
        self.user.is_staff = False
        self.user.save(update_fields=["is_staff"])
        judge = AsyncMock()
        with patch(f"{JUDGE_MODULE}.judge_trial_run", judge):
            async_to_sync(run_evaluation_run)(self.team.id, snapshot.evaluation_id, self.launch.id)
        judge.assert_not_called()
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        assert finish_trial_evaluation(self.team.id, snapshot.evaluation_id).runs[0].status == "judge_error"


class TestScoutTrialEvaluationWorkflow(SimpleTestCase):
    async def test_bounds_concurrency_and_finalizes_after_one_activity_fails(self) -> None:
        inputs = TrialEvaluationInput(team_id=2, evaluation_id=str(uuid4()))
        launch_ids = [str(uuid4()) for _ in range(7)]
        reached_limit = asyncio.Event()
        release = asyncio.Event()
        active = 0
        highest_active = 0
        completed: set[str] = set()
        finalized = False

        async def execute(function: Callable[..., object], payload: object, **options: object) -> object:
            nonlocal active, highest_active, finalized
            if function is load_scout_trial_evaluation_activity:
                return launch_ids
            if function is finish_scout_trial_evaluation_activity:
                assert completed == set(launch_ids)
                finalized = True
                return None
            assert isinstance(payload, TrialEvaluationRunInput)
            policy = options["retry_policy"]
            assert isinstance(policy, RetryPolicy) and policy.maximum_attempts == 1
            active += 1
            highest_active = max(highest_active, active)
            if active == 3:
                reached_limit.set()
            await release.wait()
            active -= 1
            completed.add(payload.launch_id)
            if payload.launch_id == launch_ids[0]:
                raise ActivityError(
                    "Synthetic worker interruption",
                    scheduled_event_id=1,
                    started_event_id=2,
                    identity="worker",
                    activity_type="judge_scout_trial_run_activity",
                    activity_id="scoring",
                    retry_state=None,
                )
            return None

        with patch(f"{WORKFLOW_MODULE}.workflow.execute_activity", side_effect=execute):
            task = asyncio.create_task(RunScoutTrialEvaluationWorkflow().run(inputs))
            try:
                await reached_limit.wait()
                assert active == 3
            finally:
                release.set()
            assert await task == inputs.evaluation_id
        assert highest_active == 3
        assert finalized

    async def test_activity_failure_does_not_put_evidence_in_temporal_history(self) -> None:
        with patch(f"{MODULE}.read_trial_evaluation", side_effect=ValueError("Private synthetic evidence")):
            with self.assertRaisesMessage(ApplicationError, "The saved evaluation could not be loaded.") as failure:
                await load_scout_trial_evaluation_activity(TrialEvaluationInput(team_id=2, evaluation_id=str(uuid4())))
        assert "Private synthetic evidence" not in str(failure.exception)
        assert failure.exception.non_retryable
