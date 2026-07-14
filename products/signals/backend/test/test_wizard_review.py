import random

import pytest
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from asgiref.sync import sync_to_async
from temporalio.testing import ActivityEnvironment

from posthog.models import EventDefinition, Organization, Team

from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.signals.backend.contracts import SIGNAL_VARIANT_LOOKUP
from products.signals.backend.models import SignalReport
from products.signals.backend.temporal.wizard_review import (
    MAX_REVIEW_SIGNALS,
    ComposeSignalsInputs,
    EmitSignalsInputs,
    ReviewSignalDraft,
    SetupGap,
    SetupReviewIntel,
    WizardReviewInputs,
    collect_setup_review_intel_activity,
    compose_review_signals_activity,
    emit_review_signals_activity,
)

REPO = "acme/webapp"


@pytest_asyncio.fixture
async def aorganization():
    organization = await sync_to_async(Organization.objects.create)(
        name=f"WizardReviewTestOrg-{random.randint(1, 99999)}"
    )
    yield organization
    await sync_to_async(organization.delete)()


@pytest_asyncio.fixture
async def ateam(aorganization):
    team = await sync_to_async(Team.objects.create)(
        organization=aorganization,
        name=f"WizardReviewTestTeam-{random.randint(1, 99999)}",
    )
    yield team
    await sync_to_async(team.delete)()


def _fully_set_up(team: Team) -> None:
    EventDefinition.objects.create(team=team, name="user signed up")
    EventDefinition.objects.create(team=team, name="$exception")
    FeatureFlag.objects.create(team=team, key="rollout", active=True, deleted=False)
    team.has_completed_onboarding_for = {"logs": True}
    team.save()


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_collect_intel_finds_all_gaps_on_bare_team(ateam):
    await sync_to_async(EventDefinition.objects.create)(team=ateam, name="$pageview")

    intel: SetupReviewIntel = await ActivityEnvironment().run(
        collect_setup_review_intel_activity, WizardReviewInputs(team_id=ateam.id, repository=REPO)
    )

    assert sorted(gap.category for gap in intel.gaps) == sorted(["events", "feature_flags", "error_tracking", "logs"])
    assert intel.event_names == ["$pageview"]


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_collect_intel_empty_on_fully_set_up_team(ateam):
    await sync_to_async(_fully_set_up)(ateam)

    intel: SetupReviewIntel = await ActivityEnvironment().run(
        collect_setup_review_intel_activity, WizardReviewInputs(team_id=ateam.id, repository=REPO)
    )

    assert intel.gaps == []


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_collect_intel_skips_already_reviewed_team(ateam):
    await sync_to_async(SignalReport.objects.create)(
        team=ateam, status=SignalReport.Status.POTENTIAL, billing_exempt=True
    )

    intel: SetupReviewIntel = await ActivityEnvironment().run(
        collect_setup_review_intel_activity, WizardReviewInputs(team_id=ateam.id, repository=REPO)
    )

    assert intel.gaps == []


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_compose_falls_back_and_caps_on_llm_failure(ateam):
    intel = SetupReviewIntel(
        gaps=[
            SetupGap(category="logs", evidence="e"),
            SetupGap(category="events", evidence="e"),
            SetupGap(category="feature_flags", evidence="e"),
            SetupGap(category="error_tracking", evidence="e"),
        ],
        team_name="acme",
        event_names=[],
        planned_events=[],
    )

    with patch("products.signals.backend.temporal.llm.call_llm", side_effect=RuntimeError("llm down")):
        drafts = await ActivityEnvironment().run(
            compose_review_signals_activity,
            ComposeSignalsInputs(team_id=ateam.id, repository=REPO, intel=intel),
        )

    # Fallback keeps the priority order and never exceeds the cap, so a detected gap still ships.
    assert [d.category for d in drafts] == ["events", "error_tracking", "feature_flags"]
    assert len(drafts) == MAX_REVIEW_SIGNALS
    assert all(REPO in d.description for d in drafts)


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_emit_sends_each_draft_through_emit_signal(ateam):
    drafts = [
        ReviewSignalDraft(category="events", description="d1", remediation_human="h1", remediation_agent="a1"),
        ReviewSignalDraft(category="logs", description="d2", remediation_human="h2", remediation_agent="a2"),
    ]

    with patch("products.signals.backend.facade.api.emit_signal", new_callable=AsyncMock) as mock_emit:
        emitted = await ActivityEnvironment().run(
            emit_review_signals_activity,
            EmitSignalsInputs(team_id=ateam.id, repository=REPO, drafts=drafts),
        )

    assert emitted == 2
    assert mock_emit.await_count == 2
    for call, draft in zip(mock_emit.await_args_list, drafts):
        kwargs = call.kwargs
        assert kwargs["source_product"] == "wizard"
        assert kwargs["source_type"] == "setup_review"
        # Weight 1.0 is what makes the report promote immediately.
        assert kwargs["weight"] == 1.0
        assert kwargs["extra"] == {"repository": REPO, "category": draft.category}
        assert kwargs["remediation"].agent == draft.remediation_agent


@pytest.mark.django_db
def test_wizard_signal_payload_validates_against_contract():
    # emit_signal validates payloads via SIGNAL_VARIANT_LOOKUP; an unregistered variant would
    # make every wizard emit raise "Unknown signal type" at runtime.
    variant = SIGNAL_VARIANT_LOOKUP[("wizard", "setup_review")]
    variant.model_validate(
        {
            "source_product": "wizard",
            "source_type": "setup_review",
            "source_id": "wizard-setup-review:1:events",
            "description": "d",
            "weight": 1.0,
            "extra": {"repository": REPO, "category": "events"},
        }
    )
