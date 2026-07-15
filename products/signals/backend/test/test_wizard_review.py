import random

import pytest
from unittest.mock import AsyncMock, patch

import pytest_asyncio
from asgiref.sync import sync_to_async
from temporalio.testing import ActivityEnvironment

from posthog.models import Organization, Team

from products.signals.backend.contracts import SIGNAL_VARIANT_LOOKUP
from products.signals.backend.models import SignalReport
from products.signals.backend.temporal.wizard_review import (
    MAX_REVIEW_SIGNALS,
    AuditCheck,
    EmitSignalsInputs,
    ReviewSignalDraft,
    WizardReviewInputs,
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


def _check(check_id: str, status: str, label: str | None = None) -> AuditCheck:
    return AuditCheck(id=check_id, label=label or f"Label for {check_id}", status=status, details="d")


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_compose_falls_back_to_verbatim_drafts_by_severity(ateam):
    checks = [
        _check("capture-uses-proxy", "suggestion"),
        _check("sdk-up-to-date", "pass"),
        _check("identify-stable-distinct-id", "error"),
        _check("init-correct", "pending"),
        _check("capture-growth-events", "warning"),
        _check("identify-not-late", "error"),
    ]

    with patch("products.signals.backend.temporal.llm.call_llm", side_effect=RuntimeError("llm down")):
        drafts = await ActivityEnvironment().run(
            compose_review_signals_activity,
            WizardReviewInputs(team_id=ateam.id, repository=REPO, checks=checks),
        )

    # pass/pending rows are not findings; the fallback ranks errors first and caps the count.
    assert len(drafts) == MAX_REVIEW_SIGNALS
    assert [d.category for d in drafts] == ["identify-stable-distinct-id", "identify-not-late", "capture-growth-events"]
    assert all(REPO in d.description for d in drafts)


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_compose_empty_when_all_checks_pass(ateam):
    drafts = await ActivityEnvironment().run(
        compose_review_signals_activity,
        WizardReviewInputs(team_id=ateam.id, repository=REPO, checks=[_check("init-correct", "pass")]),
    )

    assert drafts == []


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_compose_skips_already_reviewed_team(ateam):
    await sync_to_async(SignalReport.objects.create)(
        team=ateam,
        status=SignalReport.Status.POTENTIAL,
        billing_exempt_reason=SignalReport.BillingExemptReason.POSTHOG_ONBOARDING,
    )

    drafts = await ActivityEnvironment().run(
        compose_review_signals_activity,
        WizardReviewInputs(team_id=ateam.id, repository=REPO, checks=[_check("init-correct", "error")]),
    )

    assert drafts == []


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_emit_sends_each_draft_through_emit_signal(ateam):
    drafts = [
        ReviewSignalDraft(
            category="identify-stable-distinct-id", description="d1", remediation_human="h1", remediation_agent="a1"
        ),
        ReviewSignalDraft(
            category="capture-growth-events", description="d2", remediation_human="h2", remediation_agent="a2"
        ),
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
            "source_id": "wizard-setup-review:1:identify-stable-distinct-id",
            "description": "d",
            "weight": 1.0,
            "extra": {"repository": REPO, "category": "identify-stable-distinct-id"},
        }
    )
