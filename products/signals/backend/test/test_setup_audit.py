import random

import pytest
from unittest.mock import patch

import pytest_asyncio
from asgiref.sync import sync_to_async
from temporalio.testing import ActivityEnvironment

from posthog.models import EventDefinition, Organization, Team

from products.feature_flags.backend.models.feature_flag import FeatureFlag
from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import SetupProposal
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportTask
from products.signals.backend.temporal.setup_audit import (
    CreateProposalsInputs,
    DetectedGaps,
    PersonalizeInputs,
    ProposalCopy,
    SetupAuditInputs,
    SetupGap,
    create_proposal_reports_activity,
    detect_setup_gaps_activity,
    personalize_proposals_activity,
)

REPO = "acme/webapp"


@pytest_asyncio.fixture
async def aorganization():
    organization = await sync_to_async(Organization.objects.create)(
        name=f"SetupAuditTestOrg-{random.randint(1, 99999)}"
    )
    yield organization
    await sync_to_async(organization.delete)()


@pytest_asyncio.fixture
async def ateam(aorganization):
    team = await sync_to_async(Team.objects.create)(
        organization=aorganization,
        name=f"SetupAuditTestTeam-{random.randint(1, 99999)}",
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
async def test_detect_setup_gaps_finds_all_gaps_on_bare_team(ateam):
    await sync_to_async(EventDefinition.objects.create)(team=ateam, name="$pageview")

    detected: DetectedGaps = await ActivityEnvironment().run(
        detect_setup_gaps_activity, SetupAuditInputs(team_id=ateam.id, repository=REPO)
    )

    assert sorted(gap.category for gap in detected.gaps) == sorted(
        ["events", "feature_flags", "error_tracking", "logs"]
    )
    assert detected.event_names == ["$pageview"]


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_detect_setup_gaps_empty_on_fully_set_up_team(ateam):
    await sync_to_async(_fully_set_up)(ateam)

    detected: DetectedGaps = await ActivityEnvironment().run(
        detect_setup_gaps_activity, SetupAuditInputs(team_id=ateam.id, repository=REPO)
    )

    assert detected.gaps == []


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_detect_setup_gaps_skips_team_with_existing_proposals(ateam):
    def _existing_proposal() -> None:
        report = SignalReport.objects.create(team=ateam, status=SignalReport.Status.READY, title="t", summary="s")
        SignalReportArtefact.append_status(
            team_id=ateam.id,
            report_id=str(report.id),
            content=SetupProposal(category="events", product="product_analytics"),
            attribution=ArtefactAttribution.system(),
            reevaluate_autostart=False,
        )

    await sync_to_async(_existing_proposal)()

    detected: DetectedGaps = await ActivityEnvironment().run(
        detect_setup_gaps_activity, SetupAuditInputs(team_id=ateam.id, repository=REPO)
    )

    assert detected.gaps == []


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_personalize_falls_back_to_template_on_llm_failure(ateam):
    detected = DetectedGaps(
        gaps=[SetupGap(category="events", evidence="e"), SetupGap(category="logs", evidence="e")],
        team_name="acme",
        event_names=[],
    )

    with patch("products.signals.backend.temporal.llm.call_llm", side_effect=RuntimeError("llm down")):
        proposals = await ActivityEnvironment().run(
            personalize_proposals_activity,
            PersonalizeInputs(team_id=ateam.id, repository=REPO, detected=detected),
        )

    assert [p.category for p in proposals] == ["events", "logs"]
    assert all(REPO in p.summary for p in proposals)


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_create_proposal_reports_creates_ready_reports_without_autostart(ateam):
    report_ids = await ActivityEnvironment().run(
        create_proposal_reports_activity,
        CreateProposalsInputs(
            team_id=ateam.id,
            repository=REPO,
            proposals=[
                ProposalCopy(category="error_tracking", title="Set up error tracking", summary="pitch"),
            ],
        ),
    )

    def _verify() -> None:
        assert len(report_ids) == 1
        report = SignalReport.objects.get(id=report_ids[0])
        assert report.team_id == ateam.id
        assert report.status == SignalReport.Status.READY
        assert report.title == "Set up error tracking"
        artefact_types = set(report.artefacts.values_list("type", flat=True))
        assert artefact_types == {
            SignalReportArtefact.ArtefactType.PROPOSAL,
            SignalReportArtefact.ArtefactType.REPO_SELECTION,
        }
        proposal = report.artefacts.get(type=SignalReportArtefact.ArtefactType.PROPOSAL)
        assert '"error_tracking"' in proposal.content
        # Proposals are approval-first: creating them must never start an implementation task.
        assert not SignalReportTask.objects.filter(report_id=report.id).exists()

    await sync_to_async(_verify)()
