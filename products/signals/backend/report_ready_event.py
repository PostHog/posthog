"""The `$signals_report_ready` CDP internal event, which lets a destination act on a report as soon as it is ready.

The event only nudges. It carries the report id and the fields a destination filters on, not the report body,
so a consumer re-fetches the report through the API, under its own credentials.
"""

from collections.abc import Callable
from typing import Any

import structlog
from pydantic import ValidationError

from posthog.models import Team
from posthog.ph_client import feature_enabled_or_false

from products.cdp.backend.internal_events import InternalEventEvent, produce_internal_event
from products.signals.backend.artefact_schemas import SuggestedReviewers, priority_from_judgment
from products.signals.backend.models import SignalReport, SignalReportArtefact
from products.signals.backend.report_urls import build_bare_report_url
from products.signals.backend.signal_metadata import fetch_source_products_for_reports

logger = structlog.get_logger(__name__)

REPORT_READY_EVENT = "$signals_report_ready"
REPORT_READY_EVENT_FLAG = "signals-report-ready-event"


def report_ready_event_enabled(team: Team) -> bool:
    organization_id = str(team.organization_id)
    return (
        feature_enabled_or_false(
            REPORT_READY_EVENT_FLAG,
            organization_id,
            groups={"organization": organization_id},
            group_properties={"organization": {"id": organization_id}},
            send_feature_flag_events=False,
            only_evaluate_locally=True,
        )
        is True
    )


def _latest_artefact_content(report: SignalReport, artefact_type: str) -> str | None:
    return (
        SignalReportArtefact.objects.filter(team_id=report.team_id, report_id=report.id, type=artefact_type)
        .order_by("-created_at")
        .values_list("content", flat=True)
        .first()
    )


def _suggested_reviewer_logins(report: SignalReport) -> list[str]:
    content = _latest_artefact_content(report, SignalReportArtefact.ArtefactType.SUGGESTED_REVIEWERS)
    if not content:
        return []
    try:
        entries = SuggestedReviewers.model_validate_json(content).root
    except ValidationError:
        return []
    logins: list[str] = []
    for entry in entries:
        login = entry.github_login.lower() if entry.github_login else None
        if login and login not in logins:
            logins.append(login)
    return logins


def _source_products(team: Team, report_id: str) -> list[str]:
    # The list lives in ClickHouse. A failed read must not cost the event, because the consumer re-fetches anyway.
    try:
        meta = fetch_source_products_for_reports(team, [report_id]).get(report_id)
    except Exception:
        logger.exception("signals.report_ready_event.source_products_failed", report_id=report_id)
        return []
    return meta.source_products if meta else []


def report_ready_properties(report: SignalReport) -> dict[str, Any]:
    """Property names follow `SignalReportSerializer` where the API has the field."""
    report_id = str(report.id)
    return {
        "report_id": report_id,
        "report_url": build_bare_report_url(report.team_id, report_id),
        "title": report.title,
        "priority": priority_from_judgment(
            _latest_artefact_content(report, SignalReportArtefact.ArtefactType.PRIORITY_JUDGMENT)
        ),
        "actionability": report.latest_actionability,
        "source_products": _source_products(report.team, report_id),
        "repo_slug": report.selected_repository(),
        "suggested_reviewers": _suggested_reviewer_logins(report),
        "updated_at": report.updated_at.isoformat() if report.updated_at else None,
    }


def emit_report_ready_event(*, team_id: int, report_id: str, is_safety_suppressed: Callable[[str, int], bool]) -> None:
    """Produce the event for a report that just became READY, when the organization has the flag.

    `is_safety_suppressed` comes from the receivers module, which imports this one.
    """
    report = SignalReport.objects.select_related("team").filter(team_id=team_id, id=report_id).first()
    if report is None or report.status != SignalReport.Status.READY:
        # A later transaction moved the report on before this one's commit hook ran.
        return
    if not report_ready_event_enabled(report.team):
        return
    # The safety judge marked this report's text as attacker-influenced, so it must not leave PostHog.
    if is_safety_suppressed(report_id, team_id):
        return
    produce_internal_event(
        team_id=team_id,
        event=InternalEventEvent(
            event=REPORT_READY_EVENT,
            distinct_id=report_id,
            properties=report_ready_properties(report),
            url=build_bare_report_url(team_id, report_id),
        ),
    )
