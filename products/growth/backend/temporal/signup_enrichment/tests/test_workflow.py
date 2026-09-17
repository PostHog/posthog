import uuid
import asyncio
import datetime as dt
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from temporalio.api.enums.v1 import EventType
from temporalio.client import WorkflowExecutionStatus, WorkflowHistory
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Replayer, UnsandboxedWorkflowRunner, Worker

from posthog.dataclasses import frozen

from products.growth.backend.enrichment.core import EnrichmentOutcome
from products.growth.backend.enrichment.fields import EnrichmentFields
from products.growth.backend.enrichment.fit_score import IcpFitResult
from products.growth.backend.temporal.signup_enrichment.workflow import (
    SignupEnrichmentInputs,
    SignupEnrichmentRecheckWorkflow,
    SignupEnrichmentWorkflow,
    enrich_signup_organization_activity,
)

pytestmark = pytest.mark.asyncio

_MODULE = "products.growth.backend.temporal.signup_enrichment.workflow"
_INPUTS = SignupEnrichmentInputs(organization_id="org-1", distinct_id="d1", domain="stripe.com")
_TASK_QUEUE = "signup-enrichment-test-queue"
_EVALUATED_AT = dt.datetime(2026, 9, 14, 12, 0, tzinfo=dt.UTC)
_RECHECK_ID = f"signup-enrichment-recheck-{_INPUTS.organization_id}"
_TEST_RECHECK_DELAY = dt.timedelta(milliseconds=100)
# An execution that took the un-patched path, where the recheck is a timer and a second activity
# in this same workflow, recorded against a mocked activity.
_PRE_CHILD_HISTORY = Path(__file__).parent / "signup_enrichment_pre_recheck_child_history.json"


@frozen
class _EnrichmentRun:
    parent_result: dict
    recheck_result: dict
    parent_history: WorkflowHistory
    recheck_history: WorkflowHistory
    pha_client: MagicMock
    enrich: AsyncMock
    snapshot: MagicMock


def _events(pha_client: MagicMock, name: str) -> list:
    return [c for c in pha_client.capture.call_args_list if c.kwargs["event"] == name]


def _event_types(history: WorkflowHistory) -> list[int]:
    return [event.event_type for event in history.events]


async def _run(enrich_side_effect) -> _EnrichmentRun:
    pha_client = MagicMock()
    enrich = AsyncMock(side_effect=enrich_side_effect)
    with (
        patch(f"{_MODULE}.get_regional_ph_client", return_value=pha_client),
        patch(f"{_MODULE}.enrich_organization", enrich),
        patch(f"{_MODULE}._deterministic_company_type", return_value=None),
        patch(f"{_MODULE}.capture_signup_enrichment_snapshot") as snapshot,
        # A handle from get_workflow_handle never unlocks the time-skipping clock, so the child
        # has to reach its activity on a delay that elapses in real time.
        patch(f"{_MODULE}.RECHECK_DELAY", _TEST_RECHECK_DELAY),
        patch("posthog.models.Organization.objects") as org_objects,
    ):
        org_objects.filter.return_value.exists.return_value = True
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=_TASK_QUEUE,
                workflows=[SignupEnrichmentWorkflow, SignupEnrichmentRecheckWorkflow],
                activities=[enrich_signup_organization_activity],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                parent = await env.client.start_workflow(
                    SignupEnrichmentWorkflow.run,
                    _INPUTS,
                    id=f"signup-enrichment-{uuid.uuid4()}",
                    task_queue=_TASK_QUEUE,
                )
                parent_result = await parent.result()
                recheck = env.client.get_workflow_handle(_RECHECK_ID)
                recheck_result = await recheck.result()
                parent_history = await parent.fetch_history()
                recheck_history = await recheck.fetch_history()
    return _EnrichmentRun(
        parent_result=parent_result,
        recheck_result=recheck_result,
        parent_history=parent_history,
        recheck_history=recheck_history,
        pha_client=pha_client,
        enrich=enrich,
        snapshot=snapshot,
    )


async def test_miss_then_recheck_upgrades_without_a_second_completed_event():
    fields = EnrichmentFields(company_type="STARTUP", headcount=130, industry="Fintech")
    miss = EnrichmentOutcome(provider_fields=None, fit=IcpFitResult(status="not_found"))
    match = EnrichmentOutcome(
        provider_fields=fields,
        fit=IcpFitResult(status="scored", score=61),
        fit_evaluated_at=_EVALUATED_AT,
        enrichment_status="COMPLETE",
    )
    run = await _run([miss, match])

    assert run.parent_result == {"matched": False, "fields_filled": 0}
    assert run.recheck_result == {"matched": True, "fields_filled": 3}
    assert run.enrich.await_count == 2
    # The is_recheck label is threaded through to the enrichment core: False first, True on recheck.
    assert run.enrich.await_args_list[0].kwargs["ctx"].is_recheck is False
    assert run.enrich.await_args_list[1].kwargs["ctx"].is_recheck is True
    # is_recheck=True skips the at-signup snapshot, so it is captured only on the first attempt.
    run.snapshot.assert_called_once()

    parent_types = _event_types(run.parent_history)
    # A timer in the parent's own history is what keeps every signup execution in flight for the
    # whole delay, so a deploy that edits the parent replays all of them.
    assert EventType.EVENT_TYPE_TIMER_STARTED not in parent_types
    assert parent_types.count(EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED) == 1
    assert EventType.EVENT_TYPE_START_CHILD_WORKFLOW_EXECUTION_INITIATED in parent_types

    recheck_types = _event_types(run.recheck_history)
    assert recheck_types.index(EventType.EVENT_TYPE_TIMER_STARTED) < recheck_types.index(
        EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED
    )
    assert [
        event.timer_started_event_attributes.start_to_fire_timeout.ToTimedelta()
        for event in run.recheck_history.events
        if event.event_type == EventType.EVENT_TYPE_TIMER_STARTED
    ] == [_TEST_RECHECK_DELAY]

    recheck = _events(run.pha_client, "signup_enrichment_recheck")
    assert len(recheck) == 1
    assert recheck[0].kwargs["properties"] == {
        "upgraded": True,
        "fields_filled": 3,
        "organization_id": "org-1",
        "icp_fit_status": "scored",
        "icp_fit_evaluated_at": _EVALUATED_AT.isoformat(),
        "icp_fit_evaluation_kind": "recheck",
        "harmonic_enrichment_status": "COMPLETE",
    }
    # The launch signal fires exactly once, on the first attempt, unchanged.
    completed = _events(run.pha_client, "signup_enrichment_completed")
    assert len(completed) == 1
    assert completed[0].kwargs["properties"]["matched"] is False
    assert completed[0].kwargs["properties"]["icp_fit_status"] == "not_found"


async def test_match_on_first_attempt_still_runs_the_recheck():
    fields = EnrichmentFields(company_type="STARTUP", headcount=130)
    match = EnrichmentOutcome(provider_fields=fields, fit=IcpFitResult(status="scored", score=61))
    run = await _run([match, match])

    assert run.parent_result == {"matched": True, "fields_filled": 2}
    assert run.recheck_result == {"matched": True, "fields_filled": 2}
    assert run.enrich.await_count == 2
    assert run.enrich.await_args_list[1].kwargs["ctx"].is_recheck is True
    run.snapshot.assert_called_once()

    # Already matched at the first attempt, so matching again at recheck is not an upgrade. The
    # child can only tell because the parent passed its own outcome down.
    recheck = _events(run.pha_client, "signup_enrichment_recheck")
    assert len(recheck) == 1
    assert recheck[0].kwargs["properties"]["upgraded"] is False
    assert len(_events(run.pha_client, "signup_enrichment_completed")) == 1


async def test_a_second_signup_dispatch_keeps_its_first_leg_while_a_recheck_is_pending():
    fields = EnrichmentFields(company_type="STARTUP", headcount=130)
    match = EnrichmentOutcome(provider_fields=fields, fit=IcpFitResult(status="scored", score=61))
    enrich = AsyncMock(side_effect=[match, match])
    with (
        patch(f"{_MODULE}.get_regional_ph_client", return_value=MagicMock()),
        patch(f"{_MODULE}.enrich_organization", enrich),
        patch(f"{_MODULE}._deterministic_company_type", return_value=None),
        patch(f"{_MODULE}.capture_signup_enrichment_snapshot"),
        patch("posthog.models.Organization.objects") as org_objects,
    ):
        org_objects.filter.return_value.exists.return_value = True
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=_TASK_QUEUE,
                workflows=[SignupEnrichmentWorkflow, SignupEnrichmentRecheckWorkflow],
                activities=[enrich_signup_organization_activity],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                # Skipped time would retire the first recheck child before the second dispatch
                # reaches its own child start, which is the collision under test.
                with env.auto_time_skipping_disabled():
                    results = []
                    for _ in range(2):
                        parent = await env.client.start_workflow(
                            SignupEnrichmentWorkflow.run,
                            _INPUTS,
                            id=f"signup-enrichment-{uuid.uuid4()}",
                            task_queue=_TASK_QUEUE,
                        )
                        results.append(await parent.result())
                    second_types = _event_types(await parent.fetch_history())
                    recheck_status = (await env.client.get_workflow_handle(_RECHECK_ID).describe()).status

    assert results == [{"matched": True, "fields_filled": 2}, {"matched": True, "fields_filled": 2}]
    assert EventType.EVENT_TYPE_START_CHILD_WORKFLOW_EXECUTION_FAILED in second_types
    assert recheck_status == WorkflowExecutionStatus.RUNNING
    assert enrich.await_count == 2


async def test_recheck_skips_deleted_organization():
    """The 4h recheck must not enrich or emit for an org deleted during the delay."""
    inputs = SignupEnrichmentInputs(
        organization_id="00000000-0000-0000-0000-00000000dead", distinct_id="d1", domain="gone.dev"
    )
    with (
        patch(f"{_MODULE}.enrich_organization") as enrich_mock,
        patch(f"{_MODULE}.get_regional_ph_client") as client_mock,
        patch("posthog.models.Organization.objects") as org_objects,
    ):
        org_objects.filter.return_value.exists.return_value = False
        result = await enrich_signup_organization_activity(inputs, is_recheck=True)
    assert result["org_deleted"] is True
    assert result["matched"] is False
    enrich_mock.assert_not_called()
    client_mock.assert_not_called()


async def test_history_recorded_before_the_recheck_child_still_replays():
    history = WorkflowHistory.from_json(
        "signup-enrichment-org-1", await asyncio.to_thread(_PRE_CHILD_HISTORY.read_text)
    )

    await Replayer(
        workflows=[SignupEnrichmentWorkflow, SignupEnrichmentRecheckWorkflow],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ).replay_workflow(history)
