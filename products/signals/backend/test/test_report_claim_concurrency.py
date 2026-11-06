from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from unittest.mock import patch

from django.db import connections

from posthog.models import Organization, Team, User

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.artefact_schemas import SuggestedReviewers
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportAssignment
from products.signals.backend.report_assignments import ReportClaimConflict, claim_report
from products.signals.backend.report_claims import get_active_claim
from products.signals.backend.reviewer_rules import ReviewerProposal, ReviewerRules, StaleReviewerProposal


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
@pytest.mark.parametrize("legacy_human_edit", [False, True])
def test_concurrent_reviewer_proposals_have_one_winner(legacy_human_edit: bool) -> None:
    organization = Organization.objects.create(name="Assignment test")
    team = Team.objects.create(organization=organization)
    report = SignalReport.objects.create(team=team, status="ready")
    if legacy_human_edit:
        SignalReportArtefact.objects.create(
            team=team, report=report, type="suggested_reviewers", content="[]", actor_kind="user"
        )
    proposal = ReviewerProposal(
        expected_state=ReviewerRules.read_for_report(team_id=team.id, report_id=str(report.id)).state
    )
    barrier = Barrier(2)

    def attempt() -> str:
        try:
            barrier.wait(timeout=10)
            SignalReportArtefact.append_status(
                team_id=team.id,
                report_id=str(report.id),
                content=SuggestedReviewers(root=[]),
                attribution=ArtefactAttribution.system(),
                reviewer_proposal=proposal,
            )
            return "applied"
        except StaleReviewerProposal:
            return "stale"
        finally:
            connections.close_all()

    with (
        patch("products.signals.backend.reviewer_rules.assignment_writer_enabled", return_value=True),
        patch("products.signals.backend.reviewer_rules.assignment_side_effects_enabled", return_value=False),
    ):
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(attempt) for _ in range(2)]
            assert sorted(future.result(timeout=20) for future in futures) == ["applied", "stale"]
    assert report.artefacts.filter(type="suggested_reviewers").count() == 1
    assert report.artefacts.filter(type="reviewer_corrections").count() == 1
