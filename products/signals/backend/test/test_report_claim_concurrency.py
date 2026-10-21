from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from unittest.mock import patch

from django.db import connections

from posthog.models import Organization, Team, User

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.assignment_service import (
    AssignmentProposal,
    ReportAssignmentService,
    StaleAssignmentProposal,
)
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportAssignment
from products.signals.backend.report_assignments import ReportClaimConflict, claim_report
from products.signals.backend.report_claims import get_active_claim


@pytest.mark.django_db(transaction=True)
def test_concurrent_claims_have_one_winner() -> None:
    organization = Organization.objects.create(name="Claims test")
    team = Team.objects.create(organization=organization)
    user = User.objects.create(email="claims@example.com")
    report = SignalReport.objects.create(team=team, status="ready")
    barrier = Barrier(2)

    def attempt(agent: str) -> bool:
        try:
            barrier.wait(timeout=10)
            claim_report(
                report=report,
                actor=ArtefactAttribution.from_agent(user.id, agent),
                user=user,
                was_impersonated=False,
            )
            return True
        except ReportClaimConflict:
            return False
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {agent: pool.submit(attempt, agent) for agent in ("agent-one", "agent-two")}
        results = {agent: future.result(timeout=20) for agent, future in futures.items()}
        assert sorted(results.values()) == [False, True]
    winning_agent = next(agent for agent, succeeded in results.items() if succeeded)
    assert not SignalReportAssignment.all_teams.filter(report=report).exists()
    artefact = SignalReportArtefact.objects.get(report=report, type="work_claim")
    assert artefact.actor_agent == winning_agent
    assert artefact.created_by_id == user.id
    claim = get_active_claim(team_id=team.id, report_id=report.id)
    assert claim is not None
    assert claim.claim_id == artefact.id
    assert claim.actor_agent == winning_agent
    assert claim.actor_user_id == user.id


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("same_operation", [False, True])
def test_concurrent_assignment_writes_create_one_revision(same_operation: bool) -> None:
    organization = Organization.objects.create(name="Assignment test")
    team = Team.objects.create(organization=organization)
    report = SignalReport.objects.create(team=team, status="ready")
    with patch("products.signals.backend.assignment_service.assignment_writer_enabled", return_value=True):
        service = ReportAssignmentService(team=team, report_id=str(report.id))
    snapshot = service.read()
    proposal = AssignmentProposal(
        operation_id=uuid4(),
        expected_state=snapshot.state,
        source="research",
        outcome="no_suitable_owner",
    )
    other = proposal if same_operation else proposal.model_copy(update={"operation_id": uuid4()})
    barrier = Barrier(2)

    def attempt(value: AssignmentProposal) -> str:
        try:
            barrier.wait(timeout=10)
            result = service.apply(value, actor=ArtefactAttribution.system())
            return "replayed" if result.replayed else "applied"
        except StaleAssignmentProposal:
            return "stale"
        finally:
            connections.close_all()

    with patch("products.signals.backend.assignment_service.assignment_writer_enabled", return_value=True):
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(attempt, value) for value in (proposal, other)]
            results = sorted(future.result(timeout=20) for future in futures)
    assert results == ["applied", "replayed" if same_operation else "stale"]
    assert report.assignment_revisions.for_team(team.id).count() == 1
    assert report.artefacts.filter(type="assignment_decision").count() == 1
