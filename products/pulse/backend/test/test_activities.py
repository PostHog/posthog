import uuid
import datetime as dt

import pytest
from unittest.mock import patch

from django.conf import settings

from asgiref.sync import sync_to_async
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models.scoping import team_scope
from posthog.slo.types import SloArea, SloConfig, SloOperation

from products.pulse.backend.generation.schemas import BriefOut, BriefSectionOut, OpportunityOut
from products.pulse.backend.models import Opportunity, ProductBrief
from products.pulse.backend.sources.base import SourceItem
from products.pulse.backend.temporal.activities import (
    gather_brief_inputs_activity,
    resolve_period,
    synthesize_brief_activity,
)
from products.pulse.backend.temporal.inputs import GenerateBriefWorkflowInputs, SynthesizeActivityInputs
from products.pulse.backend.temporal.registry import ACTIVITIES
from products.pulse.backend.temporal.workflow import GenerateProductBriefWorkflow

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


class _StubSource:
    name = "stub"

    def gather(self, team, config, lookback_days) -> list[SourceItem]:
        return [
            SourceItem(
                source="stub",
                kind="movement",
                title="Pageviews dropped 30%",
                description="d",
                metrics={"pct_change": -30.0},
                evidence=[{"type": "insight", "ref": "abc", "label": "Pageviews", "url": "/project/1/insights/abc"}],
                fingerprint_hint="abc:0",
            )
        ]


@sync_to_async
def _set_ai_consent(team, approved: bool) -> None:
    team.organization.is_ai_data_processing_approved = approved
    team.organization.save()


@sync_to_async
def _create_brief(team, user) -> ProductBrief:
    with team_scope(team.pk, canonical=True):
        return ProductBrief.objects.create(team=team, created_by=user, trigger=ProductBrief.Trigger.ON_DEMAND)


@sync_to_async
def _create_userless_brief(team) -> ProductBrief:
    with team_scope(team.pk, canonical=True):
        return ProductBrief.objects.create(team=team, created_by=None, trigger=ProductBrief.Trigger.SCHEDULED)


@sync_to_async
def _reload_brief(brief_id) -> ProductBrief:
    return ProductBrief.objects.unscoped().get(id=brief_id)


@sync_to_async
def _opportunity_count(team) -> int:
    return Opportunity.objects.for_team(team.pk).count()


def _confident_out() -> BriefOut:
    return BriefOut(
        sections=[BriefSectionOut(kind="what_happened", title="t", markdown="m", citations=["c1"], confidence=0.9)],
        opportunities=[
            OpportunityOut(
                kind="build",
                title="t",
                summary="s",
                suggested_action="a",
                evidence_refs=["c1"],
                fingerprint_hint="abc:0",
                confidence=0.9,
            )
        ],
    )


async def test_gather_activity_returns_serialized_items(team) -> None:
    await _set_ai_consent(team, True)
    env = ActivityEnvironment()
    with patch("products.pulse.backend.temporal.activities.get_sources", return_value=[_StubSource()]):
        items = await env.run(
            gather_brief_inputs_activity,
            GenerateBriefWorkflowInputs(team_id=team.pk, brief_id="unused", brief_config_id=None),
        )
    assert len(items) == 1
    assert items[0]["fingerprint_hint"] == "abc:0"


async def test_gather_activity_refuses_without_ai_consent(team) -> None:
    await _set_ai_consent(team, False)
    env = ActivityEnvironment()
    with pytest.raises(ApplicationError) as exc_info:
        await env.run(
            gather_brief_inputs_activity,
            GenerateBriefWorkflowInputs(team_id=team.pk, brief_id="unused", brief_config_id=None),
        )
    assert exc_info.value.non_retryable is True


async def test_synthesize_activity_marks_ready(team, user) -> None:
    brief = await _create_brief(team, user)
    env = ActivityEnvironment()
    with patch("products.pulse.backend.temporal.activities.synthesize_brief", return_value=_confident_out()):
        status = await env.run(
            synthesize_brief_activity,
            SynthesizeActivityInputs(team_id=team.pk, brief_id=str(brief.id), items=[]),
        )
    assert status == ProductBrief.Status.READY
    reloaded = await _reload_brief(brief.id)
    assert reloaded.status == ProductBrief.Status.READY
    assert await _opportunity_count(team) == 1


async def test_synthesize_activity_without_creating_user_raises(team) -> None:
    # No creating user means no billing/quota attribution for the LLM call — fail non-retryably.
    brief = await _create_userless_brief(team)
    env = ActivityEnvironment()
    with pytest.raises(ApplicationError) as exc_info:
        await env.run(
            synthesize_brief_activity,
            SynthesizeActivityInputs(team_id=team.pk, brief_id=str(brief.id), items=[]),
        )
    assert exc_info.value.non_retryable is True


def test_workflow_inputs_carry_slo_config() -> None:
    # The workflow input must be able to carry an SloConfig for the SloInterceptor to read at start;
    # a plain input (no SLO) stays valid too.
    slo = SloConfig(
        operation=SloOperation.PULSE_BRIEF_GENERATION,
        area=SloArea.ANALYTIC_PLATFORM,
        team_id=1,
        resource_id="brief-1",
        distinct_id="user-1",
    )
    inputs = GenerateBriefWorkflowInputs(team_id=1, brief_id="brief-1", slo=slo)
    assert inputs.slo is slo
    assert inputs.slo.operation == SloOperation.PULSE_BRIEF_GENERATION
    assert GenerateBriefWorkflowInputs(team_id=1, brief_id="brief-1").slo is None


def test_resolve_period_since_last_run_vs_last_n_days() -> None:
    now = dt.datetime(2026, 1, 20, tzinfo=dt.UTC)
    # last_n_days uses the requested day count regardless of prior runs.
    fixed = resolve_period({"type": "last_n_days", "days": 14}, now, last_run=dt.datetime(2026, 1, 18, tzinfo=dt.UTC))
    assert fixed.lookback_days == 14
    assert fixed.start_date == dt.date(2026, 1, 6)
    assert fixed.end_date == dt.date(2026, 1, 20)
    # since_last_run measures the gap to the last ready brief.
    since = resolve_period({"type": "since_last_run"}, now, last_run=dt.datetime(2026, 1, 15, tzinfo=dt.UTC))
    assert since.lookback_days == 5
    # since_last_run with no prior run falls back to the default window.
    first = resolve_period({"type": "since_last_run"}, now, last_run=None)
    assert first.lookback_days == 7


async def test_workflow_marks_brief_failed_when_gather_fails(team, user) -> None:
    await _set_ai_consent(team, False)  # gather refuses (non-retryable) — the failure path under test
    brief = await _create_brief(team, user)
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            workflows=[GenerateProductBriefWorkflow],
            activities=ACTIVITIES,
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await env.client.execute_workflow(
                    GenerateProductBriefWorkflow.run,
                    GenerateBriefWorkflowInputs(team_id=team.pk, brief_id=str(brief.id)),
                    id=f"pulse-brief-test-{uuid.uuid4()}",
                    task_queue=settings.TEMPORAL_TASK_QUEUE,
                )
    reloaded = await _reload_brief(brief.id)
    assert reloaded.status == ProductBrief.Status.FAILED
    assert "AI data processing not approved" in (reloaded.error or "")
