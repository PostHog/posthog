from __future__ import annotations

import json
import asyncio
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

from django.conf import settings
from django.core.management import call_command
from django.core.serializers.json import DjangoJSONEncoder
from django.test import override_settings

from pydantic import JsonValue
from temporalio.service import RPCError, RPCStatusCode

from posthog.clickhouse.query_tagging import private_capture_context
from posthog.models import User
from posthog.storage import object_storage
from posthog.temporal.common.client import async_connect
from posthog.temporal.oauth import SIGNALS_APP_ID_DEV, get_signals_app

from products.posthog_ai.eval_harness.base import EvalTaskError
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.engines.types import CaseHooks
from products.posthog_ai.eval_harness.runner import finish_workflow
from products.posthog_ai.eval_harness.workflow import WorkflowPrivateEval
from products.signals.backend.models import (
    SignalReport,
    SignalReportArtefact,
    SignalScoutConfig,
    SignalScoutNote,
    SignalScoutRun,
    SignalScratchpad,
)
from products.signals.backend.scout_harness.trial_comparison import ScoutTrialComparisons
from products.signals.backend.scout_harness.trial_comparison_types import TrialComparisonPlan
from products.signals.backend.scout_harness.trial_launch import load_trial_context, read_trial_launch
from products.signals.backend.scout_harness.trial_result import read_trial_result
from products.signals.backend.scout_harness.trial_state import ScoutTrialStore
from products.signals.backend.temporal.agentic.scout_scheduler import trial_run_workflow_id
from products.signals.backend.temporal.agentic.scout_trial_comparison import (
    start_trial_comparison,
    trial_comparison_workflow_id,
)
from products.signals.backend.temporal.agentic.scout_trial_evaluation import trial_evaluation_workflow_id
from products.signals.evals.agentic.rubric_session import RubricSnapshot
from products.signals.evals.agentic.saved_comparison_plan import SavedComparisonPlan
from products.signals.evals.agentic.saved_comparison_rubrics import (
    install_session_rubric,
    validate_session_rubric_time_shift,
)
from products.signals.evals.agentic.saved_dataset import SavedScoutDataset
from products.signals.evals.agentic.saved_rubrics import SavedRubrics
from products.signals.evals.saved_scout import private_backend_gateway
from products.tasks.backend.facade import api as tasks_facade

if TYPE_CHECKING:
    from temporalio.client import Client

    from products.posthog_ai.eval_harness.harness.context import EvalContext
    from products.tasks.backend.facade.agents import CustomPromptSandboxContext

logger = logging.getLogger(__name__)


def write_private_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.write_text(json.dumps(value, cls=DjangoJSONEncoder, indent=2, sort_keys=True) + "\n")
    path.chmod(0o600)


def shared_state_fingerprint(team_id: int) -> dict[str, str]:
    collections = {
        "reports": SignalReport.objects.filter(team_id=team_id),
        "report_artefacts": SignalReportArtefact.objects.filter(team_id=team_id),
        "memory": SignalScratchpad.objects.for_team(team_id),
        "notes": SignalScoutNote.objects.for_team(team_id),
    }
    return {
        name: hashlib.sha256(
            json.dumps(list(rows.order_by("id").values()), cls=DjangoJSONEncoder, sort_keys=True).encode()
        ).hexdigest()
        for name, rows in collections.items()
    }


class SavedComparisonSuite:
    def __init__(
        self,
        dataset: SavedScoutDataset,
        plan: SavedComparisonPlan,
        plan_directory: Path,
        target_cutoff: datetime,
        session_dir: Path,
        output_dir: Path,
        rubric_model: str,
    ) -> None:
        self.dataset = dataset
        self.plan = plan
        self.plan_directory = plan_directory
        self.target_cutoff = target_cutoff
        self.session_dir = session_dir
        self.output_dir = output_dir
        self.rubric_model = rubric_model
        self.rubrics: dict[str, RubricSnapshot] = {}
        self.restore_metadata: dict[str, JsonValue] = {}

    def _restore(self, context: CustomPromptSandboxContext) -> dict[str, JsonValue]:
        if not settings.TEST or not settings.DEBUG:
            raise RuntimeError("Saved comparisons require the isolated eval database in DEBUG mode")
        metadata = self.dataset.restore(context, target_cutoff=self.target_cutoff)
        User.objects.filter(id=context.user_id).update(is_staff=True, is_email_verified=True)
        for skill_name, rubric in self.rubrics.items():
            config = SignalScoutConfig.objects.for_team(context.team_id).get(skill_name=skill_name)
            install_session_rubric(config, rubric)
        self.restore_metadata = metadata
        write_private_json(self.output_dir / "restore.json", metadata)
        return metadata

    @staticmethod
    def _service(context: CustomPromptSandboxContext, skill_name: str) -> ScoutTrialComparisons:
        config = SignalScoutConfig.objects.for_team(context.team_id).select_related("team").get(skill_name=skill_name)
        user = User.objects.get(id=context.user_id)
        return ScoutTrialComparisons(config, user)

    async def _export_runs(self, plan: TrialComparisonPlan, directory: Path, ctx: EvalContext) -> None:
        client = await async_connect()
        failures: list[str] = []
        for variant in plan.variants:
            for launch_id in variant.launch_ids:
                target = directory / "runs" / str(launch_id)
                errors: list[str] = []
                run: SignalScoutRun | None = None
                try:
                    try:
                        launch = await asyncio.to_thread(read_trial_launch, plan.team_id, launch_id)
                        write_private_json(target / "launch.json", launch.model_dump(mode="json"))
                    except Exception as error:
                        errors.append(f"launch: {error}")
                    run = await (
                        SignalScoutRun.objects.for_team(plan.team_id)
                        .select_related("task_run")
                        .filter(scout_config_id=plan.config_id, metadata__scout_trial__launch_id=str(launch_id))
                        .afirst()
                    )
                    if run is None:
                        raise RuntimeError("The trial did not create a scout run")
                    await self._export_task(run, target, ctx, client, errors)
                except Exception as error:
                    errors.append(str(error))
                finally:
                    try:
                        write_private_json(
                            target / "collection.json", {"run_id": str(run.id) if run else None, "errors": errors}
                        )
                    except Exception as error:
                        errors.append(f"collection record: {error}")
                failures.extend(f"{launch_id}: {error}" for error in errors)
        if failures:
            raise RuntimeError("Some trial artifacts could not be collected: " + "; ".join(failures))

    async def _export_task(
        self, run: SignalScoutRun, target: Path, ctx: EvalContext, client: Client, errors: list[str]
    ) -> None:
        task_run = run.task_run
        task_id = str(task_run.task_id)
        assert ctx.provider_strategy is not None
        ctx.provider_strategy.register_task(task_id)
        terminal = False
        raw_log: str | None = None
        log_objects: list[dict[str, JsonValue]] = []
        try:
            try:
                terminal = await finish_workflow(
                    client.get_workflow_handle(task_run.workflow_id), status=None, reason=None
                )
                if not terminal:
                    errors.append("The task workflow did not stop before export")
                await task_run.arefresh_from_db()
            except Exception as error:
                errors.append(f"task completion: {error}")
            try:
                raw_log = await asyncio.to_thread(
                    tasks_facade.read_task_run_logs, task_run.id, task_run.task_id, run.team_id
                )
                if raw_log is None or (task_run.status == "completed" and not raw_log):
                    errors.append("The trial's full task log is unavailable")
                if raw_log is not None:
                    path = target / "task.jsonl"
                    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    path.write_text(raw_log)
                    path.chmod(0o600)
            except Exception as error:
                errors.append(f"task log: {error}")
            try:
                log_urls = await asyncio.to_thread(
                    tasks_facade.get_task_run_log_urls, task_run.id, task_run.task_id, run.team_id
                )
                if not log_urls:
                    errors.append("The trial's task log references are unavailable")
                for log_url in log_urls or []:
                    provenance: dict[str, JsonValue] = {"key": log_url, "available": False}
                    log_objects.append(provenance)
                    try:
                        # The shared concatenating reader omits missing resume-chain objects.
                        metadata = await asyncio.to_thread(object_storage.head_object, log_url)
                        if metadata is None:
                            errors.append(f"Task log object is unavailable: {log_url}")
                            continue
                        provenance["available"] = True
                        size = metadata.get("ContentLength")
                        etag = metadata.get("ETag")
                        provenance["content_length"] = size if isinstance(size, int) else None
                        provenance["etag"] = etag if isinstance(etag, str) else None
                    except Exception as error:
                        provenance["error"] = str(error)
                        errors.append(f"task log object {log_url}: {error}")
            except Exception as error:
                errors.append(f"task log references: {error}")
            try:
                write_private_json(
                    target / "task.json",
                    {
                        "id": task_run.id,
                        "task_id": task_run.task_id,
                        "status": task_run.status,
                        "state": task_run.state,
                        "error_message": task_run.error_message,
                        "workflow_id": task_run.workflow_id,
                        "workflow_terminal": terminal,
                        "log_sha256": hashlib.sha256(raw_log.encode()).hexdigest() if raw_log is not None else None,
                        "log_objects": log_objects,
                    },
                )
                result = await asyncio.to_thread(read_trial_result, run)
                write_private_json(target / "result.json", result)
                if result is None:
                    errors.append("The trial result is unavailable")
            except Exception as error:
                errors.append(f"task result: {error}")
            try:
                state = await asyncio.to_thread(ScoutTrialStore(run).export)
                write_private_json(target / "private-state.json", state)
            except Exception as error:
                errors.append(f"private state: {error}")
        finally:
            try:
                await asyncio.to_thread(ctx.provider_strategy.cleanup_case, task_id)
            except Exception as error:
                errors.append(f"sandbox cleanup: {error}")

    async def _finalize(
        self,
        service: ScoutTrialComparisons,
        plan: TrialComparisonPlan,
        directory: Path,
        ctx: EvalContext,
        client: Client,
        started: asyncio.Task[str],
        finished: bool,
    ) -> None:
        errors: list[str] = []
        try:
            await started
        except Exception as error:
            errors.append(f"workflow dispatch: {error}")
        if not finished:
            identifiers = [
                trial_comparison_workflow_id(plan.team_id, plan.comparison_id),
                *[
                    trial_run_workflow_id(plan.team_id, str(launch_id))
                    for variant in plan.variants
                    for launch_id in variant.launch_ids
                ],
                trial_evaluation_workflow_id(plan.team_id, plan.comparison_id),
            ]
            # Stop dispatch before inspecting child runs so no new task can appear after collection.
            for identifier in identifiers:
                handle = client.get_workflow_handle(identifier)
                try:
                    await handle.cancel()
                except RPCError as error:
                    if error.status == RPCStatusCode.NOT_FOUND:
                        continue
                    errors.append(f"workflow cancellation {identifier}: {error}")
                except Exception as error:
                    errors.append(f"workflow cancellation {identifier}: {error}")
                try:
                    if not await finish_workflow(handle, status=None, reason=None):
                        errors.append(f"Workflow cleanup could not be confirmed: {identifier}")
                except Exception as error:
                    errors.append(f"workflow completion {identifier}: {error}")
        try:
            result = await asyncio.to_thread(service.result, plan, inspect_workflow=False)
            write_private_json(directory / "result.json", result.model_dump(mode="json"))
        except Exception as error:
            errors.append(f"comparison result: {error}")
        try:
            snapshot = await asyncio.to_thread(service.evaluation, plan)
            if snapshot is not None:
                write_private_json(directory / "judge-input.json", snapshot.model_dump(mode="json"))
        except Exception as error:
            errors.append(f"judge input: {error}")
        try:
            await self._export_runs(plan, directory, ctx)
        except Exception as error:
            errors.append(f"trial collection: {error}")
        write_private_json(directory / "collection.json", {"errors": errors})
        if errors:
            raise RuntimeError("Comparison cleanup or artifact collection failed; see collection.json")

    async def _compare(
        self, service: ScoutTrialComparisons, plan: TrialComparisonPlan, ctx: EvalContext
    ) -> dict[str, JsonValue]:
        directory = self.output_dir / "comparisons" / str(plan.comparison_id)
        write_private_json(directory / "plan.json", plan.model_dump(mode="json"))
        source = await asyncio.to_thread(load_trial_context, plan.team_id, plan.context_id)
        write_private_json(directory / "context.json", source.model_dump(mode="json"))
        rubric = self.rubrics[plan.skill_name]
        write_private_json(
            directory / "session-rubric.json",
            {"sha256": rubric.sha256, "path": str(rubric.path), "document": rubric.document.model_dump(mode="json")},
        )
        client = await async_connect()
        workflow_id = trial_comparison_workflow_id(plan.team_id, plan.comparison_id)
        handle = client.get_workflow_handle(workflow_id)
        started = asyncio.create_task(asyncio.to_thread(start_trial_comparison, plan.team_id, plan.comparison_id))
        finished = False
        try:
            await asyncio.shield(started)
            await handle.result()
            finished = True
        finally:
            finalizer = asyncio.create_task(self._finalize(service, plan, directory, ctx, client, started, finished))
            try:
                await asyncio.shield(finalizer)
            except asyncio.CancelledError:
                try:
                    await asyncio.shield(finalizer)
                except Exception:
                    logger.exception("Comparison cleanup failed during cancellation")
                raise
            except Exception:
                if finished:
                    raise
                logger.exception("Comparison cleanup also failed")
        result = await asyncio.to_thread(service.result, plan, inspect_workflow=False)
        report = result.evaluation.report if result.evaluation else None
        if result.status != "completed" or report is None:
            raise RuntimeError(result.error or "The online comparison did not produce a report")
        if any(run.status == "judge_error" for run in report.runs):
            raise RuntimeError("The online judge failed for one or more trials; see the saved comparison report")
        if any(run.status == "excluded" for run in report.runs):
            raise RuntimeError("One or more trials could not be evaluated; see the saved comparison report")
        return {"comparison_id": str(plan.comparison_id), "directory": str(directory), "status": result.status}

    async def _audit_shared_state(self, team_id: int, before: dict[str, str]) -> None:
        try:
            after = await asyncio.to_thread(shared_state_fingerprint, team_id)
            write_private_json(self.output_dir / "base-after.json", after)
            if before != after:
                write_private_json(self.output_dir / "isolation-error.json", {"before": before, "after": after})
                raise RuntimeError("A trial changed the shared reports, notes or memory; stop this batch")
        except Exception as error:
            write_private_json(self.output_dir / "isolation-check.json", {"error": str(error)})
            raise

    async def _task(
        self,
        case: SandboxedEvalCase,
        context: CustomPromptSandboxContext,
        ctx: EvalContext,
        hooks: CaseHooks,
    ) -> dict[str, object]:
        output: dict[str, object] = {"artifacts": {"directory": str(self.output_dir)}}
        cases = {saved.skill_name: saved for saved in self.dataset.cases}
        before = await asyncio.to_thread(shared_state_fingerprint, context.team_id)
        write_private_json(self.output_dir / "base-before.json", before)
        try:
            with private_capture_context(), override_settings(SCOUT_LIVE_TRIALS_LOCAL_PROJECT_IDS={context.team_id}):
                results: list[dict[str, JsonValue]] = []
                output["comparisons"] = results
                for comparison in self.plan.comparisons:
                    comparison_finished = False
                    try:
                        request = comparison.request(
                            self.plan_directory,
                            cases[comparison.skill_name],
                            target_cutoff=self.target_cutoff,
                        )
                        service = await asyncio.to_thread(self._service, context, comparison.skill_name)
                        plan = await asyncio.to_thread(service.create, request)
                        logger.info("Online comparison %s: %s", plan.comparison_id, plan.skill_name)
                        results.append(await self._compare(service, plan, ctx))
                        comparison_finished = True
                    finally:
                        try:
                            await self._audit_shared_state(context.team_id, before)
                        except Exception:
                            if comparison_finished:
                                raise
                            logger.exception("Shared state validation also failed; see isolation-check.json")
                output["exit_code"] = 0
                return output
        except Exception as error:
            raise EvalTaskError(str(error), output) from error

    async def run(self, ctx: EvalContext) -> None:
        if not settings.TEST or not settings.DEBUG:
            raise RuntimeError("Saved comparisons require the isolated eval database in DEBUG mode")
        await asyncio.to_thread(call_command, "setup_tasks_oauth")
        signals_app = await asyncio.to_thread(get_signals_app)
        if signals_app is None or str(signals_app.id) != SIGNALS_APP_ID_DEV:
            raise RuntimeError("The eval database needs the configured Signals development OAuth application")
        selected = {comparison.skill_name for comparison in self.plan.comparisons}
        async with private_backend_gateway(ctx):
            for saved in self.dataset.cases:
                if saved.skill_name in selected:
                    self.rubrics[saved.skill_name] = await SavedRubrics(
                        saved, self.session_dir, self.output_dir, generator_model=self.rubric_model
                    ).prepare()
                    validate_session_rubric_time_shift(saved, self.rubrics[saved.skill_name], self.target_cutoff)
            result = await WorkflowPrivateEval(
                experiment_name="signals-saved-comparison",
                cases=[
                    SandboxedEvalCase(
                        name="shared-scout-dataset",
                        prompt="Compare scout variants against one restored dataset and fixed rubrics",
                        project_data="empty",
                        metadata=cast(dict[str, object], self.dataset.metadata),
                        setup=self._restore,
                    )
                ],
                scorers=[],
                task=self._task,
                ctx=ctx,
                output_dir=self.output_dir,
            )
        if not result.results or any(row.error for row in result.results):
            raise RuntimeError("The saved comparison failed; inspect its private results")
