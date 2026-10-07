from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from unittest.mock import AsyncMock, MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized
from pydantic import ValidationError
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError

from posthog.storage import object_storage

from products.signals.backend.scout_harness.trial_comparison import list_comparison_history_keys
from products.signals.backend.scout_harness.trial_comparison_serializers import ScoutTrialComparisonRequestSerializer
from products.signals.backend.scout_harness.trial_comparison_types import (
    TrialComparisonRequest,
    TrialEvaluationReservation,
)
from products.signals.backend.scout_harness.trial_evaluation import TrialEvaluationError, reserve_trial_evaluation
from products.signals.backend.scout_harness.trial_evaluation_serializers import ScoutTrialEvaluationRequestSerializer
from products.signals.backend.scout_harness.trial_evaluation_types import TrialEvaluationRequest
from products.signals.backend.temporal.agentic.scout_trial_comparison import (
    RunScoutTrialComparisonWorkflow,
    TrialComparisonInput,
    dispatch_scout_trial_comparison_activity,
    fail_scout_trial_comparison_activity,
    finish_scout_trial_comparison_activity,
    prepare_scout_trial_comparison_evaluation_activity,
    start_trial_comparison,
)
from products.signals.backend.trial_execution import TrialCoordinator

MODULE = "products.signals.backend.temporal.agentic.scout_trial_comparison"


class TestTrialCoordinator(SimpleTestCase):
    def test_retries_preserve_execution_ids_and_wait_for_runner_completion(self) -> None:
        execution_ids = [uuid4(), uuid4()]
        started: list[UUID] = []
        finished: set[UUID] = set()

        class Runner:
            def prepare(self) -> list[UUID]:
                return execution_ids

            def start(self, execution_id: UUID) -> None:
                started.append(execution_id)

            def finished(self, execution_id: UUID) -> bool:
                return execution_id in finished

        coordinator = TrialCoordinator(Runner())
        coordinator.start()
        coordinator.start()
        assert started == execution_ids * 2
        assert not coordinator.finished(execution_ids)
        finished.add(execution_ids[0])
        assert not coordinator.finished(execution_ids)
        finished.add(execution_ids[1])
        assert coordinator.finished(execution_ids)


class TestScoutTrialComparisonWorkflow(SimpleTestCase):
    @parameterized.expand([False, True])
    async def test_background_comparison_waits_for_runs_and_report_or_records_timeout(self, times_out: bool) -> None:
        inputs = TrialComparisonInput(team_id=2, comparison_id=str(uuid4()))
        now = datetime(2026, 1, 1, tzinfo=UTC)
        prepared = False
        finished = False
        failed = False
        prepare_calls = 0
        report_calls = 0

        async def execute(function: Callable[..., object], payload: object, **options: object) -> object:
            nonlocal prepared, finished, failed, prepare_calls, report_calls
            assert payload == inputs
            if function is dispatch_scout_trial_comparison_activity:
                return None
            if function is prepare_scout_trial_comparison_evaluation_activity:
                prepare_calls += 1
                prepared = prepare_calls > 1 and not times_out
                return prepared
            if function is finish_scout_trial_comparison_activity:
                assert prepared
                report_calls += 1
                finished = report_calls > 1
                return finished
            if function is fail_scout_trial_comparison_activity:
                failed = True
                return None
            raise AssertionError("Unexpected workflow activity")

        async def sleep(seconds: int) -> None:
            nonlocal now
            now += timedelta(minutes=40) if times_out else timedelta(seconds=seconds)

        with (
            patch(f"{MODULE}.workflow.execute_activity", side_effect=execute),
            patch(f"{MODULE}.workflow.sleep", side_effect=sleep),
            patch(f"{MODULE}.workflow.now", side_effect=lambda: now),
        ):
            if times_out:
                with self.assertRaisesMessage(ApplicationError, "scout runs did not finish"):
                    await RunScoutTrialComparisonWorkflow().run(inputs)
                assert failed and not finished
            else:
                assert await RunScoutTrialComparisonWorkflow().run(inputs) == inputs.comparison_id
                assert prepared and finished and not failed

    async def test_judging_wait_bounds_sandbox_evaluation_workflows(self) -> None:
        expected_minutes = 2427
        inputs = TrialComparisonInput(team_id=2, comparison_id=str(uuid4()))
        now = datetime(2026, 1, 1, tzinfo=UTC)
        started = now
        waited = 0
        failed = False

        async def execute(function: Callable[..., object], payload: object, **options: object) -> object:
            nonlocal failed
            if function is dispatch_scout_trial_comparison_activity:
                return None
            if function is prepare_scout_trial_comparison_evaluation_activity:
                return True
            if function is finish_scout_trial_comparison_activity:
                return False
            if function is fail_scout_trial_comparison_activity:
                failed = True
                return None
            raise AssertionError("Unexpected workflow activity")

        async def sleep(seconds: int) -> None:
            nonlocal now, waited
            waited += 1
            now += timedelta(minutes=1)

        with (
            patch(f"{MODULE}.workflow.execute_activity", side_effect=execute),
            patch(f"{MODULE}.workflow.sleep", side_effect=sleep),
            patch(f"{MODULE}.workflow.now", side_effect=lambda: now),
        ):
            with self.assertRaisesMessage(ApplicationError, "Judging did not finish in time"):
                await RunScoutTrialComparisonWorkflow().run(inputs)
        assert failed
        assert waited == expected_minutes
        assert now - started == timedelta(minutes=expected_minutes)

    def test_comparison_dispatch_reuses_existing_workflow_and_keeps_payload_small(self) -> None:
        comparison_id = uuid4()
        client = AsyncMock()
        client.start_workflow.side_effect = [None, WorkflowAlreadyStartedError("synthetic", "comparison")]
        with patch(f"{MODULE}.async_connect", AsyncMock(return_value=client)):
            first = start_trial_comparison(2, comparison_id)
            assert start_trial_comparison(2, comparison_id) == first
        for call in client.start_workflow.await_args_list:
            assert call.kwargs["id"] == first
            assert call.kwargs["execution_timeout"] == timedelta(minutes=2492)
            assert call.kwargs["id_conflict_policy"] == WorkflowIDConflictPolicy.USE_EXISTING
            assert call.kwargs["id_reuse_policy"] == WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY
            assert call.args[1] == TrialComparisonInput(team_id=2, comparison_id=str(comparison_id))


class TestScoutTrialComparisonSerializer(SimpleTestCase):
    @parameterized.expand(["prompt_limit", "empty_prompt", "note_limit", "empty_runs", "too_many_variants"])
    def test_rejects_unbounded_or_empty_launch_inputs(self, invalid: str) -> None:
        variant: dict[str, object] = {
            "id": str(uuid4()),
            "label": "Baseline",
            "launch_ids": [str(uuid4())],
            "model": "gpt-5.5",
            "reasoning_effort": "medium",
        }
        payload: dict[str, object] = {
            "comparison_id": str(uuid4()),
            "baseline_variant_id": variant["id"],
            "variants": [variant],
        }
        if invalid == "prompt_limit":
            variant["skill_body"] = "x" * 100_001
        elif invalid == "empty_prompt":
            variant["skill_body"] = ""
        elif invalid == "note_limit":
            payload["note"] = "x" * 1001
        elif invalid == "empty_runs":
            variant["launch_ids"] = []
        else:
            payload["variants"] = [variant] * 21
        serializer = ScoutTrialComparisonRequestSerializer(data=payload)
        assert not serializer.is_valid()

    @parameterized.expand(
        [
            (kind, variants, repeats, valid)
            for kind in ("comparison", "evaluation")
            for variants, repeats, valid in ((20, 2, True), (20, 20, True), (21, 2, False), (20, 21, False))
        ]
    )
    def test_capacity_limits_versions_and_repeats_separately(
        self, kind: str, variants: int, repeats: int, valid: bool
    ) -> None:
        groups = [
            {
                "id": str(uuid4()),
                "label": f"Version {index + 1}",
                "launch_ids": [str(uuid4()) for _ in range(repeats)],
                **({"model": "gpt-5.5", "reasoning_effort": "medium"} if kind == "comparison" else {}),
            }
            for index in range(variants)
        ]
        payload = {
            f"{kind}_id": str(uuid4()),
            "baseline_variant_id": groups[0]["id"],
            "variants": groups,
            **({"rubric_source": "saved"} if kind == "evaluation" else {}),
        }
        serializer_type = (
            ScoutTrialComparisonRequestSerializer if kind == "comparison" else ScoutTrialEvaluationRequestSerializer
        )
        request_type = TrialComparisonRequest if kind == "comparison" else TrialEvaluationRequest
        serializer = serializer_type(data=payload)
        assert serializer.is_valid() is valid, serializer.errors
        if valid:
            request = request_type.model_validate(serializer.validated_data)
            assert sum(len(variant.launch_ids) for variant in request.variants) == variants * repeats
        else:
            with self.assertRaises(ValidationError):
                request_type.model_validate(payload)


class TestScoutTrialComparisonStorage(SimpleTestCase):
    @parameterized.expand(["empty", "populated", "failure"])
    def test_history_listing_is_bounded_and_does_not_hide_storage_failures(self, scenario: str) -> None:
        prefix = "signals/scout-trials/2/comparison-history/17/example/"
        client = MagicMock()
        client.list_objects_v2.return_value = (
            {"Contents": [{"Key": prefix + "example.json"}]} if scenario == "populated" else {}
        )
        if scenario == "failure":
            client.list_objects_v2.side_effect = RuntimeError("Synthetic private storage failure")
        with patch.object(object_storage, "object_storage_client", return_value=object_storage.ObjectStorage(client)):
            if scenario == "failure":
                with self.assertRaisesMessage(
                    object_storage.ObjectStorageError, "history could not be loaded"
                ) as failure:
                    list_comparison_history_keys(prefix, 10)
                assert "private" not in str(failure.exception)
            else:
                assert list_comparison_history_keys(prefix, 10) == (
                    [prefix + "example.json"] if scenario == "populated" else []
                )
        assert client.list_objects_v2.call_args.kwargs["MaxKeys"] == 11
        assert client.list_objects_v2.call_args.kwargs["Prefix"] == prefix

    @parameterized.expand(["comparison", "evaluation"])
    def test_manual_and_automatic_evaluations_cannot_claim_the_same_identity(self, first_kind: str) -> None:
        documents: dict[str, str] = {}
        first = TrialEvaluationReservation(
            team_id=2,
            evaluation_id=uuid4(),
            config_id=uuid4(),
            user_id=17,
            kind="comparison" if first_kind == "comparison" else "evaluation",
            request_hash="synthetic-first",
        )
        other = first.model_copy(
            update={
                "kind": "evaluation" if first_kind == "comparison" else "comparison",
                "request_hash": "synthetic-other",
            }
        )
        with (
            patch.object(object_storage, "read", side_effect=lambda key, **kwargs: documents.get(key)),
            patch.object(
                object_storage, "write", side_effect=lambda key, content, **kwargs: documents.__setitem__(key, content)
            ),
        ):
            reserve_trial_evaluation(first)
            reserve_trial_evaluation(first)
            with self.assertRaisesMessage(TrialEvaluationError, "already reserved"):
                reserve_trial_evaluation(other)
        assert list(documents.values()) == [first.model_dump_json()]
