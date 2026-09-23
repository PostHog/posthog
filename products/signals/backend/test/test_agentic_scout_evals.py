from __future__ import annotations

import json
import asyncio
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock

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
    [("completed", False), ("error", False), ("cancelled", False), ("transcript_error", False), ("error", True)],
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
            status="completed",
            state={"sandbox_connect_token": "synthetic-test-token"},
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
        )
        return RunResult(
            run_id=str(run.id),
            task_run_id=str(task_run.id),
            status="completed",
            last_message="done",
            runtime_s=1.0,
            skill_name=case.skill_name,
            skill_version=3,
        )

    async def production_run(**kwargs: Any) -> RunResult:
        result = await asyncio.to_thread(perform_run)
        if ending == "error":
            raise RuntimeError("Execution failed after a write")
        if ending == "cancelled":
            raise asyncio.CancelledError
        return result

    production = AsyncMock(side_effect=production_run)
    monkeypatch.setattr("products.signals.backend.scout_harness.runner.arun_signals_scout", production)
    raw_log = '{"notification":{"method":"session/update"}}'
    lifecycle: list[str] = []

    def read_task_logs(*_: object) -> str:
        lifecycle.append("read_transcript")
        if ending == "transcript_error":
            raise RuntimeError("Transcript storage unavailable")
        return raw_log

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
        expected_error = EvalTaskCancelled if ending == "cancelled" else EvalTaskError
        with pytest.raises(expected_error) as caught:
            asyncio.run(run_scout(case, context, runtime))
        assert isinstance(caught.value, EvalTaskCancelled | EvalTaskError)
        output = caught.value.output

    assert lifecycle == ["read_transcript"] + ([] if keep_containers else [f"cleanup:{ids['task']}"])
    provider.cleanup()
    assert lifecycle == ["read_transcript"] + ([] if keep_containers else [f"cleanup:{ids['task']}"] * 2)
    assert production.call_args.kwargs["skill_version"] == 3
    assert production.call_args.kwargs["repository"] == "posthog/hedgebox"
    assert production.call_args.kwargs["run_note"] == case.run_note
    assert output["outcome"] == "emit_report"
    assert output["run_id"] == ids["run"]
    assert output["raw_log"] == ("" if ending == "transcript_error" else raw_log)
    assert output["scratchpad_keys"] == ["finding"]
    artifacts = output["artifacts"]
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
