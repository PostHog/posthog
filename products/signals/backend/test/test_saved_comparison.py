from __future__ import annotations

import json
import asyncio
import hashlib
import tempfile
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from unittest.mock import AsyncMock, Mock, patch

from django.test import SimpleTestCase, override_settings

from parameterized import parameterized

from posthog.temporal.oauth import SIGNALS_APP_ID_DEV

from products.posthog_ai.eval_harness.base import EvalTaskError
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.engines.types import CaseHooks
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.signals.backend.models import SignalScoutRun
from products.signals.backend.rubrics_schema import default_criteria
from products.signals.backend.scout_harness.trial_comparison import ScoutTrialComparisons
from products.signals.backend.scout_harness.trial_comparison_types import (
    TrialComparisonPlan,
    TrialComparisonRequest,
    TrialComparisonVariant,
    TrialComparisonVariantResult,
)
from products.signals.backend.temporal.agentic.scout_scheduler import trial_run_workflow_id
from products.signals.backend.temporal.agentic.scout_trial_comparison import trial_comparison_workflow_id
from products.signals.backend.temporal.agentic.scout_trial_evaluation import trial_evaluation_workflow_id
from products.signals.evals.agentic import saved_comparison
from products.signals.evals.agentic.rubric_session import RubricSnapshot, SessionRubric
from products.signals.evals.agentic.saved_comparison import SavedComparisonSuite
from products.signals.evals.agentic.saved_comparison_plan import (
    SavedComparison,
    SavedComparisonPlan,
    SavedComparisonVariant,
)
from products.signals.evals.agentic.saved_dataset import SavedScoutDataset
from products.tasks.backend.facade.agents import CustomPromptSandboxContext

MODULE = "products.signals.evals.agentic.saved_comparison"
SKILL_NAME = "signals-scout-deliveries"
NOW = datetime(2030, 6, 4, 12, tzinfo=UTC)


@override_settings(TEST=True, DEBUG=True)
class TestSavedComparison(SimpleTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))
        variant = TrialComparisonVariant(
            id=uuid4(), label="Baseline", launch_ids=[uuid4(), uuid4()], model="gpt-6-sol", reasoning_effort="high"
        )
        request = TrialComparisonRequest(comparison_id=uuid4(), baseline_variant_id=variant.id, variants=[variant])
        self.plan = TrialComparisonPlan(
            comparison_id=request.comparison_id,
            team_id=7,
            config_id=uuid4(),
            user_id=11,
            context_id=uuid4(),
            skill_name=SKILL_NAME,
            skill_version=1,
            variants=[
                TrialComparisonVariantResult(**variant.model_dump(exclude={"skill_body"}), skill_body_sha256="a" * 64)
            ],
            created_at=NOW,
            request=request,
            request_hash="b" * 64,
            rubric_document={"revision": 1},
            judge_model="gpt-6-astra",
            judge_prompt_version="invented-version",
        )
        self.dataset = Mock(spec=SavedScoutDataset, cases=(), metadata={})
        self.suite = SavedComparisonSuite(
            self.dataset,
            SavedComparisonPlan(
                comparisons=(
                    SavedComparison(
                        skill_name=SKILL_NAME,
                        variants=(
                            SavedComparisonVariant(label="Baseline", model="gpt-6-sol", reasoning_effort="high"),
                        ),
                    ),
                )
            ),
            self.directory,
            NOW,
            self.directory / "session",
            self.directory / "output",
            "gpt-6-sol",
        )
        rubric = SessionRubric(
            scout_name=SKILL_NAME,
            generated_at=NOW,
            criteria=default_criteria(),
            canonical_references={"instructions": "Inspect delivery dates."},
            source={},
            generation={},
        )
        self.suite.rubrics[SKILL_NAME] = RubricSnapshot(
            document=rubric, path=self.directory / "session-rubric.json", sha256="c" * 64
        )
        self.ctx = Mock(spec=EvalContext, provider_strategy=Mock())
        self.service = Mock(spec=ScoutTrialComparisons)
        self.service.result.return_value = SimpleNamespace(
            model_dump=Mock(return_value={"status": "completed"}),
            status="completed",
            error=None,
            evaluation=SimpleNamespace(report=SimpleNamespace(runs=[])),
        )
        self.service.evaluation.return_value = SimpleNamespace(model_dump=Mock(return_value={"runs": []}))
        self.temporal_client = Mock()
        self.handles: dict[str, Mock] = {}

        def handle(identifier: str) -> Mock:
            return self.handles.setdefault(identifier, Mock(id=identifier, result=AsyncMock(), cancel=AsyncMock()))

        self.temporal_client.get_workflow_handle.side_effect = handle
        self.enterContext(patch(f"{MODULE}.async_connect", AsyncMock(return_value=self.temporal_client)))
        self.enterContext(
            patch(f"{MODULE}.load_trial_context", return_value=SimpleNamespace(model_dump=Mock(return_value={})))
        )
        self.enterContext(
            patch(
                f"{MODULE}.start_trial_comparison",
                return_value=trial_comparison_workflow_id(self.plan.team_id, self.plan.comparison_id),
            )
        )
        self.finish = self.enterContext(patch(f"{MODULE}.finish_workflow", AsyncMock(return_value=True)))

    def _comparison_directory(self) -> Path:
        return self.suite.output_dir / "comparisons" / str(self.plan.comparison_id)

    @parameterized.expand(["missing_log", "missing_ancestor", "log_head", "result_read", "cleanup"])
    async def test_export_failure_keeps_other_artifacts_and_cleans_every_run(self, failure: str) -> None:
        runs = [Mock(spec=SignalScoutRun), Mock(spec=SignalScoutRun)]
        for run in runs:
            run.id = uuid4()
            run.team_id = self.plan.team_id
            run.task_run = SimpleNamespace(
                id=uuid4(),
                task_id=uuid4(),
                workflow_id=f"task-{uuid4()}",
                status="completed",
                state={"turns": 1},
                error_message=None,
                arefresh_from_db=AsyncMock(),
            )
        queryset = Mock()
        queryset.select_related.return_value.filter.return_value.afirst = AsyncMock(side_effect=runs)
        raw_log = '{"message":"Invented delivery evidence é\\n"}\n' * 10_000

        def log_head(key: str) -> dict[str, str | int] | None:
            if key == "ancestor.jsonl":
                if failure == "missing_ancestor":
                    return None
                if failure == "log_head":
                    raise RuntimeError("Object storage unavailable")
            size = len(raw_log.encode()) if key == "second.jsonl" else len(raw_log.encode()) // 2
            return {"ContentLength": size, "ETag": "invented-object-etag"}

        if failure == "cleanup":
            self.ctx.provider_strategy.cleanup_case.side_effect = [RuntimeError("cleanup unavailable"), None]
        with (
            patch(f"{MODULE}.SignalScoutRun.objects.for_team", return_value=queryset),
            patch(f"{MODULE}.read_trial_launch", return_value=SimpleNamespace(model_dump=Mock(return_value={}))),
            patch(
                f"{MODULE}.tasks_facade.read_task_run_logs",
                side_effect=[None if failure == "missing_log" else raw_log, raw_log],
            ),
            patch(
                f"{MODULE}.tasks_facade.get_task_run_log_urls",
                side_effect=[["ancestor.jsonl", "first.jsonl"], ["second.jsonl"]],
            ),
            patch(f"{MODULE}.object_storage.head_object", side_effect=log_head),
            patch(
                f"{MODULE}.read_trial_result",
                side_effect=[
                    RuntimeError("result unavailable") if failure == "result_read" else {"status": "completed"},
                    {"status": "completed"},
                ],
            ),
            patch(f"{MODULE}.ScoutTrialStore") as store,
        ):
            store.return_value.export.return_value = {"reports": [{"content": "Invented delivery report."}]}
            with self.assertRaisesRegex(RuntimeError, "Some trial artifacts could not be collected"):
                await self.suite._export_runs(self.plan, self._comparison_directory(), self.ctx)

        first, second = [
            self._comparison_directory() / "runs" / str(identifier) for identifier in self.plan.variants[0].launch_ids
        ]
        self.assertTrue(json.loads((first / "collection.json").read_text())["errors"])
        self.assertTrue((first / "private-state.json").exists())
        if failure in {"missing_ancestor", "log_head"}:
            self.assertEqual((first / "task.jsonl").read_text(), raw_log)
            provenance = json.loads((first / "task.json").read_text())["log_objects"]
            self.assertEqual([entry["key"] for entry in provenance], ["ancestor.jsonl", "first.jsonl"])
            self.assertEqual([entry["available"] for entry in provenance], [False, True])
        self.assertEqual((second / "task.jsonl").read_text(), raw_log)
        self.assertEqual((second / "task.jsonl").stat().st_mode & 0o777, 0o600)
        self.assertEqual(
            json.loads((second / "task.json").read_text())["log_sha256"], hashlib.sha256(raw_log.encode()).hexdigest()
        )
        self.assertEqual(json.loads((second / "collection.json").read_text())["errors"], [])
        self.assertEqual(
            json.loads((second / "task.json").read_text())["log_objects"],
            [
                {
                    "key": "second.jsonl",
                    "available": True,
                    "content_length": len(raw_log.encode()),
                    "etag": "invented-object-etag",
                }
            ],
        )
        self.assertEqual(self.ctx.provider_strategy.cleanup_case.call_count, 2)
        self.assertEqual(self.ctx.provider_strategy.register_task.call_count, 2)

    @parameterized.expand(["workflow_failure", "cancellation", "failure_with_collection_error"])
    async def test_interrupted_comparison_waits_for_dispatch_and_exports_after_cleanup(self, outcome: str) -> None:
        dispatch_entered = asyncio.Event()
        dispatch_release = asyncio.Event()
        finished_ids: list[str] = []
        workflow_id = trial_comparison_workflow_id(self.plan.team_id, self.plan.comparison_id)
        handle = self.temporal_client.get_workflow_handle(workflow_id)
        handle.result.side_effect = RuntimeError("workflow failed")

        async def dispatch(_function: Callable[..., object], *args: object, **kwargs: object) -> object:
            if _function is start_function:
                dispatch_entered.set()
                await dispatch_release.wait()
                return workflow_id
            return await original_to_thread(_function, *args, **kwargs)

        async def finish(handle: Mock, **kwargs: object) -> bool:
            self.assertTrue(dispatch_release.is_set())
            finished_ids.append(handle.id)
            return True

        async def export(*args: object) -> None:
            self.assertEqual(finished_ids[0], workflow_id)
            self.assertEqual(len(finished_ids), 4)
            if outcome == "failure_with_collection_error":
                raise RuntimeError("collection failed")

        original_to_thread = asyncio.to_thread
        start_function = saved_comparison.start_trial_comparison
        with (
            patch(f"{MODULE}.asyncio.to_thread", side_effect=dispatch),
            patch(f"{MODULE}.finish_workflow", side_effect=finish),
            patch.object(self.suite, "_export_runs", side_effect=export) as export_runs,
        ):
            task = asyncio.create_task(self.suite._compare(self.service, self.plan, self.ctx))
            await asyncio.wait_for(dispatch_entered.wait(), timeout=1)
            if outcome == "cancellation":
                task.cancel()
            dispatch_release.set()
            if outcome == "cancellation":
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(task, timeout=1)
            else:
                with self.assertRaisesRegex(RuntimeError, "workflow failed"):
                    await asyncio.wait_for(task, timeout=1)

        export_runs.assert_awaited_once()
        self.assertEqual(finished_ids[-1], trial_evaluation_workflow_id(self.plan.team_id, self.plan.comparison_id))
        self.assertEqual(
            set(finished_ids[1:-1]),
            {
                trial_run_workflow_id(self.plan.team_id, str(identifier))
                for identifier in self.plan.variants[0].launch_ids
            },
        )
        self.assertTrue((self._comparison_directory() / "judge-input.json").exists())
        self.assertTrue((self._comparison_directory() / "result.json").exists())
        if outcome == "failure_with_collection_error":
            self.assertIn("collection failed", (self._comparison_directory() / "collection.json").read_text())

    @parameterized.expand(["collection", "judge_error", "excluded", "judged"])
    async def test_completed_comparison_preserves_errors_and_inconclusive_judgments(self, status: str) -> None:
        self.service.result.return_value.evaluation.report.runs = [
            SimpleNamespace(status="judged" if status == "collection" else status, score=None, coverage=0.0)
        ]
        failure = RuntimeError("missing transcript") if status == "collection" else None
        with patch.object(self.suite, "_export_runs", AsyncMock(side_effect=failure)):
            if status == "judged":
                result = await self.suite._compare(self.service, self.plan, self.ctx)
                self.assertEqual(result["status"], "completed")
            else:
                with self.assertRaises(RuntimeError):
                    await self.suite._compare(self.service, self.plan, self.ctx)
        errors = json.loads((self._comparison_directory() / "collection.json").read_text())["errors"]
        if status == "collection":
            self.assertIn("missing transcript", errors[0])
        else:
            self.assertEqual(errors, [])
        self.assertTrue((self._comparison_directory() / "result.json").exists())
        self.assertTrue((self._comparison_directory() / "judge-input.json").exists())

    @parameterized.expand([False, True])
    async def test_shared_state_audit_runs_after_failure_and_stops_successful_mutation(self, failed: bool) -> None:
        saved = Mock(skill_name=SKILL_NAME)
        self.dataset.cases = (saved,)
        self.service.create.return_value = self.plan
        context = Mock(spec=CustomPromptSandboxContext, team_id=self.plan.team_id)
        with (
            patch.object(SavedComparison, "request", return_value=self.plan.request),
            patch.object(self.suite, "_service", return_value=self.service),
            patch.object(
                self.suite,
                "_compare",
                AsyncMock(side_effect=RuntimeError("scout failed") if failed else None, return_value={}),
            ),
            patch(f"{MODULE}.shared_state_fingerprint", side_effect=[{"reports": "before"}, {"reports": "after"}]),
        ):
            with self.assertRaisesRegex(EvalTaskError, "scout failed" if failed else "changed the shared reports"):
                await self.suite._task(
                    SandboxedEvalCase(name="case", prompt=""), context, self.ctx, Mock(spec=CaseHooks)
                )
        self.assertEqual(json.loads((self.suite.output_dir / "base-after.json").read_text()), {"reports": "after"})
        self.assertTrue((self.suite.output_dir / "isolation-error.json").exists())

    @parameterized.expand(["success", "empty", "execution_failure", "wrong_oauth", "production"])
    async def test_suite_keeps_private_gateway_through_execution_and_fails_closed(self, outcome: str) -> None:
        active = False

        @asynccontextmanager
        async def gateway(_ctx: EvalContext) -> AsyncIterator[None]:
            nonlocal active
            active = True
            try:
                yield
            finally:
                active = False

        async def execute(**kwargs: object) -> SimpleNamespace:
            self.assertTrue(active)
            return SimpleNamespace(
                results=[]
                if outcome == "empty"
                else [SimpleNamespace(error="failed" if outcome == "execution_failure" else None)]
            )

        with (
            override_settings(TEST=outcome != "production"),
            patch(f"{MODULE}.call_command") as setup_oauth,
            patch(
                f"{MODULE}.get_signals_app",
                return_value=SimpleNamespace(id=uuid4() if outcome == "wrong_oauth" else SIGNALS_APP_ID_DEV),
            ),
            patch(f"{MODULE}.private_backend_gateway", side_effect=gateway),
            patch(f"{MODULE}.WorkflowPrivateEval", side_effect=execute) as evaluate,
        ):
            if outcome == "success":
                await self.suite.run(self.ctx)
            else:
                with self.assertRaises(RuntimeError):
                    await self.suite.run(self.ctx)
            if outcome == "production":
                setup_oauth.assert_not_called()
            if outcome in ("wrong_oauth", "production"):
                evaluate.assert_not_called()
        self.assertFalse(active)
