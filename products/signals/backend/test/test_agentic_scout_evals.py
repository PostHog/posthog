from __future__ import annotations

import json
import asyncio
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock

from django.db import OperationalError

from posthog.models import Organization, Team

from products.posthog_ai.eval_harness.base import EvalTaskCancelled, EvalTaskError
from products.posthog_ai.eval_harness.harness.providers import DockerProviderStrategy
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalScoutRun, SignalScratchpad
from products.signals.backend.scout_harness.runner import RunResult
from products.signals.evals.agentic.datasets import ScoutCase
from products.signals.evals.agentic.runners import run_scout
from products.tasks.backend.facade.agents import CustomPromptSandboxContext
from products.tasks.backend.models import Task, TaskRun


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    ("ending", "keep_containers"),
    [
        ("completed", False),
        ("error", False),
        ("failed_result", False),
        ("cancelled", False),
        ("task_cancelled", False),
        ("task_failed", False),
        ("finalization_cancelled", False),
        ("finalization_unconfirmed", False),
        ("transcript_error", False),
        ("malformed_transcript", False),
        ("state_read_error", False),
        ("error", True),
    ],
)
def test_scout_capture_preserves_changes_and_isolates_teams(
    monkeypatch: pytest.MonkeyPatch, ending: str, keep_containers: bool
) -> None:
    org = Organization.objects.create(name="Saved scout case")
    team = Team.objects.create(organization=org)
    other_team = Team.objects.create(organization=org)
    report = SignalReport.objects.create(team=team, title="Original report", summary="Original evidence")
    deleted_report = SignalReport.objects.create(team=team, title="Superseded report")
    SignalReport.objects.create(team=other_team, title="Other team's report")
    memory = SignalScratchpad.objects.for_team(team.id).create(team=team, key="cursor", content="before")
    deleted_memory = SignalScratchpad.objects.for_team(team.id).create(team=team, key="expired", content="remove")
    SignalScratchpad.objects.for_team(other_team.id).create(team=other_team, key="private", content="other team")
    case = ScoutCase(
        case_id="saved-case",
        step="scout",
        skill_name="signals-scout-example",
        skill_version=3,
        repository="posthog/hedgebox",
        run_note="Inspect the saved case.",
    )
    ids: dict[str, str] = {}
    runner_task: asyncio.Task[dict[str, Any]] | None = None
    finalized = False
    task_status = {"cancelled": "cancelled", "task_cancelled": "cancelled", "task_failed": "failed"}.get(
        ending, "completed"
    )

    def perform_run() -> RunResult:
        report.summary = "Updated evidence"
        report.save(update_fields=["summary"])
        deleted_report.delete()
        artifact = SignalReportArtefact.objects.create(
            team=team,
            report=report,
            type="note",
            content=json.dumps({"text": "Source evidence"}),
        )
        new_report = SignalReport.objects.create(team=team, title="New finding", summary="New evidence")
        memory.content = "after"
        memory.save(update_fields=["content"])
        deleted_memory.delete()
        new_memory = SignalScratchpad.objects.for_team(team.id).create(team=team, key="finding", content="full content")
        task = Task.objects.create(
            team=team, title="Eval task", description="Inspect a saved case", origin_product="signals"
        )
        task_run = TaskRun.objects.create(
            team=team,
            task=task,
            status="completed" if ending == "finalization_unconfirmed" else "in_progress",
            state={"sandbox_connect_token": "synthetic-test-token", "workflow_id": "saved-scout-workflow"},
        )
        run = SignalScoutRun.objects.for_team(team.id).create(
            team=team,
            task_run=task_run,
            skill_name=case.skill_name,
            skill_version=3,
            summary="Completed investigation",
            emitted_report_ids=[str(new_report.id)],
            edited_report_ids=[str(report.id)],
            metadata={"model": "test-model", "reasoning_effort": "medium"},
        )
        ids.update(
            artifact=str(artifact.id),
            new_report=str(new_report.id),
            new_memory=str(new_memory.id),
            run=str(run.id),
            task=str(task.id),
            task_run=str(task_run.id),
        )
        return RunResult(
            run_id=str(run.id),
            task_run_id=str(task_run.id),
            status="failed" if ending == "failed_result" else "completed",
            last_message=None if ending == "failed_result" else "done",
            runtime_s=1.0,
            skill_name=case.skill_name,
            skill_version=3,
        )

    async def production_run(**kwargs: Any) -> RunResult:
        nonlocal runner_task
        runner_task = asyncio.current_task()
        result = await asyncio.to_thread(perform_run)
        if ending == "state_read_error":
            monkeypatch.setattr(
                SignalReport.objects, "filter", MagicMock(side_effect=OperationalError("Database unavailable"))
            )
        if ending == "error":
            raise RuntimeError("Execution failed after a write")
        if ending == "cancelled":
            raise asyncio.CancelledError
        return result

    production = AsyncMock(side_effect=production_run)
    monkeypatch.setattr("products.signals.backend.scout_harness.runner.arun_signals_scout", production)
    raw_log = ("null\n" if ending == "malformed_transcript" else "") + '{"notification":{"method":"session/update"}}'
    lifecycle: list[str] = []

    def persist_final_state() -> None:
        TaskRun.objects.filter(id=ids["task_run"]).update(status=task_status)
        SignalScoutRun.objects.for_team(team.id).filter(id=ids["run"]).update(summary="Final investigation")

    async def finish_workflow() -> None:
        nonlocal finalized
        if ending == "finalization_unconfirmed":
            raise TimeoutError
        if ending == "finalization_cancelled":
            assert runner_task is not None
            runner_task.cancel()
        await asyncio.to_thread(persist_final_state)
        finalized = True

    workflow_handle = MagicMock(result=AsyncMock(side_effect=finish_workflow), cancel=AsyncMock(), signal=AsyncMock())
    temporal_client = MagicMock(get_workflow_handle=MagicMock(return_value=workflow_handle))
    monkeypatch.setattr("products.signals.evals.agentic.runners.async_connect", AsyncMock(return_value=temporal_client))

    def read_task_logs(*_: object) -> str:
        lifecycle.append("read_transcript")
        if ending == "transcript_error":
            raise RuntimeError("Transcript storage unavailable")
        return raw_log if finalized else "incomplete transcript"

    monkeypatch.setattr("products.tasks.backend.facade.api.read_task_run_logs", read_task_logs)
    monkeypatch.setattr(
        "products.posthog_ai.eval_harness.harness.providers.cleanup_case_containers",
        lambda task_id: lifecycle.append(f"cleanup:{task_id}"),
    )
    context = CustomPromptSandboxContext(team_id=team.id, user_id=1, repository=case.repository)
    provider = DockerProviderStrategy(keep_containers=keep_containers)
    runtime = MagicMock(
        agent_model="test-model", agent_runtime="codex", reasoning_effort="medium", provider_strategy=provider
    )

    if ending == "completed":
        output = asyncio.run(run_scout(case, context, runtime))
    else:
        expected_error = EvalTaskCancelled if ending in {"cancelled", "finalization_cancelled"} else EvalTaskError
        with pytest.raises(expected_error) as caught:
            asyncio.run(run_scout(case, context, runtime))
        assert isinstance(caught.value, EvalTaskCancelled | EvalTaskError)
        if ending == "task_cancelled":
            assert str(caught.value) == "Scout task was cancelled"
        elif ending == "task_failed":
            assert str(caught.value) == "Scout task did not complete: failed"
        elif ending == "failed_result":
            assert str(caught.value) == "Scout execution failed"
        output = caught.value.output

    if ending == "state_read_error":
        assert output["run_id"] == ids["run"]
        assert output["task_run_id"] == ids["task_run"]
        assert output["raw_log"] == ""
        assert output["artifacts"]["result"]["status"] == "completed"
        assert output["artifacts"]["requested"]["skill_version"] == 3
        assert {row["key"]: row["content"] for row in output["artifacts"]["before"]["scratchpad"]} == {
            "cursor": "before",
            "expired": "remove",
        }
        assert "after" not in output["artifacts"]
        assert "changes" not in output["artifacts"]
        assert "Database unavailable" in output["artifacts"]["collection_error"]
        assert "synthetic-test-token" not in json.dumps(output)
        assert lifecycle == []
        return

    assert lifecycle == ["read_transcript"] + ([] if keep_containers else [f"cleanup:{ids['task']}"])
    provider.cleanup()
    assert lifecycle == ["read_transcript"] + ([] if keep_containers else [f"cleanup:{ids['task']}"] * 2)
    assert production.call_args.kwargs["skill_version"] == 3
    assert production.call_args.kwargs["repository"] == "posthog/hedgebox"
    assert production.call_args.kwargs["run_note"] == case.run_note
    assert output["outcome"] == "emit_report"
    assert output["run_id"] == ids["run"]
    assert output["raw_log"] == (
        ""
        if ending == "transcript_error"
        else "incomplete transcript"
        if ending == "finalization_unconfirmed"
        else raw_log
    )
    assert output["summary"] == (
        "Completed investigation" if ending == "finalization_unconfirmed" else "Final investigation"
    )
    assert output["scratchpad_keys"] == ["finding"]
    artifacts = output["artifacts"]
    assert artifacts["workflow"] == {"id": "saved-scout-workflow", "terminal": ending != "finalization_unconfirmed"}
    assert artifacts["task_run"]["status"] == task_status
    temporal_client.get_workflow_handle.assert_called_once_with("saved-scout-workflow")
    workflow_handle.signal.assert_not_awaited()
    assert {row["team_id"] for row in artifacts["after"]["reports"]} == {team.id}
    assert {row["team_id"] for row in artifacts["after"]["scratchpad"]} == {team.id}
    assert [row["content"] for row in artifacts["after"]["report_artefacts"]] == [
        json.dumps({"text": "Source evidence"})
    ]
    assert {row["key"]: row["content"] for row in artifacts["before"]["scratchpad"]} == {
        "cursor": "before",
        "expired": "remove",
    }
    assert {row["key"]: row["content"] for row in artifacts["after"]["scratchpad"]} == {
        "cursor": "after",
        "finding": "full content",
    }
    assert artifacts["changes"]["reports"]["created"] == [ids["new_report"]]
    assert artifacts["changes"]["reports"]["updated"] == [str(report.id)]
    assert len(artifacts["changes"]["reports"]["deleted"]) == 1
    assert artifacts["changes"]["scratchpad"]["updated"] == [str(memory.id)]
    assert len(artifacts["changes"]["scratchpad"]["deleted"]) == 1
    assert artifacts["after"]["scout_runs"][0]["metadata"]["reasoning_effort"] == "medium"
    assert "synthetic-test-token" not in json.dumps(output)
