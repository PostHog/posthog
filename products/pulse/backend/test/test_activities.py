import uuid

import pytest
from unittest.mock import AsyncMock, patch

from django.conf import settings

from asgiref.sync import sync_to_async
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models.scoping import team_scope

from products.pulse.backend.generation.schemas import BriefOut, BriefSectionOut, OpportunityOut
from products.pulse.backend.models import Opportunity, ProductBrief
from products.pulse.backend.sources.base import SourceItem, SourceItemKind
from products.pulse.backend.temporal.activities import (
    MAX_ITEMS,
    gather_brief_inputs_activity,
    synthesize_brief_activity,
)
from products.pulse.backend.temporal.inputs import GenerateBriefWorkflowInputs, SynthesizeActivityInputs
from products.pulse.backend.temporal.registry import ACTIVITIES
from products.pulse.backend.temporal.workflow import GenerateProductBriefWorkflow

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


class _StubSource:
    name = "stub"

    def gather(self, team, config, period_days) -> list[SourceItem]:
        return [
            SourceItem(
                source="stub",
                kind="movement",
                title="Pageviews dropped 30%",
                description="d",
                numbers={"pct_change": -30.0},
                evidence=[{"type": "insight", "ref": "abc", "label": "Pageviews"}],
                fingerprint_hint="abc:0",
            )
        ]


class _RaisingSource:
    name = "raising"

    def gather(self, team, config, period_days) -> list[SourceItem]:
        raise RuntimeError("source exploded")


class _EmptySource:
    name = "empty"

    def gather(self, team, config, period_days) -> list[SourceItem]:
        return []


class _ManyItemsSource:
    def __init__(self, kind: SourceItemKind, count: int) -> None:
        self.name = f"many_{kind}"
        self._kind: SourceItemKind = kind
        self._count = count

    def gather(self, team, config, period_days) -> list[SourceItem]:
        return [
            SourceItem(
                source=self.name,
                kind=self._kind,
                title=f"{self._kind} {i}",
                description="d",
                fingerprint_hint=f"{self._kind}:{i}",
            )
            for i in range(self._count)
        ]


@sync_to_async
def _set_ai_consent(team, approved: bool) -> None:
    team.organization.is_ai_data_processing_approved = approved
    team.organization.save()


@sync_to_async
def _create_brief(team, user) -> ProductBrief:
    with team_scope(team.pk, canonical=True):
        return ProductBrief.objects.create(
            team=team, created_by=user, trigger=ProductBrief.Trigger.ON_DEMAND, period_days=7
        )


@sync_to_async
def _reload_brief(brief_id) -> ProductBrief:
    return ProductBrief.objects.unscoped().get(id=brief_id)


@sync_to_async
def _opportunity_count(team) -> int:
    return Opportunity.objects.for_team(team.pk).count()


@sync_to_async
def _get_opportunity(team) -> Opportunity:
    return Opportunity.objects.for_team(team.pk).get()


@sync_to_async
def _create_opportunity(team, fingerprint: str) -> Opportunity:
    with team_scope(team.pk, canonical=True):
        return Opportunity.objects.create(team=team, kind="build", title="t", summary="s", fingerprint=fingerprint)


def _confident_out() -> BriefOut:
    return BriefOut(
        sections=[
            BriefSectionOut(kind="what_happened", title="t", markdown="m", citations=["insight:abc"], confidence=0.9)
        ],
        opportunities=[
            OpportunityOut(
                kind="build",
                title="t",
                summary="s",
                suggested_action="a",
                evidence_refs=["insight:abc"],
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
            GenerateBriefWorkflowInputs(team_id=team.pk, brief_id="unused", brief_config_id=None, period_days=7),
        )
    assert len(items) == 1
    assert items[0]["fingerprint_hint"] == "abc:0"


async def test_gather_activity_survives_one_broken_source(team) -> None:
    await _set_ai_consent(team, True)
    env = ActivityEnvironment()
    with patch(
        "products.pulse.backend.temporal.activities.get_sources", return_value=[_RaisingSource(), _StubSource()]
    ):
        items = await env.run(
            gather_brief_inputs_activity,
            GenerateBriefWorkflowInputs(team_id=team.pk, brief_id="unused", brief_config_id=None, period_days=7),
        )
    assert [item["fingerprint_hint"] for item in items] == ["abc:0"]


@pytest.mark.parametrize(
    "sources,expect_raise",
    [
        ([_RaisingSource(), _EmptySource()], False),  # partial failure in a quiet week -> empty brief, no raise
        ([_RaisingSource(), _RaisingSource()], True),  # every source failed -> retryable error
    ],
)
async def test_gather_activity_failed_sources(team, sources, expect_raise) -> None:
    await _set_ai_consent(team, True)
    env = ActivityEnvironment()
    inputs = GenerateBriefWorkflowInputs(team_id=team.pk, brief_id="unused", brief_config_id=None, period_days=7)
    with patch("products.pulse.backend.temporal.activities.get_sources", return_value=sources):
        if expect_raise:
            with pytest.raises(ApplicationError) as exc_info:
                await env.run(gather_brief_inputs_activity, inputs)
            assert exc_info.value.non_retryable is False
        else:
            assert await env.run(gather_brief_inputs_activity, inputs) == []


async def test_gather_activity_cap_keeps_high_priority_kinds(team) -> None:
    await _set_ai_consent(team, True)
    env = ActivityEnvironment()
    health_count = 15
    sources = [_ManyItemsSource("context", 45), _ManyItemsSource("health", health_count)]
    with patch("products.pulse.backend.temporal.activities.get_sources", return_value=sources):
        items = await env.run(
            gather_brief_inputs_activity,
            GenerateBriefWorkflowInputs(team_id=team.pk, brief_id="unused", brief_config_id=None, period_days=7),
        )
    assert len(items) == MAX_ITEMS
    health_hints = [item["fingerprint_hint"] for item in items if item["kind"] == "health"]
    assert health_hints == [f"health:{i}" for i in range(health_count)]


async def test_gather_activity_refuses_without_ai_consent(team) -> None:
    await _set_ai_consent(team, False)
    env = ActivityEnvironment()
    with pytest.raises(ApplicationError) as exc_info:
        await env.run(
            gather_brief_inputs_activity,
            GenerateBriefWorkflowInputs(team_id=team.pk, brief_id="unused", brief_config_id=None, period_days=7),
        )
    assert exc_info.value.non_retryable is True


async def test_synthesize_activity_marks_ready(team, user) -> None:
    brief = await _create_brief(team, user)
    env = ActivityEnvironment()
    with (
        patch("products.pulse.backend.temporal.activities.synthesize_brief", return_value=_confident_out()),
        patch("products.pulse.backend.temporal.activities.emit_signal", new_callable=AsyncMock),
    ):
        status = await env.run(
            synthesize_brief_activity,
            SynthesizeActivityInputs(team_id=team.pk, brief_id=str(brief.id), items=[]),
        )
    assert status == ProductBrief.Status.READY
    reloaded = await _reload_brief(brief.id)
    assert reloaded.status == ProductBrief.Status.READY
    assert await _opportunity_count(team) == 1


async def test_synthesize_activity_emits_signal_per_new_opportunity(team, user) -> None:
    brief = await _create_brief(team, user)
    env = ActivityEnvironment()
    with (
        patch("products.pulse.backend.temporal.activities.synthesize_brief", return_value=_confident_out()),
        patch("products.pulse.backend.temporal.activities.emit_signal", new_callable=AsyncMock) as emit_mock,
    ):
        await env.run(
            synthesize_brief_activity,
            SynthesizeActivityInputs(team_id=team.pk, brief_id=str(brief.id), items=[]),
        )
    opportunity = await _get_opportunity(team)
    assert emit_mock.await_count == 1
    kwargs = emit_mock.await_args.kwargs
    assert kwargs["source_product"] == "pulse"
    assert kwargs["source_type"] == "opportunity_build"
    assert kwargs["source_id"] == str(opportunity.id)
    assert kwargs["description"] == "t\n\ns"
    assert kwargs["weight"] == 0.9
    assert kwargs["extra"] == {
        "brief_id": str(brief.id),
        "kind": "build",
        "evidence": [{"type": "insight", "ref": "abc", "label": ""}],
    }


async def test_synthesize_activity_does_not_emit_for_deduped_opportunity(team, user) -> None:
    brief = await _create_brief(team, user)
    await _create_opportunity(team, fingerprint="build:abc:0")
    env = ActivityEnvironment()
    with (
        patch("products.pulse.backend.temporal.activities.synthesize_brief", return_value=_confident_out()),
        patch("products.pulse.backend.temporal.activities.emit_signal", new_callable=AsyncMock) as emit_mock,
    ):
        status = await env.run(
            synthesize_brief_activity,
            SynthesizeActivityInputs(team_id=team.pk, brief_id=str(brief.id), items=[]),
        )
    assert status == ProductBrief.Status.READY
    emit_mock.assert_not_awaited()


async def test_synthesize_activity_survives_emit_failure(team, user) -> None:
    brief = await _create_brief(team, user)
    env = ActivityEnvironment()
    with (
        patch("products.pulse.backend.temporal.activities.synthesize_brief", return_value=_confident_out()),
        patch(
            "products.pulse.backend.temporal.activities.emit_signal",
            new_callable=AsyncMock,
            side_effect=RuntimeError("signals down"),
        ),
    ):
        status = await env.run(
            synthesize_brief_activity,
            SynthesizeActivityInputs(team_id=team.pk, brief_id=str(brief.id), items=[]),
        )
    assert status == ProductBrief.Status.READY
    reloaded = await _reload_brief(brief.id)
    assert reloaded.status == ProductBrief.Status.READY


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
