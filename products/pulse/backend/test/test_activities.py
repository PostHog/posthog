import uuid
import dataclasses

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.conf import settings

from asgiref.sync import sync_to_async
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.models.scoping import team_scope

from products.pulse.backend.generation.accountability import OpportunityStatusLine
from products.pulse.backend.generation.explain import CausalCandidate
from products.pulse.backend.generation.goal import GoalStatus
from products.pulse.backend.generation.schemas import BriefOut, BriefSectionOut, OpportunityOut
from products.pulse.backend.models import BriefConfig, Opportunity, ProductBrief
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
def _create_brief(team, user, config: BriefConfig | None = None) -> ProductBrief:
    with team_scope(team.pk, canonical=True):
        return ProductBrief.objects.create(
            team=team, created_by=user, config=config, trigger=ProductBrief.Trigger.ON_DEMAND, period_days=7
        )


@sync_to_async
def _create_config(team, goal: str) -> BriefConfig:
    with team_scope(team.pk, canonical=True):
        return BriefConfig.objects.create(team=team, name="Focus", goal=goal)


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


_CANDIDATE = CausalCandidate(
    kind="flag", ref="flag:123", label="checkout-v2", happened_at="2026-07-01", detail="Feature flag created."
)

_STATUS_LINE = OpportunityStatusLine(
    opportunity_id="11111111-1111-1111-1111-111111111111",
    kind="build",
    status="acted",
    title="Recover the signup drop",
    age_days=21,
    baseline_summary="70.0/day avg",
    current_summary="100.0/day avg",
    delta_pct=42.9,
)


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


async def test_gather_activity_raises_when_all_sources_fail(team) -> None:
    await _set_ai_consent(team, True)
    env = ActivityEnvironment()
    with patch(
        "products.pulse.backend.temporal.activities.get_sources", return_value=[_RaisingSource(), _RaisingSource()]
    ):
        with pytest.raises(ApplicationError) as exc_info:
            await env.run(
                gather_brief_inputs_activity,
                GenerateBriefWorkflowInputs(team_id=team.pk, brief_id="unused", brief_config_id=None, period_days=7),
            )
    assert exc_info.value.non_retryable is False


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


@pytest.mark.parametrize("kind,expected_candidates", [("movement", [_CANDIDATE]), ("context", [])])
async def test_synthesize_activity_collects_candidates_only_for_movements(
    team, user, kind: SourceItemKind, expected_candidates: list[CausalCandidate]
) -> None:
    brief = await _create_brief(team, user)
    env = ActivityEnvironment()
    item = SourceItem(source="stub", kind=kind, title="t", description="d", fingerprint_hint="abc:0")
    with (
        patch(
            "products.pulse.backend.temporal.activities.synthesize_brief", return_value=_confident_out()
        ) as synth_mock,
        patch(
            "products.pulse.backend.temporal.activities.collect_causal_candidates", return_value=[_CANDIDATE]
        ) as collect_mock,
        patch("products.pulse.backend.temporal.activities.emit_signal", new_callable=AsyncMock),
    ):
        status = await env.run(
            synthesize_brief_activity,
            SynthesizeActivityInputs(team_id=team.pk, brief_id=str(brief.id), items=[dataclasses.asdict(item)]),
        )
    assert status == ProductBrief.Status.READY
    kwargs = synth_mock.call_args.kwargs
    assert kwargs["items"] == [item]
    assert kwargs["candidates"] == expected_candidates
    assert collect_mock.called == bool(expected_candidates)


async def test_synthesize_activity_reports_brief_generated(team, user) -> None:
    brief = await _create_brief(team, user)
    env = ActivityEnvironment()
    scoped_capture = MagicMock()
    capture_mock = scoped_capture.return_value.__enter__.return_value
    with (
        patch("products.pulse.backend.temporal.activities.synthesize_brief", return_value=_confident_out()),
        patch("products.pulse.backend.temporal.activities.emit_signal", new_callable=AsyncMock),
        patch("products.pulse.backend.temporal.activities.ph_scoped_capture", scoped_capture),
    ):
        await env.run(
            synthesize_brief_activity,
            SynthesizeActivityInputs(team_id=team.pk, brief_id=str(brief.id), items=[]),
        )
    capture_mock.assert_called_once()
    kwargs = capture_mock.call_args.kwargs
    assert kwargs["event"] == "product_brief_generated"
    assert kwargs["properties"]["status"] == ProductBrief.Status.READY
    assert kwargs["properties"]["new_opportunity_count"] == 1
    assert kwargs["properties"]["has_config"] is False


@pytest.mark.parametrize("kind", ["movement", "context"])
async def test_synthesize_activity_collects_accountability_for_any_item_kind(team, user, kind: SourceItemKind) -> None:
    brief = await _create_brief(team, user)
    env = ActivityEnvironment()
    item = SourceItem(source="stub", kind=kind, title="t", description="d", fingerprint_hint="abc:0")
    with (
        patch(
            "products.pulse.backend.temporal.activities.synthesize_brief", return_value=_confident_out()
        ) as synth_mock,
        patch(
            "products.pulse.backend.temporal.activities.collect_accountability", return_value=[_STATUS_LINE]
        ) as collect_mock,
        patch("products.pulse.backend.temporal.activities.emit_signal", new_callable=AsyncMock),
    ):
        status = await env.run(
            synthesize_brief_activity,
            SynthesizeActivityInputs(team_id=team.pk, brief_id=str(brief.id), items=[dataclasses.asdict(item)]),
        )
    assert status == ProductBrief.Status.READY
    assert synth_mock.call_args.kwargs["status_lines"] == [_STATUS_LINE]
    collect_mock.assert_called_once()


_GOAL_STATUS = GoalStatus(
    goal="Increase subscription usage",
    metric_label="Subscriptions created",
    current_rate="100.0/day avg",
    previous_rate="70.0/day avg",
    delta_pct=42.9,
)


@pytest.mark.parametrize("goal,expect_collected", [("Increase subscription usage", True), ("", False), ("   ", False)])
async def test_synthesize_activity_collects_goal_status_only_for_configs_with_a_goal(
    team, user, goal: str, expect_collected: bool
) -> None:
    config = await _create_config(team, goal=goal)
    brief = await _create_brief(team, user, config=config)
    env = ActivityEnvironment()
    item = SourceItem(source="stub", kind="movement", title="t", description="d", fingerprint_hint="abc:0")
    with (
        patch(
            "products.pulse.backend.temporal.activities.synthesize_brief", return_value=_confident_out()
        ) as synth_mock,
        patch(
            "products.pulse.backend.temporal.activities.collect_goal_status", return_value=_GOAL_STATUS
        ) as collect_mock,
        patch("products.pulse.backend.temporal.activities.emit_signal", new_callable=AsyncMock),
    ):
        status = await env.run(
            synthesize_brief_activity,
            SynthesizeActivityInputs(team_id=team.pk, brief_id=str(brief.id), items=[dataclasses.asdict(item)]),
        )
    assert status == ProductBrief.Status.READY
    assert synth_mock.call_args.kwargs["goal_status"] == (_GOAL_STATUS if expect_collected else None)
    assert collect_mock.called is expect_collected


async def test_synthesize_activity_skips_goal_status_without_a_config(team, user) -> None:
    brief = await _create_brief(team, user)
    env = ActivityEnvironment()
    item = SourceItem(source="stub", kind="movement", title="t", description="d", fingerprint_hint="abc:0")
    with (
        patch(
            "products.pulse.backend.temporal.activities.synthesize_brief", return_value=_confident_out()
        ) as synth_mock,
        patch("products.pulse.backend.temporal.activities.collect_goal_status") as collect_mock,
        patch("products.pulse.backend.temporal.activities.emit_signal", new_callable=AsyncMock),
    ):
        await env.run(
            synthesize_brief_activity,
            SynthesizeActivityInputs(team_id=team.pk, brief_id=str(brief.id), items=[dataclasses.asdict(item)]),
        )
    assert synth_mock.call_args.kwargs["goal_status"] is None
    collect_mock.assert_not_called()


async def test_synthesize_activity_survives_goal_status_collection_failure(team, user) -> None:
    config = await _create_config(team, goal="Increase subscription usage")
    brief = await _create_brief(team, user, config=config)
    env = ActivityEnvironment()
    item = SourceItem(source="stub", kind="movement", title="t", description="d", fingerprint_hint="abc:0")
    with (
        patch(
            "products.pulse.backend.temporal.activities.synthesize_brief", return_value=_confident_out()
        ) as synth_mock,
        patch(
            "products.pulse.backend.temporal.activities.collect_goal_status",
            side_effect=RuntimeError("goal read exploded"),
        ),
        patch("products.pulse.backend.temporal.activities.emit_signal", new_callable=AsyncMock),
    ):
        status = await env.run(
            synthesize_brief_activity,
            SynthesizeActivityInputs(team_id=team.pk, brief_id=str(brief.id), items=[dataclasses.asdict(item)]),
        )
    assert status == ProductBrief.Status.READY
    assert synth_mock.call_args.kwargs["goal_status"] is None


async def test_synthesize_activity_survives_accountability_collection_failure(team, user) -> None:
    brief = await _create_brief(team, user)
    env = ActivityEnvironment()
    item = SourceItem(source="stub", kind="context", title="t", description="d", fingerprint_hint="abc:0")
    with (
        patch(
            "products.pulse.backend.temporal.activities.synthesize_brief", return_value=_confident_out()
        ) as synth_mock,
        patch(
            "products.pulse.backend.temporal.activities.collect_accountability",
            side_effect=RuntimeError("re-score exploded"),
        ),
        patch("products.pulse.backend.temporal.activities.emit_signal", new_callable=AsyncMock),
    ):
        status = await env.run(
            synthesize_brief_activity,
            SynthesizeActivityInputs(team_id=team.pk, brief_id=str(brief.id), items=[dataclasses.asdict(item)]),
        )
    assert status == ProductBrief.Status.READY
    assert synth_mock.call_args.kwargs["status_lines"] == []


async def test_synthesize_activity_survives_candidate_collection_failure(team, user) -> None:
    brief = await _create_brief(team, user)
    env = ActivityEnvironment()
    item = SourceItem(source="stub", kind="movement", title="t", description="d", fingerprint_hint="abc:0")
    with (
        patch(
            "products.pulse.backend.temporal.activities.synthesize_brief", return_value=_confident_out()
        ) as synth_mock,
        patch(
            "products.pulse.backend.temporal.activities.collect_causal_candidates",
            side_effect=RuntimeError("collector exploded"),
        ),
        patch("products.pulse.backend.temporal.activities.emit_signal", new_callable=AsyncMock),
    ):
        status = await env.run(
            synthesize_brief_activity,
            SynthesizeActivityInputs(team_id=team.pk, brief_id=str(brief.id), items=[dataclasses.asdict(item)]),
        )
    assert status == ProductBrief.Status.READY
    assert synth_mock.call_args.kwargs["candidates"] == []


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
