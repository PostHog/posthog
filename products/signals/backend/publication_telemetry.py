from __future__ import annotations

import json
from typing import Literal

from django.utils import timezone

from posthog.event_usage import groups
from posthog.models import Team
from posthog.ph_client import ph_scoped_capture

from products.signals.backend.models import SignalReport, SignalReportArtefact


def capture_research_access_event(
    *,
    team_id: int,
    origin: Literal["pipeline", "scout"],
    reason: str,
    fallback: bool,
    report_id: str | None = None,
    scout_config_id: str | None = None,
) -> None:
    team = Team.objects.select_related("organization").get(id=team_id)
    with ph_scoped_capture() as capture:
        capture(
            distinct_id=str(team.uuid),
            event="signal_research_fallback" if fallback else "signal_research_blocked",
            groups=groups(team.organization, team),
            properties={
                "team_id": team_id,
                "report_id": report_id,
                "scout_config_id": scout_config_id,
                "origin": origin,
                "reason": reason,
                "research_mode": "data_only" if fallback else "blocked",
            },
        )


def publication_attention_reason(
    publication_status: str, pending_reason: str | None, actionability: str | None
) -> str | None:
    attention_reason = None
    if publication_status == SignalReport.Status.FAILED:
        attention_reason = "execution_failure"
    elif publication_status == SignalReport.Status.PENDING_INPUT:
        attention_reason = (
            "repo_selection_required"
            if pending_reason == "repo_selection_required"
            else "human_decision"
            if actionability == "requires_human_input" or pending_reason == "agent_requested"
            else None
        )
    return attention_reason


def capture_first_publication(
    team_id: int, report_id: str, publication_status: str, pending_reason: str | None = None
) -> None:
    claimed = SignalReport.objects.filter(
        team_id=team_id,
        id=report_id,
        first_visible_at__isnull=False,
        first_publication_event_sent_at__isnull=True,
    ).update(first_publication_event_sent_at=timezone.now())
    if not claimed:
        return
    report = SignalReport.objects.select_related("team__organization").get(team_id=team_id, id=report_id)
    contents = {
        kind: json.loads(content)
        for kind, content in SignalReportArtefact.objects.filter(
            team_id=team_id,
            report_id=report_id,
            type__in=["repo_selection", "actionability_judgment"],
        )
        .order_by("created_at", "id")
        .values_list("type", "content")
    }
    selection = contents.get("repo_selection", {})
    context = report.research_context or selection.get("research_context") or {}
    actionability = contents.get("actionability_judgment", {}).get("actionability")
    attention_reason = publication_attention_reason(publication_status, pending_reason, actionability)
    mode = context.get("mode", "unknown")
    scout_authored = (
        bool(report.scout_idempotency_key)
        or SignalReportArtefact.objects.filter(
            team_id=team_id, report_id=report_id, type="note", content__contains="via emit_report."
        ).exists()
    )
    with ph_scoped_capture() as capture:
        capture(
            distinct_id=str(report.team.uuid),
            event="signal_report_first_published",
            groups=groups(report.team.organization, report.team),
            properties={
                "team_id": team_id,
                "report_id": report_id,
                "origin": "scout" if scout_authored else "pipeline",
                "publication_status": publication_status,
                "actionability": actionability,
                "research_mode": mode,
                "attention_reason": attention_reason,
                "fallback_reason": context.get("repository_status") if mode == "data_only" else None,
            },
        )
