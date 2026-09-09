from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from django.db import connections

from posthog.models import Organization, Team, User

from products.signals.backend.artefact_attribution import ArtefactAttribution
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportAssignment
from products.signals.backend.report_assignments import ReportClaimConflict, claim_report


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
        futures = [pool.submit(attempt, agent) for agent in ("agent-one", "agent-two")]
        assert sorted(future.result(timeout=20) for future in futures) == [False, True]
    assert SignalReportAssignment.all_teams.filter(report=report).count() == 1
    assert SignalReportArtefact.objects.filter(report=report, type="work_claim").count() == 1
