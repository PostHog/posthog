import uuid
import datetime as dt

import pytest

from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.schema import PulseScanConfig

from products.pulse.backend.models import PulseDigestStatus
from products.pulse.backend.temporal.types import EnrichedFinding, Finding, MetricDescriptor
from products.pulse.backend.temporal.workflow import PulseScanInputs, PulseScanWorkflow


def _scan_inputs() -> PulseScanInputs:
    # config is supplied so the workflow skips load_scan_config_activity (the manual-trigger path).
    return PulseScanInputs(
        team_id=1,
        period_key="2026-W22",
        period_start=dt.datetime(2026, 5, 18, tzinfo=dt.UTC).isoformat(),
        period_end=dt.datetime(2026, 5, 25, tzinfo=dt.UTC).isoformat(),
        config=PulseScanConfig(),
    )


def _finding() -> Finding:
    return Finding(
        descriptor=MetricDescriptor(source="top_event", label="Signups", query={}),
        current_value=120.0,
        baseline_value=80.0,
        change_pct=0.5,
        impact=4.47,
        robust_z=3.2,
    )


def _enriched_finding() -> EnrichedFinding:
    return EnrichedFinding(
        descriptor=MetricDescriptor(source="top_event", label="Signups", query={}),
        current_value=120.0,
        baseline_value=80.0,
        change_pct=0.5,
        impact=4.47,
        robust_z=3.2,
        narrative="Signups rose notably.",
    )


async def _run_scan(*, detect_raises: bool = False, findings: list[Finding] | None = None, statuses: list[str]) -> dict:
    """Drive PulseScanWorkflow.run with name-matched mock activities; record set_digest_status calls.

    With no `findings`, detect returns nothing and the workflow takes the no-findings path. Pass
    `findings` to drive the enrichment/notification path; `detect_raises` forces a failure instead.
    """
    detected = findings or []

    @activity.defn(name="create_or_get_digest_activity")
    async def m_create(team_id: int, period_key: str, period_start: str, period_end: str) -> str:
        return "digest-1"

    @activity.defn(name="set_workflow_run_id_activity")
    async def m_runid(team_id: int, digest_id: str, run_id: str) -> None:
        return None

    @activity.defn(name="fetch_findings_activity")
    async def m_fetch(inputs: object) -> list[Finding]:
        if detect_raises:
            raise RuntimeError("fetch boom")
        return detected

    @activity.defn(name="enrich_findings_activity")
    async def m_enrich(inputs: object) -> list[EnrichedFinding]:
        return [_enriched_finding() for _ in detected]

    @activity.defn(name="synthesize_digest_activity")
    async def m_synthesize(inputs: object) -> None:
        return None

    @activity.defn(name="persist_findings_activity")
    async def m_persist(inputs: object) -> list:
        return []

    @activity.defn(name="notify_digest_activity")
    async def m_notify(inputs: object) -> None:
        return None

    @activity.defn(name="emit_pulse_events_activity")
    async def m_emit(inputs: object) -> None:
        return None

    @activity.defn(name="set_digest_status_activity")
    async def m_status(team_id: int, digest_id: str, status: str, error: str | None = None) -> None:
        statuses.append(status)

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping(data_converter=pydantic_data_converter) as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[PulseScanWorkflow],
            activities=[
                m_create,
                m_runid,
                m_fetch,
                m_enrich,
                m_synthesize,
                m_persist,
                m_notify,
                m_emit,
                m_status,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            return await env.client.execute_workflow(
                PulseScanWorkflow.run,
                _scan_inputs(),
                id=f"test-pulse-scan-{task_queue}",
                task_queue=task_queue,
            )


class TestPulseScanWorkflowStateMachine:
    @pytest.mark.asyncio
    async def test_no_findings_path_delivers_zero(self):
        statuses: list[str] = []
        result = await _run_scan(detect_raises=False, statuses=statuses)
        assert result["finding_count"] == 0
        assert PulseDigestStatus.DELIVERED.value in statuses
        assert PulseDigestStatus.FAILED.value not in statuses

    @pytest.mark.asyncio
    async def test_activity_failure_marks_digest_failed(self):
        statuses: list[str] = []
        with pytest.raises(WorkflowFailureError):
            await _run_scan(detect_raises=True, statuses=statuses)
        assert PulseDigestStatus.FAILED.value in statuses
        assert PulseDigestStatus.DELIVERED.value not in statuses

    @pytest.mark.asyncio
    async def test_with_findings_path_delivers_enriched(self):
        statuses: list[str] = []
        result = await _run_scan(findings=[_finding()], statuses=statuses)
        assert result["finding_count"] == 1
        assert PulseDigestStatus.DELIVERED.value in statuses
        assert PulseDigestStatus.FAILED.value not in statuses
