from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from unittest.mock import AsyncMock, MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError

from posthog.storage import object_storage

from products.signals.backend.scout_harness.trial_comparison import list_comparison_history_keys
from products.signals.backend.scout_harness.trial_comparison_serializers import ScoutTrialComparisonRequestSerializer
from products.signals.backend.scout_harness.trial_comparison_types import TrialEvaluationReservation
from products.signals.backend.scout_harness.trial_evaluation import TrialEvaluationError, reserve_trial_evaluation
from products.signals.backend.temporal.agentic.scout_trial_comparison import (
    RunScoutTrialComparisonWorkflow,
    TrialComparisonInput,
    dispatch_scout_trial_comparison_activity,
    fail_scout_trial_comparison_activity,
    finish_scout_trial_comparison_activity,
    prepare_scout_trial_comparison_evaluation_activity,
    start_trial_comparison,
)

MODULE = "products.signals.backend.temporal.agentic.scout_trial_comparison"


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

    def test_comparison_dispatch_reuses_existing_workflow_and_keeps_payload_small(self) -> None:
        comparison_id = uuid4()
        client = AsyncMock()
        client.start_workflow.side_effect = [None, WorkflowAlreadyStartedError("synthetic", "comparison")]
        with patch(f"{MODULE}.async_connect", AsyncMock(return_value=client)):
            first = start_trial_comparison(2, comparison_id)
            assert start_trial_comparison(2, comparison_id) == first
        for call in client.start_workflow.await_args_list:
            assert call.kwargs["id"] == first
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
            payload["variants"] = [variant] * 11
        serializer = ScoutTrialComparisonRequestSerializer(data=payload)
        assert not serializer.is_valid()


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
