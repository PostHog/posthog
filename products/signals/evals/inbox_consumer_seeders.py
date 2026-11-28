from __future__ import annotations

import json
from typing import Any

from django.utils import timezone

from posthog.models import Team, User

from products.posthog_ai.evals.error_tracking.seeders import seed_error_tracking_issues
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.tasks.backend.facade.agents import CustomPromptSandboxContext

from .inbox_consumer_fixture import REPORTS, InboxReport


def _create_report(team: Team, user: User, spec: InboxReport, *, signal_count: int) -> SignalReport:
    now = timezone.now()
    report = SignalReport.objects.create(
        team=team,
        status=spec.status,
        title=spec.title,
        summary=spec.summary,
        signal_count=signal_count,
        total_weight=float(signal_count),
        latest_actionability=spec.actionability,
        latest_already_addressed=False,
        promoted_at=now,
        first_visible_at=now,
    )
    SignalReportArtefact.objects.create(
        team=team,
        report=report,
        type=SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT,
        content=json.dumps({"priority": spec.priority, "explanation": "Set by the inbox consumer eval seeder."}),
    )
    if spec.for_user:
        SignalReportArtefact.objects.create(
            team=team,
            report=report,
            type=SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS,
            content=json.dumps([{"user_uuid": str(user.uuid)}]),
        )
    return report


def seed_inbox(context: CustomPromptSandboxContext) -> dict[str, Any]:
    """Seed the error tracking issues and the inbox reports that describe them.

    Returns ``reports`` keyed by ``InboxReport.key``, each with the ``id`` and ``title`` the scorers match
    on, next to the error tracking seeder's ``lookup_issues``.
    """
    seed = seed_error_tracking_issues(context)
    team = Team.objects.get(id=context.team_id)
    user = User.objects.get(id=context.user_id)
    reports = {spec.key: _create_report(team, user, spec, signal_count=3 + index) for index, spec in enumerate(REPORTS)}
    return {
        **seed,
        "reports": {key: {"id": str(report.id), "title": report.title} for key, report in reports.items()},
    }
