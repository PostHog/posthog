import pytest
from unittest.mock import patch

from asgiref.sync import sync_to_async
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

from posthog.models.scoping import team_scope

from products.pulse.backend.generation.schemas import BriefOut, BriefSectionOut, OpportunityOut
from products.pulse.backend.models import Opportunity, ProductBrief
from products.pulse.backend.sources.base import SourceItem
from products.pulse.backend.temporal.activities import (
    GenerateBriefWorkflowInputs,
    SynthesizeActivityInputs,
    gather_brief_inputs_activity,
    synthesize_brief_activity,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


class _StubSource:
    name = "stub"

    def has_data(self, team, config) -> bool:
        return True

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
    with patch("products.pulse.backend.temporal.activities.synthesize_brief", return_value=_confident_out()):
        status = await env.run(
            synthesize_brief_activity,
            SynthesizeActivityInputs(
                team_id=team.pk, brief_id=str(brief.id), brief_config_id=None, period_days=7, items=[]
            ),
        )
    assert status == ProductBrief.Status.READY
    reloaded = await _reload_brief(brief.id)
    assert reloaded.status == ProductBrief.Status.READY
    assert await _opportunity_count(team) == 1


async def test_synthesize_activity_marks_failed_on_error(team, user) -> None:
    brief = await _create_brief(team, user)
    env = ActivityEnvironment()
    with patch("products.pulse.backend.temporal.activities.synthesize_brief", side_effect=RuntimeError("llm exploded")):
        with pytest.raises(RuntimeError):
            await env.run(
                synthesize_brief_activity,
                SynthesizeActivityInputs(
                    team_id=team.pk, brief_id=str(brief.id), brief_config_id=None, period_days=7, items=[]
                ),
            )
    reloaded = await _reload_brief(brief.id)
    assert reloaded.status == ProductBrief.Status.FAILED
    assert "llm exploded" in (reloaded.error or "")
